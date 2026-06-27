import json
from calendar import monthrange
from datetime import datetime, date, time, timedelta

# Django
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

# Bibliotecas de terceiros
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Imports locais
from .models import Escala, DiaEscala, Funcionario, Turno, Feriado, ConfiguracaoSistema, Grupo
from .services import GeradorEscala



def login_view(request):
    """View de login personalizada"""
    if request.user.is_authenticated:
        return redirect('escala:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'✅ Bem-vindo, {user.get_full_name() or user.username}!')
            next_url = request.GET.get('next', 'escala:dashboard')
            return redirect(next_url)
        else:
            messages.error(request, '❌ Usuário ou senha incorretos!')
    
    return render(request, 'escala/login.html')


def logout_view(request):
    """View de logout"""
    logout(request)
    messages.info(request, '👋 Você saiu do sistema com sucesso!')
    return redirect('escala:login')


# ==================== DASHBOARD ====================

@login_required
def dashboard(request):
    agora = timezone.localtime()
    hoje = agora.date()
    hora_atual = agora.time()
    tz = timezone.get_current_timezone()

    # ===== TURNOS =====
    turnos = list(Turno.objects.all().order_by('horario_entrada'))
    turno_atual = turno_anterior = turno_proximo = None

    for i, t in enumerate(turnos):
        ini, fim = t.horario_entrada, t.horario_saida
        if (ini < fim and ini <= hora_atual < fim) or (ini > fim and (hora_atual >= ini or hora_atual < fim)):
            turno_atual = t
            turno_anterior = turnos[i - 1]
            turno_proximo = turnos[(i + 1) % len(turnos)]
            break

    if not turno_atual:
        return render(request, 'escala/dashboard.html', {})

    # ===== DATETIME REAL DO TURNO (CORRETO) =====
    inicio_data = hoje
    if turno_atual.horario_entrada > turno_atual.horario_saida and hora_atual < turno_atual.horario_saida:
        inicio_data = hoje - timedelta(days=1)

    inicio_dt = timezone.make_aware(
        datetime.combine(inicio_data, turno_atual.horario_entrada), tz
    )

    fim_data = inicio_data
    if turno_atual.horario_saida <= turno_atual.horario_entrada:
        fim_data = inicio_data + timedelta(days=1)

    fim_dt = timezone.make_aware(
        datetime.combine(fim_data, turno_atual.horario_saida), tz
    )

    # ===== PROGRESSO (NÃO COMEÇA EM 100%) =====
    total_segundos = max(1, (fim_dt - inicio_dt).total_seconds())
    decorridos = (agora - inicio_dt).total_seconds()
    progresso_turno = max(0, min(100, (decorridos / total_segundos) * 100))

    # ===== TEMPO RESTANTE DO ATUAL =====
    restante = max(0, int((fim_dt - agora).total_seconds()))
    horas = restante // 3600
    minutos = (restante % 3600) // 60
    tempo_restante = f"{horas:02d}:{minutos:02d}"

    # ===== TEMPO PARA O PRÓXIMO COMEÇAR =====
    proximo_inicio_dt = fim_dt  # próximo começa quando o atual termina
    seg_proximo = max(0, int((proximo_inicio_dt - agora).total_seconds()))
    hp = seg_proximo // 3600
    mp = (seg_proximo % 3600) // 60
    tempo_para_proximo = f"{hp:02d}:{mp:02d}"

    # ===== FUNCIONÁRIOS =====
    funcionarios_turno_atual = DiaEscala.objects.filter(
        data=inicio_data,
        funcionario__turno=turno_atual,
        funcionario__ativo=True,
        situacao='TRABALHA'
    ).select_related('funcionario')

    data_turno_anterior = inicio_data
    if turno_anterior.horario_saida < turno_anterior.horario_entrada:
        data_turno_anterior = inicio_data - timedelta(days=1)

    funcionarios_turno_anterior = DiaEscala.objects.filter(
        data=data_turno_anterior,
        funcionario__turno=turno_anterior,
        funcionario__ativo=True,
        situacao='TRABALHA'
    ).select_related('funcionario')

    funcionarios_turno_proximo = DiaEscala.objects.filter(
        data=fim_data,
        funcionario__turno=turno_proximo,
        funcionario__ativo=True,
        situacao='TRABALHA'
    ).select_related('funcionario')

    context = {
        'turno_atual': turno_atual,
        'turno_anterior': turno_anterior,
        'turno_proximo': turno_proximo,
        'funcionarios_turno_atual': funcionarios_turno_atual,
        'funcionarios_turno_anterior': funcionarios_turno_anterior,
        'funcionarios_turno_proximo': funcionarios_turno_proximo,
        'progresso_turno': round(progresso_turno, 1),
        'tempo_restante': tempo_restante,
        'tempo_para_proximo': tempo_para_proximo,
    }

    return render(request, 'escala/dashboard.html', context)


# ==================== ESCALAS ====================

@login_required
def escala_lista(request):
    """Lista todas as escalas"""
    escalas = Escala.objects.all().order_by('-ano', '-mes')
    return render(request, 'escala/escala_lista.html', {'escalas': escalas})


@login_required
def escala_detalhe(request, pk):
    """Mostra detalhes de uma escala em formato de tabela por turno"""
    escala = get_object_or_404(Escala, pk=pk)

    dias_semana_abrev = {0: 'SEG', 1: 'TER', 2: 'QUA', 3: 'QUI', 4: 'SEX', 5: 'SAB', 6: 'DOM'}

    dias_mes = monthrange(escala.ano, escala.mes)[1]
    calendario_dias = []
    for dia in range(1, dias_mes + 1):
        d = date(escala.ano, escala.mes, dia)
        calendario_dias.append({
            'dia': dia,
            'dia_semana_abrev': dias_semana_abrev[d.weekday()],
            'eh_domingo': d.weekday() == 6
        })

    dias_escala = DiaEscala.objects.filter(escala=escala).select_related(
        'funcionario', 'funcionario__turno', 'turno_coberto'
    )

    SIT_MAP = {
        'TRABALHA':          ('trabalha',       '✔'),
        'FOLGA':             ('folga',           'F'),
        'FOLGA_COMPENSADA':  ('folga-compensada','C'),
        'FALTA':             ('falta',           'FT'),
        'ATESTADO':          ('atestado',        'AF'),
        'FERIAS':            ('ferias',          'FB'),
        'FOLGA_ANIVERSARIO': ('folga-aniv',      '🎂'),
        'FOLGA_FERIADO':     ('folga-feriado',   '🎉'),
    }

    def montar_linha(func_data, dias_turno=None):
        linha = {'id': func_data['id'], 'nome': func_data['nome'], 'dias': []}
        for dia in range(1, dias_mes + 1):
            situacao = func_data['dias_situacao'][dia]
            classe, simbolo = SIT_MAP.get(situacao, ('', ''))
            if situacao == 'TRABALHA' and dias_turno and dias_turno[dia]:
                simbolo = dias_turno[dia][:3].upper()
            linha['dias'].append({'classe': classe, 'simbolo': simbolo, 'situacao': situacao})
        return linha

    # Turno sections (REGULAR employees)
    turnos = list(Turno.objects.all().order_by('horario_entrada'))
    turnos_data = []
    for turno in turnos:
        func_dict = {}
        for dia_obj in dias_escala:
            if dia_obj.funcionario.turno_id != turno.id:
                continue
            fid = dia_obj.funcionario.id
            if fid not in func_dict:
                func_dict[fid] = {'id': fid, 'nome': dia_obj.funcionario.nome, 'dias_situacao': [''] * (dias_mes + 1)}
            func_dict[fid]['dias_situacao'][dia_obj.data.day] = dia_obj.situacao
        turnos_data.append({
            'nome': turno.nome,
            'horario': f"{turno.horario_entrada.strftime('%H:%M')}–{turno.horario_saida.strftime('%H:%M')}",
            'funcionarios': [montar_linha(fd) for fd in func_dict.values()],
        })

    # Folguistas section
    folguista_dict = {}
    for dia_obj in dias_escala:
        if dia_obj.funcionario.tipo != 'FOLGUISTA':
            continue
        fid = dia_obj.funcionario.id
        if fid not in folguista_dict:
            folguista_dict[fid] = {
                'id': fid,
                'nome': dia_obj.funcionario.nome,
                'dias_situacao': [''] * (dias_mes + 1),
                'dias_turno': [None] * (dias_mes + 1),
            }
        folguista_dict[fid]['dias_situacao'][dia_obj.data.day] = dia_obj.situacao
        if dia_obj.turno_coberto:
            folguista_dict[fid]['dias_turno'][dia_obj.data.day] = dia_obj.turno_coberto.nome

    folguistas_data = [
        montar_linha(fd, dias_turno=fd['dias_turno'])
        for fd in folguista_dict.values()
    ]

    context = {
        'escala': escala,
        'calendario_dias': calendario_dias,
        'turnos_data': turnos_data,
        'folguistas_data': folguistas_data,
    }
    return render(request, 'escala/escala_detalhe.html', context)


@login_required
def gerar_escala_view(request):
    """Gera uma nova escala"""
    if request.method == 'POST':
        mes = int(request.POST.get('mes'))
        ano = int(request.POST.get('ano'))
        force = request.POST.get('force') == 'on'
        
        escala_existente = Escala.objects.filter(mes=mes, ano=ano).first()
        
        if escala_existente and not force:
            messages.warning(request, f'Já existe escala para {mes:02d}/{ano}. Marque "Forçar regerar" para substituir.')
            return redirect('escala:gerar_escala')
        
        if escala_existente and force:
            escala_existente.delete()
            messages.info(request, f'Escala anterior de {mes:02d}/{ano} removida.')
        
        gerador = GeradorEscala(mes, ano)
        sucesso, escala, alertas = gerador.gerar()

        if escala is None:
            messages.error(request, '❌ Erro crítico ao gerar escala:')
            for alerta in alertas:
                messages.warning(request, alerta)
            return redirect('escala:gerar_escala')

        if sucesso:
            messages.success(request, f'✅ Escala de {mes:02d}/{ano} gerada com sucesso!')
        else:
            messages.error(request, f'⚠️ Escala gerada com problemas. Verifique os alertas.')
            for alerta in alertas:
                messages.warning(request, alerta)

        return redirect('escala:escala_detalhe', pk=escala.id)
    
    hoje = date.today()
    return render(request, 'escala/gerar_escala.html', {
        'mes_atual': hoje.month,
        'ano_atual': hoje.year,
    })


@login_required
def revalidar_escala(request, pk):
    """Revalida uma escala existente após ajustes manuais"""
    from calendar import monthrange
    
    escala = get_object_or_404(Escala, pk=pk)
    dias_mes = monthrange(escala.ano, escala.mes)[1]
    
    dias_escala = DiaEscala.objects.filter(escala=escala).select_related('funcionario', 'funcionario__turno')
    
    escala_gerada = {}
    for dia_obj in dias_escala:
        func_id = dia_obj.funcionario.id
        if func_id not in escala_gerada:
            escala_gerada[func_id] = {}
        escala_gerada[func_id][dia_obj.data.day] = dia_obj.situacao
    
    alertas = []
    config = ConfiguracaoSistema.get()

    def regime_aplica_consecutivas(regime):
        if not config.consecutivas_ativo:
            return False
        return config.consecutivas_regime == 'AMBOS' or config.consecutivas_regime == regime

    # 1. Validar folgas consecutivas
    alertas.append("🔍 VALIDANDO FOLGAS CONSECUTIVAS...")
    problemas_consecutivas = []

    if not config.consecutivas_ativo:
        alertas.append("⏭️ Regra de consecutivas desativada nas configurações")
    else:
        for func_id, dias_func in escala_gerada.items():
            funcionario = Funcionario.objects.get(id=func_id)

            if not regime_aplica_consecutivas(funcionario.regime):
                continue

            for dia in range(1, dias_mes):
                if dia not in dias_func or (dia + 1) not in dias_func:
                    continue
                if dias_func[dia] == 'FOLGA' and dias_func[dia + 1] == 'FOLGA':
                    problemas_consecutivas.append(f"⚠️ {funcionario.nome}: dias {dia} e {dia+1}")
                    break

        if problemas_consecutivas:
            alertas.append("⚠️ Folgas consecutivas encontradas:")
            alertas.extend([f"   {p}" for p in problemas_consecutivas])
        else:
            alertas.append("✅ Sem folgas consecutivas!")

    # 2. Validar domingos de folga
    alertas.append("\n🔍 VALIDANDO DOMINGOS DE FOLGA...")

    domingos = [
        dia for dia in range(1, dias_mes + 1)
        if date(escala.ano, escala.mes, dia).weekday() == 6
    ]

    problemas_domingo = []
    if domingos:
        for func_id, dias_func in escala_gerada.items():
            funcionario = Funcionario.objects.get(id=func_id)
            tem_domingo = any(
                dias_func.get(dom, 'TRABALHA') in ['FOLGA', 'FOLGA_COMPENSADA', 'FOLGA_ANIVERSARIO', 'FOLGA_FERIADO', 'FERIAS', 'ATESTADO']
                for dom in domingos
            )
            if not tem_domingo:
                problemas_domingo.append(f"⚠️ {funcionario.nome} ({funcionario.regime})")

        if problemas_domingo:
            alertas.append("⚠️ Sem nenhum domingo de folga:")
            alertas.extend([f"   {p}" for p in problemas_domingo])
        else:
            alertas.append("✅ Todos têm pelo menos 1 domingo de folga!")
    
    # 3. Validar lotação mínima
    alertas.append("\n🔍 VALIDANDO LOTAÇÃO MÍNIMA...")
    turnos = Turno.objects.all()
    problemas_lotacao = []
    
    for dia in range(1, dias_mes + 1):
        for turno in turnos:
            funcionarios_turno = Funcionario.objects.filter(
                tipo='REGULAR',
                ativo=True,
                turno=turno
            )
            
            trabalhando = 0
            for func in funcionarios_turno:
                if func.id in escala_gerada:
                    situacao = escala_gerada[func.id].get(dia, 'TRABALHA')
                    if situacao == 'TRABALHA':
                        trabalhando += 1
            
            if trabalhando < turno.minimo_funcionarios:
                problemas_lotacao.append(
                    f"⚠️ DIA {dia:02d}/{escala.mes:02d} - "
                    f"Turno {turno.nome}: {trabalhando}/{turno.minimo_funcionarios}"
                )
    
    if problemas_lotacao:
        alertas.append("⚠️ Problemas de lotação encontrados:")
        alertas.extend([f"   {p}" for p in problemas_lotacao])
    else:
        alertas.append("✅ Lotação mínima OK em todos os dias!")
    
    if problemas_lotacao or problemas_consecutivas or (domingos and problemas_domingo):
        escala.gerada_com_sucesso = False
        alertas.append("\n⚠️ Escala possui problemas pendentes")
    else:
        escala.gerada_com_sucesso = True
        alertas.append("\n✅ Escala válida! Todos os problemas foram corrigidos!")
    
    escala.observacoes = "\n".join(alertas)
    escala.save()
    
    messages.success(request, '🔄 Escala revalidada com sucesso!')
    return redirect('escala:escala_detalhe', pk=escala.id)


@login_required
@require_POST
def alterar_situacao_dia(request):
    """Altera manualmente a situação de um dia na escala"""
    try:
        data = json.loads(request.body)
        escala_id = data['escala_id']
        funcionario_id = data['funcionario_id']
        dia = int(data['dia'])
        nova_situacao = data['nova_situacao']

        SITUACOES_VALIDAS = {'TRABALHA', 'FOLGA', 'FOLGA_COMPENSADA', 'FALTA', 'ATESTADO', 'FERIAS'}
        if nova_situacao not in SITUACOES_VALIDAS:
            return JsonResponse({'sucesso': False, 'erro': 'Situação inválida!'})

        escala = Escala.objects.get(id=escala_id)
        funcionario = Funcionario.objects.get(id=funcionario_id)
        data_dia = date(escala.ano, escala.mes, dia)

        dia_escala, _ = DiaEscala.objects.get_or_create(
            escala=escala,
            funcionario=funcionario,
            data=data_dia,
            defaults={'situacao': nova_situacao}
        )
        dia_escala.situacao = nova_situacao
        dia_escala.save()

        return JsonResponse({'sucesso': True})

    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)})


@login_required
@require_POST
def trocar_folga(request):
    """Troca uma folga de dia, validando todas as regras"""
    try:
        data = json.loads(request.body)
        escala_id = data['escala_id']
        funcionario_id = data['funcionario_id']
        dia_origem = int(data['dia_origem'])
        dia_destino = int(data['dia_destino'])
        
        escala = Escala.objects.get(id=escala_id)
        funcionario = Funcionario.objects.get(id=funcionario_id)
        
        data_origem = date(escala.ano, escala.mes, dia_origem)
        data_destino = date(escala.ano, escala.mes, dia_destino)
        
        dia_escala_origem = DiaEscala.objects.get(
            escala=escala,
            funcionario=funcionario,
            data=data_origem
        )
        
        dia_escala_destino = DiaEscala.objects.get(
            escala=escala,
            funcionario=funcionario,
            data=data_destino
        )
        
        if dia_escala_origem.situacao != 'FOLGA':
            return JsonResponse({
                'sucesso': False,
                'erro': 'Só pode mover <strong>folgas regulares</strong>! Aniversários e feriados são fixos.'
            })
        
        if dia_escala_destino.situacao != 'TRABALHA':
            return JsonResponse({
                'sucesso': False,
                'erro': 'O destino deve ser um <strong>dia de trabalho</strong>!'
            })
        
        if not _mesma_semana(data_origem, data_destino):
            return JsonResponse({
                'sucesso': False,
                'erro': 'Só pode trocar folgas <strong>dentro da mesma semana</strong>!'
            })
        
        erro_domingo = _valida_domingo_obrigatorio(funcionario, escala, dia_origem, dia_destino)
        if erro_domingo:
            return JsonResponse({
                'sucesso': False,
                'erro': erro_domingo
            })
        
        if _cria_consecutivas(funcionario, escala, dia_origem, dia_destino):
            return JsonResponse({
                'sucesso': False,
                'erro': 'A troca criaria <strong>folgas consecutivas</strong>, o que não é permitido!'
            })
        
        if not _mantem_lotacao_minima(funcionario.turno, escala, data_origem, data_destino):
            return JsonResponse({
                'sucesso': False,
                'erro': 'A troca quebraria a <strong>lotação mínima</strong> do turno!'
            })
        
        dia_escala_origem.situacao = 'TRABALHA'
        dia_escala_destino.situacao = 'FOLGA'
        
        dia_escala_origem.save()
        dia_escala_destino.save()
        
        return JsonResponse({
            'sucesso': True,
            'mensagem': f'✅ Folga movida do <strong>dia {dia_origem}</strong> para o <strong>dia {dia_destino}</strong> com sucesso!'
        })
        
    except DiaEscala.DoesNotExist:
        return JsonResponse({
            'sucesso': False,
            'erro': 'Dia da escala não encontrado no banco de dados!'
        })
    except Exception as e:
        return JsonResponse({
            'sucesso': False,
            'erro': f'Erro inesperado: {str(e)}'
        })


def _mesma_semana(data1, data2):
    """Verifica se duas datas estão na mesma semana"""
    return data1.isocalendar()[1] == data2.isocalendar()[1]


def _valida_domingo_obrigatorio(funcionario, escala, dia_origem, dia_destino):
    """Valida se o funcionário manterá pelo menos 1 domingo de folga"""
    data_origem = date(escala.ano, escala.mes, dia_origem)
    eh_domingo_origem = data_origem.weekday() == 6
    
    if not eh_domingo_origem:
        return None
    
    dias = DiaEscala.objects.filter(
        escala=escala,
        funcionario=funcionario
    )
    
    domingos_folga = 0
    for d in dias:
        eh_domingo = d.data.weekday() == 6
        
        if not eh_domingo:
            continue
        
        if d.data.day == dia_origem:
            situacao_simulada = 'TRABALHA'
        elif d.data.day == dia_destino:
            situacao_simulada = 'FOLGA'
        else:
            situacao_simulada = d.situacao
        
        if situacao_simulada != 'TRABALHA':
            domingos_folga += 1
    
    if domingos_folga < 1:
        return (
            '⚠️ <strong>Operação bloqueada!</strong><br><br>'
            'Todo funcionário deve ter <strong>pelo menos 1 domingo de folga</strong> por mês.<br>'
            'Esta troca removeria o único domingo de descanso do funcionário.'
        )
    
    return None


def _cria_consecutivas(funcionario, escala, dia_origem, dia_destino):
    """Verifica se troca cria folgas consecutivas"""
    dias = DiaEscala.objects.filter(
        escala=escala,
        funcionario=funcionario
    ).order_by('data')
    
    situacoes = {}
    for d in dias:
        dia_num = d.data.day
        if dia_num == dia_origem:
            situacoes[dia_num] = 'TRABALHA'
        elif dia_num == dia_destino:
            situacoes[dia_num] = 'FOLGA'
        else:
            situacoes[dia_num] = d.situacao
    
    dias_ordenados = sorted(situacoes.keys())
    for i in range(len(dias_ordenados) - 1):
        hoje = dias_ordenados[i]
        amanha = dias_ordenados[i + 1]
        
        if amanha - hoje == 1:
            if situacoes[hoje] != 'TRABALHA' and situacoes[amanha] != 'TRABALHA':
                return True
    
    return False


def _mantem_lotacao_minima(turno, escala, data_origem, data_destino):
    """Verifica se mantém lotação mínima nos dois dias"""
    for data in [data_origem, data_destino]:
        trabalhando = DiaEscala.objects.filter(
            escala=escala,
            data=data,
            funcionario__turno=turno,
            situacao='TRABALHA'
        ).count()
        
        if data == data_origem:
            trabalhando += 1
        elif data == data_destino:
            trabalhando -= 1
        
        if trabalhando < turno.minimo_funcionarios:
            return False
    
    return True


# ==================== FUNCIONÁRIOS ====================

@login_required
def funcionario_lista(request):
    """Lista todos os funcionários"""
    funcionarios = Funcionario.objects.all().select_related('turno').order_by('turno', 'tipo', 'nome')
    
    regulares = funcionarios.filter(tipo='REGULAR', ativo=True)
    folguistas = funcionarios.filter(tipo='FOLGUISTA', ativo=True)
    inativos = funcionarios.filter(ativo=False)
    
    context = {
        'regulares': regulares,
        'folguistas': folguistas,
        'inativos': inativos,
    }
    return render(request, 'escala/funcionario_lista.html', context)


@login_required
def funcionario_novo(request):
    """Cadastra um novo funcionário"""
    if request.method == 'POST':
        try:
            nome = request.POST.get('nome')
            data_nascimento = request.POST.get('data_nascimento')
            data_admissao = request.POST.get('data_admissao')
            tipo = request.POST.get('tipo')
            turno_id = request.POST.get('turno')
            turno = Turno.objects.get(id=turno_id) if turno_id else None
            grupo_id = request.POST.get('grupo')
            grupo = Grupo.objects.get(id=grupo_id) if grupo_id else None
            regime = request.POST.get('regime', '6x1')
            folga_fixa = request.POST.get('folga_fixa_dia')
            folga_fixa_dia = int(folga_fixa) if folga_fixa not in ('', None) else None
            ferias_inicio = request.POST.get('ferias_inicio') or None
            ferias_fim = request.POST.get('ferias_fim') or None

            funcionario = Funcionario.objects.create(
                nome=nome,
                data_nascimento=data_nascimento,
                data_admissao=data_admissao,
                tipo=tipo,
                turno=turno,
                grupo=grupo,
                regime=regime,
                folga_fixa_dia=folga_fixa_dia,
                ativo=True,
                ferias_inicio=ferias_inicio,
                ferias_fim=ferias_fim,
            )

            # Turnos e grupos habilitados (folguista)
            turnos_hab = request.POST.getlist('turnos_habilitados')
            grupos_hab = request.POST.getlist('grupos_habilitados')
            if turnos_hab:
                funcionario.turnos_habilitados.set(Turno.objects.filter(id__in=turnos_hab))
            if grupos_hab:
                funcionario.grupos_habilitados.set(Grupo.objects.filter(id__in=grupos_hab))

            messages.success(request, f'✅ Funcionário {funcionario.nome} cadastrado com sucesso!')
            return redirect('escala:funcionario_lista')

        except Exception as e:
            messages.error(request, f'❌ Erro ao cadastrar: {str(e)}')

    turnos = Turno.objects.all()
    grupos = Grupo.objects.all()
    return render(request, 'escala/funcionario_form.html', {'turnos': turnos, 'grupos': grupos})


@login_required
def funcionario_editar(request, pk):
    """Edita um funcionário existente"""
    funcionario = get_object_or_404(Funcionario, pk=pk)
    
    if request.method == 'POST':
        try:
            funcionario.nome = request.POST.get('nome')
            funcionario.data_nascimento = request.POST.get('data_nascimento')
            funcionario.data_admissao = request.POST.get('data_admissao')
            funcionario.tipo = request.POST.get('tipo')
            if funcionario.tipo == 'FOLGUISTA':
                funcionario.turno = None
            else:
                turno_id = request.POST.get('turno')
                funcionario.turno = Turno.objects.get(id=turno_id) if turno_id else None
            grupo_id = request.POST.get('grupo')
            funcionario.grupo = Grupo.objects.get(id=grupo_id) if grupo_id else None
            funcionario.regime = request.POST.get('regime', '6x1')
            folga_fixa = request.POST.get('folga_fixa_dia')
            funcionario.folga_fixa_dia = int(folga_fixa) if folga_fixa not in ('', None) else None
            funcionario.ativo = request.POST.get('ativo') == 'on'
            funcionario.ferias_inicio = request.POST.get('ferias_inicio') or None
            funcionario.ferias_fim = request.POST.get('ferias_fim') or None
            funcionario.save()

            turnos_hab = request.POST.getlist('turnos_habilitados')
            grupos_hab = request.POST.getlist('grupos_habilitados')
            funcionario.turnos_habilitados.set(Turno.objects.filter(id__in=turnos_hab))
            funcionario.grupos_habilitados.set(Grupo.objects.filter(id__in=grupos_hab))

            messages.success(request, f'✅ Funcionário {funcionario.nome} atualizado com sucesso!')
            return redirect('escala:funcionario_lista')

        except Exception as e:
            messages.error(request, f'❌ Erro ao atualizar: {str(e)}')

    turnos = Turno.objects.all()
    grupos = Grupo.objects.all()
    context = {
        'funcionario': funcionario,
        'turnos': turnos,
        'grupos': grupos,
        'turnos_habilitados_ids': list(funcionario.turnos_habilitados.values_list('id', flat=True)),
        'grupos_habilitados_ids': list(funcionario.grupos_habilitados.values_list('id', flat=True)),
    }
    return render(request, 'escala/funcionario_form.html', context)


@login_required
@require_POST
def funcionario_deletar(request, pk):
    """Deleta um funcionário"""
    try:
        funcionario = get_object_or_404(Funcionario, pk=pk)
        nome = funcionario.nome
        funcionario.delete()
        
        messages.success(request, f'✅ Funcionário {nome} removido com sucesso!')
    except Exception as e:
        messages.error(request, f'❌ Erro ao remover: {str(e)}')
    
    return redirect('escala:funcionario_lista')


# ==================== TURNOS ====================

@login_required
def turno_lista(request):
    """Lista todos os turnos"""
    turnos = Turno.objects.all().order_by('horario_entrada')
    return render(request, 'escala/turno_lista.html', {'turnos': turnos})


@login_required
def turno_novo(request):
    """Cadastra novo turno"""
    if request.method == 'POST':
        try:
            Turno.objects.create(
                nome=request.POST.get('nome'),
                horario_entrada=request.POST.get('horario_entrada'),
                horario_saida=request.POST.get('horario_saida'),
                minimo_funcionarios=request.POST.get('minimo_funcionarios'),
            )
            messages.success(request, f'✅ Turno cadastrado!')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)}')
    
    return redirect('escala:turno_lista')


@login_required
def turno_editar(request, pk):
    """Edita turno"""
    turno = get_object_or_404(Turno, pk=pk)
    
    if request.method == 'POST':
        try:
            turno.nome = request.POST.get('nome')
            turno.horario_entrada = request.POST.get('horario_entrada')
            turno.horario_saida = request.POST.get('horario_saida')
            turno.minimo_funcionarios = request.POST.get('minimo_funcionarios')
            turno.save()
            messages.success(request, f'✅ Turno atualizado!')
        except Exception as e:
            messages.error(request, f'❌ Erro: {str(e)}')
    
    return redirect('escala:turno_lista')


@login_required
@require_POST
def turno_deletar(request, pk):
    """Deleta turno"""
    try:
        turno = get_object_or_404(Turno, pk=pk)
        turno.delete()
        messages.success(request, f'✅ Turno removido!')
    except Exception as e:
        messages.error(request, f'❌ Erro: {str(e)}')
    
    return redirect('escala:turno_lista')



@login_required
def exportar_escala_excel(request, pk):
    """Exporta escala para Excel com formatação"""
    escala = get_object_or_404(Escala, pk=pk)
    
    # Criar workbook
    wb = Workbook()
    
    # Buscar dados
    dias_mes = monthrange(escala.ano, escala.mes)[1]
    dias_escala = DiaEscala.objects.filter(escala=escala).select_related('funcionario', 'funcionario__turno')
    
    # Organizar por turno (dinâmico — aceita qualquer nome de turno)
    turnos_ordem = list(Turno.objects.values_list('nome', flat=True).order_by('horario_entrada'))
    turnos_data = {nome: {} for nome in turnos_ordem}

    for dia_obj in dias_escala:
        turno_nome = dia_obj.funcionario.turno.nome
        func_id = dia_obj.funcionario.id
        func_nome = dia_obj.funcionario.nome

        if turno_nome not in turnos_data:
            turnos_data[turno_nome] = {}

        if func_id not in turnos_data[turno_nome]:
            turnos_data[turno_nome][func_id] = {
                'nome': func_nome,
                'dias': {}
            }

        turnos_data[turno_nome][func_id]['dias'][dia_obj.data.day] = dia_obj.situacao

    # Criar abas por turno
    cores = {
        'TRABALHA': 'D4EDDA',
        'FOLGA': 'F8D7DA',
        'FOLGA_COMPENSADA': 'FFE0B2',
        'FALTA': 'EF9A9A',
        'ATESTADO': 'E1BEE7',
        'FERIAS': 'B3E5FC',
        'FOLGA_ANIVERSARIO': 'FFF3CD',
        'FOLGA_FERIADO': 'D1ECF1',
    }

    simbolos = {
        'TRABALHA': '✓',
        'FOLGA': 'F',
        'FOLGA_COMPENSADA': 'C',
        'FALTA': 'FT',
        'ATESTADO': 'AF',
        'FERIAS': 'FB',
        'FOLGA_ANIVERSARIO': '🎂',
        'FOLGA_FERIADO': '🎉',
    }
    
    dias_semana = {0: 'SEG', 1: 'TER', 2: 'QUA', 3: 'QUI', 4: 'SEX', 5: 'SAB', 6: 'DOM'}
    
    # Remover aba padrão
    wb.remove(wb.active)
    
    for turno_nome in turnos_ordem:
        if not turnos_data.get(turno_nome):
            continue
            
        ws = wb.create_sheet(title=f"Turno {turno_nome.title()}")
        
        # Título
        ws.merge_cells('A1:AH1')
        ws['A1'] = f'ESCALA {escala.mes:02d}/{escala.ano} - TURNO {turno_nome}'
        ws['A1'].font = Font(size=14, bold=True)
        ws['A1'].alignment = Alignment(horizontal='center')
        
        # Cabeçalho da tabela
        ws['A3'] = 'FUNCIONÁRIO'
        ws['A3'].font = Font(bold=True)
        ws['A3'].fill = PatternFill(start_color='ECF0F1', end_color='ECF0F1', fill_type='solid')
        
        # Dias do mês
        for dia in range(1, dias_mes + 1):
            col = dia + 1
            data = date(escala.ano, escala.mes, dia)
            dia_semana_nome = dias_semana[data.weekday()]
            
            cell = ws.cell(row=3, column=col)
            cell.value = f"{dia}\n{dia_semana_nome}"
            cell.font = Font(bold=True, size=9)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            
            # Destaque para domingos
            if data.weekday() == 6:
                cell.fill = PatternFill(start_color='FFC107', end_color='FFC107', fill_type='solid')
            else:
                cell.fill = PatternFill(start_color='ECF0F1', end_color='ECF0F1', fill_type='solid')
        
        # Dados dos funcionários
        row = 4
        for func_id, func_data in sorted(turnos_data[turno_nome].items(), key=lambda x: x[1]['nome']):
            ws.cell(row=row, column=1).value = func_data['nome']
            ws.cell(row=row, column=1).font = Font(bold=True)
            
            for dia in range(1, dias_mes + 1):
                col = dia + 1
                situacao = func_data['dias'].get(dia, 'TRABALHA')
                
                cell = ws.cell(row=row, column=col)
                cell.value = simbolos.get(situacao, '')
                cell.alignment = Alignment(horizontal='center', vertical='center')
                
                # Aplicar cor
                if situacao in cores:
                    cell.fill = PatternFill(start_color=cores[situacao], end_color=cores[situacao], fill_type='solid')
            
            row += 1
        
        # Ajustar largura das colunas
        ws.column_dimensions['A'].width = 25
        for col in range(2, dias_mes + 2):
            ws.column_dimensions[ws.cell(row=3, column=col).column_letter].width = 5
        
        # Altura da linha do cabeçalho
        ws.row_dimensions[3].height = 30
        
        # Bordas
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=1, max_col=dias_mes + 1):
            for cell in row:
                cell.border = thin_border
    
    # Preparar resposta HTTP
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Escala_{escala.mes:02d}_{escala.ano}.xlsx"'
    
    wb.save(response)
    return response


# ==================== CONFIGURAÇÕES ====================

@login_required
def configuracao_view(request):
    config = ConfiguracaoSistema.get()
    if request.method == 'POST':
        config.consecutivas_ativo = request.POST.get('consecutivas_ativo') == 'on'
        config.consecutivas_regime = request.POST.get('consecutivas_regime', 'AMBOS')
        config.domingo_ativo = request.POST.get('domingo_ativo') == 'on'
        config.save()
        messages.success(request, '✅ Configurações salvas!')
        return redirect('escala:configuracao')
    return render(request, 'escala/configuracao.html', {'config': config})


# ==================== GRUPOS ====================

@login_required
def grupo_lista(request):
    grupos = Grupo.objects.all()
    return render(request, 'escala/grupo_lista.html', {'grupos': grupos})

@login_required
def grupo_novo(request):
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        if nome:
            Grupo.objects.get_or_create(nome=nome)
            messages.success(request, f'✅ Grupo "{nome}" cadastrado!')
        return redirect('escala:grupo_lista')
    return render(request, 'escala/grupo_form.html', {})

@login_required
def grupo_editar(request, pk):
    grupo = get_object_or_404(Grupo, pk=pk)
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        if nome:
            grupo.nome = nome
            grupo.save()
            messages.success(request, f'✅ Grupo atualizado!')
        return redirect('escala:grupo_lista')
    return render(request, 'escala/grupo_form.html', {'grupo': grupo})

@login_required
@require_POST
def grupo_deletar(request, pk):
    grupo = get_object_or_404(Grupo, pk=pk)
    grupo.delete()
    messages.success(request, '✅ Grupo removido!')
    return redirect('escala:grupo_lista')


# ==================== FERIADOS ====================

@login_required
def feriado_lista(request):
    """Lista feriados do ano corrente (ou ano selecionado)"""
    ano_atual = date.today().year
    ano = int(request.GET.get('ano', ano_atual))

    feriados = Feriado.objects.filter(data__year=ano).order_by('data')
    anos_disponiveis = (
        Feriado.objects.dates('data', 'year').values_list('data__year', flat=True)
    )

    context = {
        'feriados': feriados,
        'ano': ano,
        'ano_atual': ano_atual,
        'anos_disponiveis': sorted(set(anos_disponiveis)),
        'total_feriados': feriados.count(),
    }
    return render(request, 'escala/feriado_lista.html', context)


@login_required
def feriado_novo(request):
    """Cadastra novo feriado"""
    if request.method == 'POST':
        try:
            nome = request.POST.get('nome')
            data = request.POST.get('data')
            tipo = request.POST.get('tipo')
            
            # Verificar se já existe feriado nesta data
            if Feriado.objects.filter(data=data).exists():
                messages.error(request, '❌ Já existe um feriado cadastrado nesta data!')
                return redirect('escala:feriado_novo')
            
            Feriado.objects.create(
                nome=nome,
                data=data,
                tipo=tipo
            )
            
            messages.success(request, f'✅ Feriado "{nome}" cadastrado com sucesso!')
            return redirect('escala:feriado_lista')
            
        except Exception as e:
            messages.error(request, f'❌ Erro ao cadastrar: {str(e)}')
    
    return render(request, 'escala/feriado_form.html')


@login_required
def feriado_editar(request, pk):
    """Edita um feriado existente"""
    feriado = get_object_or_404(Feriado, pk=pk)
    
    if request.method == 'POST':
        try:
            feriado.nome = request.POST.get('nome')
            nova_data = request.POST.get('data')
            
            # Verificar se a nova data já existe (exceto o próprio feriado)
            if Feriado.objects.filter(data=nova_data).exclude(pk=pk).exists():
                messages.error(request, '❌ Já existe um feriado cadastrado nesta data!')
                return redirect('escala:feriado_editar', pk=pk)
            
            feriado.data = nova_data
            feriado.tipo = request.POST.get('tipo')
            feriado.save()
            
            messages.success(request, f'✅ Feriado "{feriado.nome}" atualizado!')
            return redirect('escala:feriado_lista')
            
        except Exception as e:
            messages.error(request, f'❌ Erro ao atualizar: {str(e)}')
    
    context = {'feriado': feriado}
    return render(request, 'escala/feriado_form.html', context)


@login_required
@require_POST
def feriado_deletar(request, pk):
    """Deleta um feriado"""
    try:
        feriado = get_object_or_404(Feriado, pk=pk)
        nome = feriado.nome
        feriado.delete()
        
        messages.success(request, f'✅ Feriado "{nome}" removido com sucesso!')
    except Exception as e:
        messages.error(request, f'❌ Erro ao remover: {str(e)}')
    
    return redirect('escala:feriado_lista')


# ==================== CALENDÁRIO ====================

@login_required
def calendario_view(request):
    """Calendário visual com escalas e ocorrências"""
    from calendar import monthrange
    from collections import defaultdict
    import json
    
    # Pegar mês/ano dos parâmetros ou usar atual
    hoje = date.today()
    mes = int(request.GET.get('mes', hoje.month))
    ano = int(request.GET.get('ano', hoje.year))
    
    # Validar mês
    if mes < 1 or mes > 12:
        mes = hoje.month
    
    # Buscar escala do mês
    try:
        escala = Escala.objects.get(mes=mes, ano=ano)
        dias_escala = DiaEscala.objects.filter(escala=escala).select_related(
            'funcionario', 'funcionario__turno'
        )
    except Escala.DoesNotExist:
        escala = None
        dias_escala = []
    
    # Buscar feriados do mês
    data_inicio = date(ano, mes, 1)
    dias_mes = monthrange(ano, mes)[1]
    data_fim = date(ano, mes, dias_mes)
    
    feriados = Feriado.objects.filter(
        data__gte=data_inicio,
        data__lte=data_fim
    )
    feriados_dict = {f.data.day: f for f in feriados}

    # Organizar dados por dia
    calendario_dias = []
    calendario_dias_json = []

    for dia in range(1, dias_mes + 1):
        data = date(ano, mes, dia)
        dia_semana = data.weekday()

        turnos_info = {
            'MANHA': {'funcionarios': [], 'minimo': 0, 'atual': 0},
            'TARDE': {'funcionarios': [], 'minimo': 0, 'atual': 0},
            'NOITE': {'funcionarios': [], 'minimo': 0, 'atual': 0},
        }

        if escala:
            for dia_obj in dias_escala:
                if dia_obj.data.day == dia and dia_obj.situacao == 'TRABALHA':
                    turno_nome = dia_obj.funcionario.turno.nome
                    if turno_nome in turnos_info:
                        turnos_info[turno_nome]['funcionarios'].append(dia_obj.funcionario.nome)

            turnos = Turno.objects.all()
            for turno in turnos:
                if turno.nome in turnos_info:
                    turnos_info[turno.nome]['minimo'] = turno.minimo_funcionarios
                    turnos_info[turno.nome]['atual'] = len(turnos_info[turno.nome]['funcionarios'])

        feriado_obj = feriados_dict.get(dia)

        dia_info = {
            'dia': dia,
            'data': data,
            'dia_semana': dia_semana,
            'eh_domingo': dia_semana == 6,
            'eh_sabado': dia_semana == 5,
            'eh_hoje': data == hoje,
            'eh_passado': data < hoje,
            'eh_futuro': data > hoje,
            'feriado': feriado_obj,
            'turnos': turnos_info,
        }

        calendario_dias.append(dia_info)

        dia_info_json = {
            'dia': dia,
            'data': data.isoformat(),
            'dia_semana': dia_semana,
            'eh_domingo': dia_semana == 6,
            'eh_sabado': dia_semana == 5,
            'eh_hoje': data == hoje,
            'eh_passado': data < hoje,
            'eh_futuro': data > hoje,
            'feriado': {
                'nome': feriado_obj.nome,
                'tipo': feriado_obj.get_tipo_display(),
                'eh_dia_util': feriado_obj.eh_dia_util()
            } if feriado_obj else None,
            'turnos': turnos_info,
        }

        calendario_dias_json.append(dia_info_json)
    
    # Calcular dias vazios no início do mês
    primeiro_dia = date(ano, mes, 1)
    dia_semana_inicial = primeiro_dia.weekday()
    # Ajustar para domingo = 0
    dias_vazios = (dia_semana_inicial + 1) % 7
    
    # Meses em português brasileiro
    meses_pt = [
        'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
    ]
    
    # Meses para navegação
    meses = [
        {'num': i, 'nome': meses_pt[i-1]}
        for i in range(1, 13)
    ]
    
    # Nome do mês atual em português
    mes_nome_pt = f"{meses_pt[mes-1]} {ano}"
    
    context = {
        'ano': ano,
        'mes': mes,
        'mes_nome': mes_nome_pt,
        'calendario_dias': calendario_dias,  # Para o template Django
        'calendario_dias_json': json.dumps(calendario_dias_json),  # Para JavaScript
        'dias_vazios': range(dias_vazios),  # Dias vazios no início
        'escala': escala,
        'meses': meses,
        'anos': range(2024, 2031),
    }
    
    return render(request, 'escala/calendario.html', context)