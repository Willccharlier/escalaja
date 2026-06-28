from datetime import date, timedelta
from calendar import monthrange
from .models import Funcionario, Feriado, Escala, DiaEscala, Turno, ConfiguracaoSistema
from django.db import transaction
import random
from itertools import combinations
from django.utils import timezone
from escala.models import DiaEscala


class GeradorEscala:
    """Serviço responsável por gerar escalas mensais automaticamente"""
    
    def __init__(self, mes, ano):
        self.mes = mes
        self.ano = ano
        self.dias_mes = monthrange(ano, mes)[1]
        self.alertas = []
        self.escala_gerada = {}   # {funcionario_id: {dia: situacao}}
        self.turno_coberto = {}   # {funcionario_id: {dia: turno_id}} — só folguistas
        self.config = ConfiguracaoSistema.get()
        
    def gerar(self):
        """
        Método principal que coordena toda a geração da escala
        Retorna: (sucesso: bool, escala: Escala, alertas: list)
        """
        try:
            with transaction.atomic():
                # 1. Criar objeto Escala
                escala = Escala.objects.create(
                    mes=self.mes,
                    ano=self.ano,
                    gerada_com_sucesso=False
                )
                
                # 2. Buscar turnos
                turnos = Turno.objects.all()
                
                if not turnos.exists():
                    self.alertas.append("❌ ERRO: Nenhum turno cadastrado!")
                    escala.observacoes = "\n".join(self.alertas)
                    escala.save()
                    return False, escala, self.alertas
                
                # 3. Buscar feriados do mês
                feriados = self._buscar_feriados_mes()
                
                # 4. Gerar escala POR TURNO com 2 folgas/semana
                for turno in turnos:
                    sucesso_turno = self._gerar_escala_turno(turno, feriados)
                    if not sucesso_turno:
                        self.alertas.append(f"❌ Impossível gerar escala para turno {turno.nome}")

                # 4b. Gerar folgas dos folguistas e escalá-los nas coberturas
                self._gerar_escala_folguistas()
                self._escalar_folguistas_coberturas()

                # 5. Garantir regra fundamental: máx consecutivos por regime
                self.alertas.append("\n🔧 VERIFICANDO REGRA DE CONSECUTIVOS...")
                corr_consec = self._corrigir_maximos_consecutivos()
                if corr_consec > 0:
                    self.alertas.append(f"   ✅ {corr_consec} correções de consecutivos realizadas!")
                else:
                    self.alertas.append("   ✅ Regra de consecutivos OK!")

                # 5b. Garantir máximo de folgas por mês (remove extras geradas por correções)
                removidos = self._garantir_maximo_folgas_mes()
                if removidos > 0:
                    self.alertas.append(f"   ✅ {removidos} folgas extras removidas (quota mensal)")

                # 5c. Quebrar sequências de 3+ folgas consecutivas (sempre ativo)
                corr3 = self._corrigir_tres_consecutivas()
                if corr3 > 0:
                    self.alertas.append(f"   ✅ {corr3} sequências de 3+ folgas consecutivas corrigidas")

                # 6. Tentar priorizar domingos (apenas 6x1, se config ativa)
                if self.config.domingo_ativo:
                    self.alertas.append("\n🔧 TENTANDO PRIORIZAR DOMINGOS (6x1)...")
                    domingos_dados = self._tentar_priorizar_domingos()
                    if domingos_dados > 0:
                        self.alertas.append(f"   ✅ {domingos_dados} trocas para domingo realizadas!")
                    else:
                        self.alertas.append("   ℹ️ Não foi possível dar mais domingos sem quebrar lotação")
                else:
                    self.alertas.append("\n⏭️ Priorização de domingos desativada")
                
                # 6. Validar mínimos
                problemas = self._validar_minimos_por_dia()
                
                # 7. Tentar corrigir problemas de lotação
                if problemas:
                    self.alertas.append("\n🔧 INICIANDO CORREÇÃO DE LOTAÇÃO...")
                    self.alertas.extend([f"   ⚠️ {p}" for p in problemas])
                    
                    correcoes = self._corrigir_por_redistribuicao()
                    
                    if correcoes > 0:
                        self.alertas.append(f"   ✅ {correcoes} correções realizadas!")
                        problemas = self._validar_minimos_por_dia()
                        
                        if not problemas:
                            self.alertas.append("   ✅ Problemas de lotação resolvidos!")
                        else:
                            self.alertas.append("   ⚠️ Ainda restam problemas:")
                            self.alertas.extend([f"      {p}" for p in problemas])
                    else:
                        self.alertas.append("   ❌ Não foi possível corrigir lotação")
                
                # 8. Corrigir folgas consecutivas (se config ativa)
                if self.config.consecutivas_ativo:
                    self.alertas.append(f"\n🔧 CORRIGINDO FOLGAS CONSECUTIVAS ({self.config.consecutivas_regime})...")
                    correcoes_consecutivas = self._corrigir_folgas_consecutivas()
                    if correcoes_consecutivas > 0:
                        self.alertas.append(f"   ✅ {correcoes_consecutivas} correções realizadas!")
                    else:
                        self.alertas.append("   ℹ️ Sem folgas consecutivas")
                else:
                    self.alertas.append("\n⏭️ Regra de folgas consecutivas desativada")
                
                # 9. Validações finais e alertas
                self._validar_e_alertar_consecutividade()
                self._validar_e_alertar_domingo_folga()
                
                # 10. Salvar no banco
                self._salvar_dias_escala(escala)
                
                # 11. Definir status final
                # Mínimo por turno é regra absoluta. Folguistas cobrindo um turno já foram
                # contados em _validar_minimos_por_dia, então "problemas" só existe se
                # nenhum regular nem folguista cobre o turno no dia — escala genuinamente inválida.
                if problemas:
                    escala.gerada_com_sucesso = False
                    self.alertas.append("\n❌ Escala com déficit de pessoal — turnos abaixo do mínimo:")
                    self.alertas.extend([f"   ⚠️ {p}" for p in problemas])
                    self.alertas.append("   Cadastre mais funcionários ou folguistas habilitados para esses turnos.")
                else:
                    escala.gerada_com_sucesso = True
                    self.alertas.append("\n✅ Escala gerada com sucesso!")
                
                escala.observacoes = "\n".join(self.alertas)
                escala.save()
                
                return not bool(problemas), escala, self.alertas
                
        except Exception as e:
            self.alertas.append(f"❌ ERRO CRÍTICO: {str(e)}")
            return False, None, self.alertas
    
    def _corrigir_maximos_consecutivos(self):
        """
        Garante a regra fundamental CLT:
        - 5x2: máximo 5 dias seguidos trabalhando
        - 6x1: máximo 6 dias seguidos trabalhando
        Varre o mês inteiro (sem respeitar fronteira de semana).
        """
        MAX_ITER = 50
        correcoes = 0

        funcionarios = list(Funcionario.objects.filter(
            id__in=self.escala_gerada.keys(), tipo='REGULAR'
        ))
        max_por_regime = {'5x2': 5, '6x1': 6}

        for func in funcionarios:
            max_consec = max_por_regime.get(func.regime, 6)

            for _ in range(MAX_ITER):
                # Encontra a primeira sequência que viola o limite
                sequencia = []
                violacao = None

                for dia in range(1, self.dias_mes + 1):
                    if self.escala_gerada[func.id].get(dia) == 'TRABALHA':
                        sequencia.append(dia)
                        if len(sequencia) > max_consec:
                            violacao = sequencia[:]
                            break
                    else:
                        sequencia = []

                if not violacao:
                    break  # Sem violação, próximo funcionário

                # Inserir folga no meio da sequência para dividir igualmente
                meio = violacao[len(violacao) // 2]

                # Tenta inserir folga no meio; se quebrar mínimo, testa outros dias da sequência
                inserido = False
                candidatos = sorted(violacao, key=lambda d: abs(d - meio))

                turno_func = func.turno
                minimo_turno = turno_func.minimo_funcionarios if turno_func else 0
                funcionarios_turno = list(Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, turno=turno_func
                )) if turno_func else []

                for dia_folga in candidatos:
                    trabalhando = sum(
                        1 for f in funcionarios_turno
                        if f.id != func.id and
                        self.escala_gerada.get(f.id, {}).get(dia_folga) == 'TRABALHA'
                    )

                    if trabalhando >= minimo_turno:
                        self.escala_gerada[func.id][dia_folga] = 'FOLGA'
                        correcoes += 1
                        inserido = True
                        break

                if not inserido:
                    self.escala_gerada[func.id][meio] = 'FOLGA'
                    correcoes += 1

        return correcoes

    def _corrigir_tres_consecutivas(self):
        """
        Quebra qualquer sequência de 3+ folgas seguidas.
        Sempre ativo — independente de config.
        Move o dia do meio da sequência para outro dia na mesma semana
        onde o turno ainda tem cobertura suficiente.
        """
        semanas = self._dividir_em_semanas_correto()
        correcoes = 0

        funcionarios = {
            f.id: f for f in Funcionario.objects.filter(
                id__in=self.escala_gerada.keys()
            ).select_related('turno')
        }

        def semana_do(dia):
            for s in semanas:
                if dia in s:
                    return s
            return None

        def tem_tres_consecutivas(dias_dict):
            run = 0
            for d in range(1, self.dias_mes + 1):
                if dias_dict.get(d) == 'FOLGA':
                    run += 1
                    if run >= 3:
                        return True
                else:
                    run = 0
            return False

        for func_id, dias in self.escala_gerada.items():
            func = funcionarios.get(func_id)
            if not func:
                continue

            for _ in range(30):
                # Achar início da primeira sequência de 3+
                run_start = None
                run_len = 0
                violacao = None
                for d in range(1, self.dias_mes + 1):
                    if dias.get(d) == 'FOLGA':
                        if run_start is None:
                            run_start = d
                        run_len += 1
                        if run_len >= 3:
                            violacao = (run_start, d)
                            break
                    else:
                        run_start = None
                        run_len = 0

                if not violacao:
                    break

                # Mover o dia do meio da sequência para outro dia na sua semana
                meio = violacao[0] + (violacao[1] - violacao[0]) // 2
                sem = semana_do(meio)
                if not sem:
                    break

                turno = func.turno
                minimo = turno.minimo_funcionarios if turno else 0
                colegas = list(Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, turno=turno
                ).exclude(id=func_id)) if turno else []

                movido = False
                for dia_novo in sem:
                    if dias.get(dia_novo) != 'TRABALHA':
                        continue
                    if dia_novo == meio:
                        continue

                    # Verificar cobertura no dia_novo (quem vai cobrir o mínimo se ele folgar?)
                    outros = sum(
                        1 for f in colegas
                        if self.escala_gerada.get(f.id, {}).get(dia_novo) == 'TRABALHA'
                    )
                    if outros < minimo:
                        continue

                    dias[meio] = 'TRABALHA'
                    dias[dia_novo] = 'FOLGA'

                    if not tem_tres_consecutivas(dias):
                        correcoes += 1
                        movido = True
                        break
                    else:
                        dias[meio] = 'FOLGA'
                        dias[dia_novo] = 'TRABALHA'

                if not movido:
                    # Força mesmo sem garantia de mínimo para não deixar 3+ consecutivas
                    for dia_novo in sem:
                        if dias.get(dia_novo) != 'TRABALHA' or dia_novo == meio:
                            continue
                        dias[meio] = 'TRABALHA'
                        dias[dia_novo] = 'FOLGA'
                        if not tem_tres_consecutivas(dias):
                            correcoes += 1
                            break
                        dias[meio] = 'FOLGA'
                        dias[dia_novo] = 'TRABALHA'
                    else:
                        break

        return correcoes

    def _garantir_maximo_folgas_mes(self):
        """
        Remove folgas excedentes à quota mensal de cada funcionário REGULAR.
        A quota é: soma de _folgas_semana para cada semana do mês.
        Prioriza remover dias onde o turno já tem cobertura suficiente.
        """
        semanas = self._dividir_em_semanas_correto()
        funcionarios = list(Funcionario.objects.filter(
            id__in=self.escala_gerada.keys(), tipo='REGULAR'
        ).select_related('turno'))
        removidos = 0

        for func in funcionarios:
            quota = sum(self._folgas_semana(func, len(s)) for s in semanas)
            dias_folga = sorted(
                [d for d, s in self.escala_gerada[func.id].items() if s == 'FOLGA']
            )
            excesso = len(dias_folga) - quota
            if excesso <= 0:
                continue

            turno = func.turno
            minimo = turno.minimo_funcionarios if turno else 0
            colegas = [
                f for f in Funcionario.objects.filter(tipo='REGULAR', ativo=True, turno=turno)
                if f.id != func.id
            ] if turno else []

            def cobertura(dia):
                return sum(
                    1 for f in colegas
                    if self.escala_gerada.get(f.id, {}).get(dia) == 'TRABALHA'
                )

            # Remove folgas onde os colegas já cobrem o mínimo (dias mais seguros para remover)
            candidatos = sorted(dias_folga, key=lambda d: -cobertura(d))
            for dia in candidatos:
                if excesso <= 0:
                    break
                if cobertura(dia) >= minimo:
                    self.escala_gerada[func.id][dia] = 'TRABALHA'
                    excesso -= 1
                    removidos += 1

        return removidos

    def _buscar_feriados_mes(self):
        """Busca feriados do mês que caem em dias úteis"""
        data_inicio = date(self.ano, self.mes, 1)
        data_fim = date(self.ano, self.mes, self.dias_mes)
        
        feriados = Feriado.objects.filter(
            data__gte=data_inicio,
            data__lte=data_fim
        )
        
        return [f for f in feriados if f.eh_dia_util()]
    
    def _dividir_em_semanas_correto(self):
        """Divide o mês em semanas (Domingo a Sábado)"""
        semanas = []
        semana_atual = []
        
        for dia in range(1, self.dias_mes + 1):
            data = date(self.ano, self.mes, dia)
            dia_semana = data.weekday()  # 0=seg, 6=dom
            
            if dia_semana == 6 and semana_atual:
                semanas.append(semana_atual)
                semana_atual = []
            
            semana_atual.append(dia)
            
            if dia_semana == 5 or dia == self.dias_mes:
                if semana_atual:
                    semanas.append(semana_atual)
                    semana_atual = []
        
        if semana_atual:
            semanas.append(semana_atual)
        
        return semanas
    
    def _encontrar_semana_do_dia(self, dia_procurado):
        """Encontra qual semana um dia pertence"""
        semanas = self._dividir_em_semanas_correto()
        for semana in semanas:
            if dia_procurado in semana:
                return semana
        return None
    
    def _gerar_escala_turno(self, turno, feriados):
        """Gera escala para um turno, respeitando o regime individual de cada funcionário"""
        funcionarios = list(Funcionario.objects.filter(
            tipo='REGULAR',
            ativo=True,
            turno=turno
        ))

        if not funcionarios:
            self.alertas.append(f"⚠️ Turno {turno.nome}: Nenhum funcionário!")
            return False

        minimo = turno.minimo_funcionarios

        # Inicializar: todos trabalham
        for func in funcionarios:
            self.escala_gerada[func.id] = {dia: 'TRABALHA' for dia in range(1, self.dias_mes + 1)}

        semanas = self._dividir_em_semanas_correto()

        # Processar todos juntos — quota individual por regime
        for idx_semana, semana in enumerate(semanas):
            semana_anterior = semanas[idx_semana - 1] if idx_semana > 0 else None
            sucesso = self._processar_semana(funcionarios, semana, minimo, idx_semana + 1, semana_anterior)
            if not sucesso:
                self.alertas.append(f"⚠️ Semana {idx_semana + 1}: Impossível distribuir folgas!")

        return True

    def _dias_criticos_folguista(self, func):
        """Retorna conjunto de dias onde o folguista não pode folgar.
        Um dia é crítico se algum turno habilitado ficaria abaixo do mínimo sem ele."""
        from itertools import chain
        turnos_hab = list(func.turnos_habilitados.all())
        if not turnos_hab:
            return set()

        criticos = set()
        for dia in range(1, self.dias_mes + 1):
            for turno in turnos_hab:
                regulares = Funcionario.objects.filter(tipo='REGULAR', ativo=True, turno=turno)
                trabalhando = sum(
                    1 for f in regulares
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                if trabalhando < turno.minimo_funcionarios:
                    criticos.add(dia)
                    break
        return criticos

    def _gerar_escala_folguistas(self):
        """Gera folgas para funcionários FOLGUISTA com base no regime deles.
        Nunca coloca folga em dia crítico (dia onde algum turno habilitado ficaria sem mínimo)."""
        folguistas = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('turnos_habilitados')
        )
        if not folguistas:
            return

        semanas = self._dividir_em_semanas_correto()
        max_consec = {'5x2': 5, '6x1': 6}

        for func in folguistas:
            self.escala_gerada[func.id] = {dia: 'TRABALHA' for dia in range(1, self.dias_mes + 1)}
            limite = max_consec.get(func.regime, 6)

            # Dias onde este folguista é indispensável — não pode folgar
            dias_criticos = self._dias_criticos_folguista(func)

            for idx, semana in enumerate(semanas):
                dias_count = len(semana)
                folgas_necessarias = self._folgas_semana(func, dias_count)

                if folgas_necessarias == 0:
                    continue

                semana_anterior = semanas[idx - 1] if idx > 0 else None

                # Streak de trabalho vindo da semana anterior
                streak_anterior = 0
                if semana_anterior:
                    for d in reversed(semana_anterior):
                        if self.escala_gerada[func.id].get(d) == 'TRABALHA':
                            streak_anterior += 1
                        else:
                            break

                # Dias disponíveis para folga nesta semana (excluindo críticos)
                dias_livres = [d for d in semana if d not in dias_criticos]

                def combinacao_valida(combinacao):
                    """Verifica consecutividade e que não cai em dia crítico."""
                    if any(d in dias_criticos for d in combinacao):
                        return False
                    dias_folga_set = set(combinacao)
                    streak = streak_anterior
                    for d in semana:
                        if d in dias_folga_set:
                            streak = 0
                        else:
                            streak += 1
                            if streak > limite:
                                return False
                    return True

                fixas_raw = self._combinacoes_dia_fixo(func, semana, folgas_necessarias) or []
                combinacoes_fixas = [c for c in fixas_raw if combinacao_valida(c)]

                atribuido = False
                MAX_TENT = 30

                if combinacoes_fixas:
                    for _ in range(MAX_TENT):
                        combinacao = random.choice(combinacoes_fixas)
                        if combinacao_valida(combinacao):
                            for dia in combinacao:
                                self.escala_gerada[func.id][dia] = 'FOLGA'
                            atribuido = True
                            break
                else:
                    # Gera combinações apenas dos dias livres
                    if len(dias_livres) >= folgas_necessarias:
                        combinacoes = self._gerar_combinacoes_validas(dias_livres, folgas_necessarias, False)
                        combinacoes = [c for c in combinacoes if combinacao_valida(c)]
                    else:
                        combinacoes = []

                    for _ in range(MAX_TENT):
                        if not combinacoes:
                            break
                        combinacao = random.choice(combinacoes)
                        if combinacao_valida(combinacao):
                            for dia in combinacao:
                                self.escala_gerada[func.id][dia] = 'FOLGA'
                            atribuido = True
                            break

                if not atribuido:
                    # Fallback: usa dias livres primeiro; se insuficiente, usa críticos (menos mal)
                    candidatos = dias_livres if len(dias_livres) >= folgas_necessarias else list(semana)
                    for dia in candidatos[:folgas_necessarias]:
                        self.escala_gerada[func.id][dia] = 'FOLGA'

    def _escalar_folguistas_coberturas(self):
        """
        Atribui um turno a cada dia de trabalho do folguista.
        Prioriza turnos com déficit; se não houver déficit, atribui ao turno
        com menos funcionários trabalhando naquele dia (dos habilitados).
        """
        folguistas = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('turnos_habilitados')
        )
        if not folguistas:
            return

        turnos_habilitados_cache = {
            f.id: set(f.turnos_habilitados.values_list('id', flat=True))
            for f in folguistas
        }

        turnos = list(Turno.objects.all().order_by('horario_entrada'))

        for dia in range(1, self.dias_mes + 1):
            # Conta trabalhando por turno neste dia (apenas REGULAR)
            contagem_turno = {}
            for turno in turnos:
                regulares = list(Funcionario.objects.filter(tipo='REGULAR', ativo=True, turno=turno))
                contagem_turno[turno.id] = sum(
                    1 for f in regulares
                    if f.id in self.escala_gerada and self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )

            for func in folguistas:
                if self.escala_gerada.get(func.id, {}).get(dia) != 'TRABALHA':
                    continue

                if dia in self.turno_coberto.get(func.id, {}):
                    continue

                habilitados = [t for t in turnos if t.id in turnos_habilitados_cache.get(func.id, set())]
                if not habilitados:
                    continue

                # Primeiro: turno com déficit
                turno_escolhido = None
                for turno in habilitados:
                    deficit = turno.minimo_funcionarios - contagem_turno.get(turno.id, 0)
                    if deficit > 0:
                        turno_escolhido = turno
                        break

                # Sem déficit: turno com menor cobertura relativa ao seu mínimo
                # Ex: NOITE 1/1 (100%) vs MANHA 2/3 (67%) → vai para MANHA
                if turno_escolhido is None:
                    def _cobertura_rel(t):
                        minimo = t.minimo_funcionarios
                        atual = contagem_turno.get(t.id, 0)
                        return atual / minimo if minimo > 0 else float('inf')
                    turno_escolhido = min(habilitados, key=_cobertura_rel)

                if func.id not in self.turno_coberto:
                    self.turno_coberto[func.id] = {}
                self.turno_coberto[func.id][dia] = turno_escolhido.id
                contagem_turno[turno_escolhido.id] = contagem_turno.get(turno_escolhido.id, 0) + 1

    def _folgas_semana(self, func, dias_count):
        """Retorna quantas folgas o funcionário precisa na semana, dado seu regime"""
        if func.regime == '6x1':
            return 1 if dias_count >= 4 else 0
        else:  # 5x2
            if dias_count >= 5:
                return 2
            elif dias_count >= 3:
                return 1
            else:
                return 0

    def _combinacoes_dia_fixo(self, func, dias_semana, folgas_necessarias):
        """
        Para 5x2 com folga_fixa_dia definido, retorna as combinações preferidas
        (par consecutivo a partir do dia fixo) se disponíveis nesta semana.
        Retorna None se não aplicável.
        """
        if func.folga_fixa_dia is None:
            return None

        dia_fixo = func.folga_fixa_dia
        wd_to_day = {date(self.ano, self.mes, d).weekday(): d for d in dias_semana}
        d1 = wd_to_day.get(dia_fixo)

        if func.regime == '6x1':
            # 6x1: dia único fixo
            if folgas_necessarias == 1 and d1:
                return [[d1]]
            return None

        # 5x2: par consecutivo (dia fixo + seguinte)
        dia_seg = (dia_fixo + 1) % 7
        d2 = wd_to_day.get(dia_seg)

        if folgas_necessarias == 2 and d1 and d2:
            return [[d1, d2]]
        elif folgas_necessarias == 1 and d1:
            return [[d1]]
        elif folgas_necessarias == 1 and d2:
            return [[d2]]
        return None

    def _funcionario_ja_tem_domingo(self, func_id, antes_do_dia):
        """Verifica se o funcionário já tem algum domingo de folga antes de um dia específico"""
        for d in range(1, antes_do_dia):
            if date(self.ano, self.mes, d).weekday() == 6:
                if self.escala_gerada[func_id].get(d) != 'TRABALHA':
                    return True
        return False

    def _ordenar_com_prioridade_domingo(self, combinacoes, domingo, func_id, antes_do_dia):
        """Coloca combinações com domingo na frente se o funcionário ainda não tem domingo"""
        if not domingo:
            return combinacoes
        if self._funcionario_ja_tem_domingo(func_id, antes_do_dia):
            return combinacoes
        com_dom = [c for c in combinacoes if domingo in c]
        sem_dom = [c for c in combinacoes if domingo not in c]
        random.shuffle(com_dom)
        random.shuffle(sem_dom)
        return com_dom + sem_dom

    def _processar_semana(self, funcionarios, dias_semana, minimo, num_semana, semana_anterior=None):
        """Processa uma semana atribuindo folgas individuais respeitando o mínimo global do turno"""
        dias_count = len(dias_semana)

        # Domingo desta semana (se existir)
        domingo_semana = next(
            (d for d in dias_semana if date(self.ano, self.mes, d).weekday() == 6),
            None
        )

        MAX_TENTATIVAS = 100

        for tentativa in range(MAX_TENTATIVAS):
            estado_backup = {func.id: self.escala_gerada[func.id].copy() for func in funcionarios}

            sucesso_total = True
            funcionarios_embaralhados = funcionarios.copy()

            # Quem não tem domingo ainda vai na frente da fila nesta semana com domingo
            if domingo_semana:
                sem_dom = [f for f in funcionarios_embaralhados
                           if not self._funcionario_ja_tem_domingo(f.id, domingo_semana)]
                com_dom = [f for f in funcionarios_embaralhados
                           if self._funcionario_ja_tem_domingo(f.id, domingo_semana)]
                random.shuffle(sem_dom)
                random.shuffle(com_dom)
                funcionarios_embaralhados = sem_dom + com_dom
            else:
                random.shuffle(funcionarios_embaralhados)

            for func in funcionarios_embaralhados:
                func_id = func.id
                folgas_necessarias = self._folgas_semana(func, dias_count)

                if folgas_necessarias == 0:
                    continue

                exigir_nc = self._regime_aplica_consecutivas(func.regime)

                # 1ª prioridade: dia fixo configurado (folga_fixa_dia)
                combinacoes_fixas = self._combinacoes_dia_fixo(func, dias_semana, folgas_necessarias)

                # Se a semana tem domingo e o funcionário ainda não tem nenhum,
                # ignora o dia fixo nesta semana para garantir o domingo obrigatório
                if (combinacoes_fixas and domingo_semana
                        and not self._funcionario_ja_tem_domingo(func_id, domingo_semana)
                        and not any(domingo_semana in c for c in combinacoes_fixas)):
                    combinacoes_fixas = None

                if combinacoes_fixas:
                    combinacoes = combinacoes_fixas
                else:
                    combinacoes = self._gerar_combinacoes_validas(dias_semana, folgas_necessarias, exigir_nc)

                if not combinacoes:
                    sucesso_total = False
                    break

                # Filtrar consecutividade entre semanas
                if semana_anterior and exigir_nc:
                    ultimo_dia_anterior = semana_anterior[-1]
                    filtradas = [
                        c for c in combinacoes
                        if not (min(c) == dias_semana[0] and
                                self.escala_gerada[func_id].get(ultimo_dia_anterior) != 'TRABALHA')
                    ]
                    if filtradas:
                        combinacoes = filtradas

                if not combinacoes:
                    sucesso_total = False
                    break

                # Ordenar: domingo na frente se funcionário ainda não tem
                if not combinacoes_fixas:
                    combinacoes = self._ordenar_com_prioridade_domingo(
                        combinacoes, domingo_semana, func_id, domingo_semana or dias_semana[0]
                    )

                folga_atribuida = False
                for combinacao in combinacoes:
                    if self._combinacao_mantem_minimo(func_id, combinacao, funcionarios, minimo):
                        for dia in combinacao:
                            self.escala_gerada[func_id][dia] = 'FOLGA'
                        folga_atribuida = True
                        break

                if not folga_atribuida:
                    sucesso_total = False
                    break

            if sucesso_total:
                return True

            for func in funcionarios:
                self.escala_gerada[func.id] = estado_backup[func.id].copy()

        # Fallback: dá folgas mesmo sem manter mínimo (ex: único funcionário no turno)
        # O déficit será reportado pela validação de lotação — o funcionário NÃO pode ficar sem folga
        for func in funcionarios:
            folgas_necessarias = self._folgas_semana(func, dias_count)
            if folgas_necessarias == 0:
                continue
            ja_tem = sum(1 for d in dias_semana if self.escala_gerada[func.id].get(d) != 'TRABALHA')
            if ja_tem >= folgas_necessarias:
                continue

            combinacoes_fixas = self._combinacoes_dia_fixo(func, dias_semana, folgas_necessarias)
            if combinacoes_fixas:
                combinacao = random.choice(combinacoes_fixas)
            else:
                exigir_nc = self._regime_aplica_consecutivas(func.regime)
                combinacoes = self._gerar_combinacoes_validas(dias_semana, folgas_necessarias, exigir_nc)
                if not combinacoes:
                    combinacoes = self._gerar_combinacoes_validas(dias_semana, folgas_necessarias, False)
                if not combinacoes:
                    continue
                if domingo_semana:
                    combinacoes = self._ordenar_com_prioridade_domingo(
                        combinacoes, domingo_semana, func.id, domingo_semana
                    )
                combinacao = combinacoes[0]

            for dia in combinacao:
                self.escala_gerada[func.id][dia] = 'FOLGA'

        return True  # folgas atribuídas; déficit de lotação será reportado na validação
    
    def _gerar_combinacoes_validas(self, dias, quantidade, exigir_nao_consecutivo=True):
        """Gera combinações de dias, opcionalmente exigindo que não sejam consecutivos"""
        if quantidade == 1:
            return [[dia] for dia in dias]

        if quantidade == 2:
            combinacoes = []
            for i, dia1 in enumerate(dias):
                for dia2 in dias[i+1:]:
                    if not exigir_nao_consecutivo or abs(dia2 - dia1) > 1:
                        combinacoes.append([dia1, dia2])
            return combinacoes

        return []
    
    def _combinacao_mantem_minimo(self, func_id, dias_folga, funcionarios, minimo):
        """Verifica se folgas mantém mínimo em todos os dias"""
        for dia in dias_folga:
            trabalhando = 0
            for f in funcionarios:
                if f.id == func_id:
                    continue
                
                if f.id in self.escala_gerada:
                    if self.escala_gerada[f.id].get(dia) == 'TRABALHA':
                        trabalhando += 1
                else:
                    trabalhando += 1
            
            if trabalhando < minimo:
                return False
        
        return True
    
    def _tentar_priorizar_domingos(self):
        """Tenta dar domingos de folga para funcionários 6x1 trocando dentro da semana"""
        domingos = [
            dia for dia in range(1, self.dias_mes + 1)
            if date(self.ano, self.mes, dia).weekday() == 6
        ]
        if not domingos:
            return 0

        trocas_realizadas = 0

        funcs = list(Funcionario.objects.filter(
            id__in=self.escala_gerada.keys()
        ).select_related('turno'))

        # Pré-computar colegas de turno por funcionário
        colegas_turno = {}
        for func in funcs:
            if func.turno:
                colegas_turno[func.id] = [
                    f for f in funcs
                    if f.id != func.id and f.turno_id == func.turno_id
                ]
            else:
                colegas_turno[func.id] = []

        for func in funcs:
            if func.regime != '6x1':
                continue

            tem_domingo = any(
                self.escala_gerada[func.id].get(dom) != 'TRABALHA'
                for dom in domingos
            )
            if tem_domingo:
                continue

            minimo = func.turno.minimo_funcionarios if func.turno else 0

            # Pré-carregar folguistas com turnos habilitados
            folguistas_ativos = list(
                Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
                .prefetch_related('turnos_habilitados')
            )

            for domingo in domingos:
                if self.escala_gerada[func.id].get(domingo) != 'TRABALHA':
                    continue

                semana_domingo = self._encontrar_semana_do_dia(domingo)
                if not semana_domingo:
                    continue

                # Cobertura regular no domingo
                colegas = colegas_turno[func.id]
                regulares_no_domingo = sum(
                    1 for f in colegas
                    if self.escala_gerada.get(f.id, {}).get(domingo) == 'TRABALHA'
                )

                # Folguistas disponíveis (trabalhando no domingo, habilitados para este turno)
                folguistas_cobrindo = [
                    f for f in folguistas_ativos
                    if (self.escala_gerada.get(f.id, {}).get(domingo) == 'TRABALHA'
                        and func.turno
                        and func.turno.id in f.turnos_habilitados.values_list('id', flat=True))
                ]

                cobertura_total = regulares_no_domingo + len(folguistas_cobrindo)
                if cobertura_total < minimo:
                    continue

                trocou = False
                for dia in semana_domingo:
                    if dia == domingo:
                        continue
                    if self.escala_gerada[func.id].get(dia) != 'FOLGA':
                        continue

                    self.escala_gerada[func.id][domingo] = 'FOLGA'
                    self.escala_gerada[func.id][dia] = 'TRABALHA'

                    # Atualizar turno_coberto do folguista ANTES de validar,
                    # pois a validação conta folguistas via turno_coberto
                    folg_backup = None
                    if folguistas_cobrindo and func.turno:
                        folg = folguistas_cobrindo[0]
                        old_turno = self.turno_coberto.get(folg.id, {}).get(domingo)
                        folg_backup = (folg.id, domingo, old_turno)
                        if folg.id not in self.turno_coberto:
                            self.turno_coberto[folg.id] = {}
                        self.turno_coberto[folg.id][domingo] = func.turno.id

                    if (self._validar_consecutividade_funcionario(func.id) and
                            self._validar_lotacao_dias_especificos([domingo, dia])):
                        trocas_realizadas += 1
                        trocou = True
                        break
                    else:
                        # Reverter tudo
                        self.escala_gerada[func.id][domingo] = 'TRABALHA'
                        self.escala_gerada[func.id][dia] = 'FOLGA'
                        if folg_backup:
                            fid, d, old_t = folg_backup
                            if old_t is None:
                                self.turno_coberto.get(fid, {}).pop(d, None)
                            else:
                                self.turno_coberto[fid][d] = old_t

                if trocou:
                    break

        return trocas_realizadas
    
    def _validar_minimos_por_dia(self):
        """Valida se todos os dias têm lotação mínima.
        Conta regulares + folguistas cobrindo o turno via turno_coberto."""
        problemas = []
        turnos = Turno.objects.all()

        for dia in range(1, self.dias_mes + 1):
            for turno in turnos:
                funcionarios_turno = Funcionario.objects.filter(
                    tipo='REGULAR',
                    ativo=True,
                    turno=turno
                )

                regulares = sum(
                    1 for func in funcionarios_turno
                    if func.id in self.escala_gerada and
                    self.escala_gerada[func.id].get(dia) == 'TRABALHA'
                )

                # Folguistas cobrindo este turno neste dia contam para o mínimo
                folguistas = sum(
                    1 for fid, dias_turno in self.turno_coberto.items()
                    if dias_turno.get(dia) == turno.id
                )

                trabalhando = regulares + folguistas

                if trabalhando < turno.minimo_funcionarios:
                    problemas.append(
                        f"DIA {dia:02d}/{self.mes:02d} - "
                        f"Turno {turno.nome}: {trabalhando}/{turno.minimo_funcionarios}"
                    )

        return problemas
    
    def _corrigir_por_redistribuicao(self):
        """Corrige lotação movendo folgas dentro da mesma semana"""
        correcoes_feitas = 0
        turnos = Turno.objects.all()
        semanas = self._dividir_em_semanas_correto()
        
        for turno in turnos:
            funcionarios_turno = list(Funcionario.objects.filter(
                tipo='REGULAR',
                ativo=True,
                turno=turno
            ))
            
            if not funcionarios_turno:
                continue
            
            for dia in range(1, self.dias_mes + 1):
                regulares = sum(
                    1 for f in funcionarios_turno
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                folguistas = sum(
                    1 for fid, dias_turno in self.turno_coberto.items()
                    if dias_turno.get(dia) == turno.id
                )
                trabalhando = regulares + folguistas

                falta = turno.minimo_funcionarios - trabalhando

                if falta <= 0:
                    continue
                
                candidatos = [
                    f for f in funcionarios_turno
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'FOLGA'
                ]
                
                for candidato in candidatos[:falta]:
                    if self._tentar_trocar_folga_mesma_semana(candidato.id, dia, funcionarios_turno, turno.minimo_funcionarios, semanas):
                        correcoes_feitas += 1
                        falta -= 1
                        if falta == 0:
                            break
        
        return correcoes_feitas
    
    def _tentar_trocar_folga_mesma_semana(self, func_id, dia_problema, funcionarios_turno, minimo, semanas):
        """Tenta trocar folga dentro da mesma semana"""
        semana_problema = None
        for semana in semanas:
            if dia_problema in semana:
                semana_problema = semana
                break
        
        if not semana_problema:
            return False
        
        for dia_candidato in semana_problema:
            if dia_candidato == dia_problema:
                continue
            
            if self.escala_gerada[func_id].get(dia_candidato) != 'TRABALHA':
                continue
            
            trabalhando = sum(
                1 for f in funcionarios_turno
                if f.id in self.escala_gerada and
                self.escala_gerada[f.id].get(dia_candidato) == 'TRABALHA'
            )
            
            if trabalhando <= minimo:
                continue
            
            self.escala_gerada[func_id][dia_problema] = 'TRABALHA'
            self.escala_gerada[func_id][dia_candidato] = 'FOLGA'
            
            if self._validar_consecutividade_funcionario(func_id):
                return True
            else:
                self.escala_gerada[func_id][dia_problema] = 'FOLGA'
                self.escala_gerada[func_id][dia_candidato] = 'TRABALHA'
        
        return False
    
    def _regime_aplica_consecutivas(self, regime):
        """Verifica se a regra de consecutivas se aplica a este regime"""
        if not self.config.consecutivas_ativo:
            return False
        cfg = self.config.consecutivas_regime
        return cfg == 'AMBOS' or cfg == regime

    def _corrigir_folgas_consecutivas(self):
        """Corrige folgas consecutivas respeitando o regime configurado.
        Tenta mover o primeiro dia do par para outra data na mesma semana;
        se não conseguir, tenta mover o segundo dia na sua semana.
        """
        correcoes_feitas = 0
        semanas = self._dividir_em_semanas_correto()
        MAX_TENTATIVAS = 20

        regime_por_func = {
            f.id: f.regime
            for f in Funcionario.objects.filter(id__in=self.escala_gerada.keys())
        }

        def semana_do_dia(dia):
            for s in semanas:
                if dia in s:
                    return s
            return None

        def tentar_mover(func_id, dia_folga, dia_trabalha, dias_excluidos):
            """Move folga de dia_folga para outro dia na mesma semana; retorna True se conseguiu."""
            sem = semana_do_dia(dia_folga)
            if not sem:
                return False
            for dia_novo in sem:
                if dia_novo == dia_folga or dia_novo in dias_excluidos:
                    continue
                if self.escala_gerada[func_id].get(dia_novo) != 'TRABALHA':
                    continue
                self.escala_gerada[func_id][dia_folga] = 'TRABALHA'
                self.escala_gerada[func_id][dia_novo] = 'FOLGA'
                if (self._validar_consecutividade_funcionario(func_id) and
                        self._validar_lotacao_dias_especificos([dia_folga, dia_novo])):
                    return True
                self.escala_gerada[func_id][dia_folga] = 'FOLGA'
                self.escala_gerada[func_id][dia_novo] = 'TRABALHA'
            return False

        for func_id in self.escala_gerada.keys():
            if not self._regime_aplica_consecutivas(regime_por_func.get(func_id, '5x2')):
                continue

            for _ in range(MAX_TENTATIVAS):
                par = None
                for dia in range(1, self.dias_mes):
                    if (self.escala_gerada[func_id].get(dia) == 'FOLGA' and
                            self.escala_gerada[func_id].get(dia + 1) == 'FOLGA'):
                        par = (dia, dia + 1)
                        break

                if not par:
                    break

                d1, d2 = par
                # Tenta mover o primeiro dia; se não, tenta o segundo
                if tentar_mover(func_id, d1, d2, {d2}):
                    correcoes_feitas += 1
                elif tentar_mover(func_id, d2, d1, {d1}):
                    correcoes_feitas += 1
                else:
                    break  # Não conseguiu resolver este par

        return correcoes_feitas
    
    def _validar_consecutividade_funcionario(self, func_id):
        """Valida se não tem folgas consecutivas, respeitando config de regime"""
        try:
            func = Funcionario.objects.get(id=func_id)
            if not self._regime_aplica_consecutivas(func.regime):
                return True
        except Funcionario.DoesNotExist:
            pass

        for dia in range(1, self.dias_mes):
            if (self.escala_gerada[func_id].get(dia) == 'FOLGA' and
                    self.escala_gerada[func_id].get(dia + 1) == 'FOLGA'):
                return False
        return True
    
    def _validar_lotacao_dias_especificos(self, dias):
        """Valida lotação de dias específicos, contando regulares + folguistas."""
        turnos = Turno.objects.all()

        for dia in dias:
            for turno in turnos:
                funcionarios_turno = Funcionario.objects.filter(
                    tipo='REGULAR',
                    ativo=True,
                    turno=turno
                )

                regulares = sum(
                    1 for f in funcionarios_turno
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                folguistas = sum(
                    1 for fid, dias_turno in self.turno_coberto.items()
                    if dias_turno.get(dia) == turno.id
                )

                if regulares + folguistas < turno.minimo_funcionarios:
                    return False

        return True
    
    def _validar_e_alertar_consecutividade(self):
        """Alerta sobre folgas consecutivas restantes, respeitando config de regime"""
        if not self.config.consecutivas_ativo:
            return

        problemas = []

        for func_id in self.escala_gerada.keys():
            funcionario = Funcionario.objects.get(id=func_id)

            if not self._regime_aplica_consecutivas(funcionario.regime):
                continue

            for dia in range(1, self.dias_mes):
                hoje = self.escala_gerada[func_id][dia]
                amanha = self.escala_gerada[func_id][dia + 1]

                if hoje == 'FOLGA' and amanha == 'FOLGA':
                    problemas.append(f"⚠️ {funcionario.nome}: dias {dia} e {dia+1}")
                    break

        if problemas:
            self.alertas.append("\n⚠️ Folgas consecutivas restantes:")
            self.alertas.extend([f"   {p}" for p in problemas])
    
    def _validar_e_alertar_domingo_folga(self):
        """Alerta sobre funcionários sem domingo"""
        domingos = [
            dia for dia in range(1, self.dias_mes + 1)
            if date(self.ano, self.mes, dia).weekday() == 6
        ]
        
        if not domingos:
            return
        
        problemas = []
        
        for func_id in self.escala_gerada.keys():
            funcionario = Funcionario.objects.get(id=func_id)
            
            tem_domingo = any(
                self.escala_gerada[func_id][dom] != 'TRABALHA'
                for dom in domingos
            )
            
            if not tem_domingo:
                problemas.append(f"⚠️ {funcionario.nome}")
        
        if problemas:
            self.alertas.append("\n⚠️ Sem domingo de folga:")
            self.alertas.extend([f"   {p}" for p in problemas])
    
    def _salvar_dias_escala(self, escala):
        """Salva escala no banco"""
        dias_para_criar = []
        turno_cache = {t.id: t for t in Turno.objects.all()}

        for func_id, dias_func in self.escala_gerada.items():
            funcionario = Funcionario.objects.get(id=func_id)

            for dia, situacao in dias_func.items():
                data = date(self.ano, self.mes, dia)
                turno_cob_id = self.turno_coberto.get(func_id, {}).get(dia)
                turno_cob = turno_cache.get(turno_cob_id) if turno_cob_id else None

                dias_para_criar.append(
                    DiaEscala(
                        escala=escala,
                        funcionario=funcionario,
                        data=data,
                        situacao=situacao,
                        turno_coberto=turno_cob
                    )
                )

        DiaEscala.objects.bulk_create(dias_para_criar)

def funcionarios_em_plantao():
    agora = timezone.localtime()
    hoje = agora.date()
    hora = agora.time()

    plantao = DiaEscala.objects.select_related(
        'funcionario', 'funcionario__turno'
    ).filter(
        data=hoje,
        situacao='TRABALHA',
        funcionario__ativo=True
    )

    funcionarios = []
    for dia in plantao:
        turno = dia.funcionario.turno

        # turno normal
        if turno.horario_entrada < turno.horario_saida:
            if turno.horario_entrada <= hora < turno.horario_saida:
                funcionarios.append(dia.funcionario)

        # turno noturno (vira o dia)
        else:
            if hora >= turno.horario_entrada or hora < turno.horario_saida:
                funcionarios.append(dia.funcionario)

    return funcionarios