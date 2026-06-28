from datetime import date, timedelta
from calendar import monthrange
from .models import Funcionario, Feriado, Escala, DiaEscala, Turno, Grupo, SetorTurno, ConfiguracaoSistema
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
        self.setor_coberto = {}   # {funcionario_id: {dia: grupo_id}} — só folguistas
        self.domingo_garantido = {}  # {funcionario_id: dia} — domingo R1, nunca remover
        self.config = ConfiguracaoSistema.get()
        
    def gerar(self):
        """
        Método principal que coordena toda a geração da escala
        Retorna: (sucesso: bool, escala: Escala, alertas: list)
        """
        try:
            with transaction.atomic():
                # 1. Criar objeto Escala (remove existente se houver)
                Escala.objects.filter(mes=self.mes, ano=self.ano).delete()
                escala = Escala.objects.create(
                    mes=self.mes,
                    ano=self.ano,
                    gerada_com_sucesso=False
                )
                
                # 2. Buscar setores com funcionários ativos
                setores = Grupo.objects.filter(
                    funcionario__tipo='REGULAR', funcionario__ativo=True
                ).distinct()

                if not setores.exists():
                    self.alertas.append("❌ ERRO: Nenhum setor com funcionários cadastrado!")
                    escala.observacoes = "\n".join(self.alertas)
                    escala.save()
                    return False, escala, self.alertas

                # 3. Buscar feriados do mês
                feriados = self._buscar_feriados_mes()

                # 4. R1+R2: Garantir 1 domingo por funcionário ANTES de qualquer outra folga
                todos_regulares = list(Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True
                ).select_related('grupo', 'turno'))
                for func in todos_regulares:
                    self.escala_gerada[func.id] = {dia: 'TRABALHA' for dia in range(1, self.dias_mes + 1)}
                self._garantir_domingos(todos_regulares)
                self.alertas.append("✅ Domingos garantidos (R1+R2)")

                # 5. Gerar escala POR SETOR com folgas/semana por regime
                for setor in setores:
                    sucesso_setor = self._gerar_escala_setor(setor, feriados)
                    if not sucesso_setor:
                        self.alertas.append(f"❌ Impossível gerar escala para setor {setor.nome}")

                # 5b. Gerar folgas dos folguistas e escalá-los nas coberturas de setor
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

                # (domingos já garantidos no passo 4 — R1+R2)
                
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
                
                # 7b. Cobrir déficits restantes com folguistas habilitados
                problemas = self._validar_minimos_por_dia()
                if problemas:
                    self.alertas.append("\n🔧 ALOCANDO FOLGUISTAS NOS DÉFICITS RESTANTES...")
                    corr_folg = self._cobrir_deficits_com_folguistas()
                    if corr_folg > 0:
                        self.alertas.append(f"   ✅ {corr_folg} déficit(s) coberto(s) por folguistas!")
                        problemas = self._validar_minimos_por_dia()
                    else:
                        self.alertas.append("   ⚠️ Sem folguistas habilitados disponíveis para os déficits")

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
                
                # 9. Re-verificar consecutivos de trabalho após todas as redistribuições
                self.alertas.append("\n🔧 RE-VERIFICANDO CONSECUTIVOS DE TRABALHO (pós-redistribuição)...")
                corr_final = self._corrigir_maximos_consecutivos()
                if corr_final > 0:
                    self.alertas.append(f"   ✅ {corr_final} correções adicionais de consecutivos!")
                else:
                    self.alertas.append("   ✅ Consecutivos OK!")

                # 9b. Reparo determinístico R1: corrigir quem ficou sem domingo após todos os ajustes
                self.alertas.append("\n🔧 REPARANDO R1 (domingo garantido pós-geração)...")
                corr_r1 = self._corrigir_r1_pos_geracao()
                if corr_r1 > 0:
                    self.alertas.append(f"   ✅ {corr_r1} domingos reparados!")
                else:
                    self.alertas.append("   ✅ R1 OK — todos têm domingo!")

                # 9c. Corrigir quantidade de folgas no mês (R2 CLT)
                self.alertas.append("\n🔧 VERIFICANDO QUANTIDADE DE FOLGAS NO MÊS...")
                prob_folgas = self._validar_folgas_mes()
                if prob_folgas:
                    self.alertas.append("   ⚠️ Ajustando folgas mensais...")
                    self._corrigir_folgas_mes()
                    prob_folgas = self._validar_folgas_mes()
                if not prob_folgas:
                    self.alertas.append("   ✅ Folgas mensais OK!")

                # 10. Validações finais
                self._validar_e_alertar_consecutividade()
                problemas_domingo = self._validar_e_alertar_domingo_folga()
                problemas_lotacao = self._validar_minimos_por_dia()
                prob_folgas_final = self._validar_folgas_mes()

                # 11. Salvar no banco
                self._salvar_dias_escala(escala)

                # 12. Status final — as 3 regras são leis absolutas, sem exceção
                erros = []
                if problemas_domingo:
                    erros.append(("\n❌ R1 VIOLADA — funcionários sem domingo de folga:", problemas_domingo))
                if prob_folgas_final:
                    erros.append(("\n❌ FOLGAS MENSAIS INCORRETAS:", prob_folgas_final))
                if problemas_lotacao:
                    erros.append(("\n❌ LOTAÇÃO MÍNIMA NÃO ATENDIDA:", problemas_lotacao))

                if erros:
                    escala.gerada_com_sucesso = False
                    for titulo, itens in erros:
                        self.alertas.append(titulo)
                        self.alertas.extend([f"   ❌ {i}" for i in itens])
                    self.alertas.append("\n⛔ Escala inválida — as regras obrigatórias não foram atendidas.")
                else:
                    escala.gerada_com_sucesso = True
                    self.alertas.append("\n✅ Escala gerada com sucesso! Todas as regras atendidas.")
                
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
            id__in=self.escala_gerada.keys()
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

                setor_func = func.grupo
                turno_func = func.turno
                st_obj = SetorTurno.objects.filter(setor=setor_func, turno=turno_func).first() if setor_func and turno_func else None
                minimo_st = st_obj.minimo_funcionarios if st_obj else 0
                funcionarios_st = list(Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, grupo=setor_func, turno=turno_func
                )) if setor_func and turno_func else []

                for dia_folga in candidatos:
                    trabalhando = sum(
                        1 for f in funcionarios_st
                        if f.id != func.id and
                        self.escala_gerada.get(f.id, {}).get(dia_folga) == 'TRABALHA'
                    )

                    if trabalhando >= minimo_st:
                        self.escala_gerada[func.id][dia_folga] = 'FOLGA'
                        correcoes += 1
                        inserido = True
                        break

                if not inserido:
                    # R3: escolher dia com maior cobertura E que não conflite com folguista garantido
                    def cobertura_dia(d):
                        reg = sum(
                            1 for f in funcionarios_st
                            if f.id != func.id and
                            self.escala_gerada.get(f.id, {}).get(d) == 'TRABALHA'
                        )
                        # Penalizar dias onde o folguista garantido também está de folga
                        folg_folga = sum(
                            1 for fid, dom in self.domingo_garantido.items()
                            if dom == d and self.escala_gerada.get(fid, {}).get(d) == 'FOLGA'
                        )
                        return reg - folg_folga * 10
                    melhor_dia = max(violacao, key=cobertura_dia)
                    self.escala_gerada[func.id][melhor_dia] = 'FOLGA'
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
                # R1: nunca mover o domingo garantido para TRABALHA
                dom_sagrado = self.domingo_garantido.get(func_id)
                candidatos_meio = [d for d in range(violacao[0], violacao[1]+1) if d != dom_sagrado]
                meio = candidatos_meio[len(candidatos_meio)//2] if candidatos_meio else violacao[0] + (violacao[1]-violacao[0])//2
                sem = semana_do(meio)
                if not sem:
                    break

                setor = func.grupo
                turno = func.turno
                st_obj2 = SetorTurno.objects.filter(setor=setor, turno=turno).first() if setor and turno else None
                minimo = st_obj2.minimo_funcionarios if st_obj2 else 0
                colegas = list(Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, grupo=setor, turno=turno
                ).exclude(id=func_id)) if setor and turno else []

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
        ).select_related('turno', 'grupo'))
        removidos = 0

        for func in funcionarios:
            quota = sum(self._folgas_semana(func, len(s)) for s in semanas)
            dias_folga = sorted(
                [d for d, s in self.escala_gerada[func.id].items() if s == 'FOLGA']
            )
            excesso = len(dias_folga) - quota
            if excesso <= 0:
                continue

            setor = func.grupo
            turno = func.turno
            st_obj = SetorTurno.objects.filter(setor=setor, turno=turno).first() if setor and turno else None
            minimo = st_obj.minimo_funcionarios if st_obj else 0
            colegas = [
                f for f in Funcionario.objects.filter(tipo='REGULAR', ativo=True, grupo=setor, turno=turno)
                if f.id != func.id
            ] if setor and turno else []

            def cobertura(dia):
                return sum(
                    1 for f in colegas
                    if self.escala_gerada.get(f.id, {}).get(dia) == 'TRABALHA'
                )

            # Remove folgas onde os colegas já cobrem o mínimo (dias mais seguros para remover)
            # R1: nunca remover o domingo garantido
            domingo_sagrado = self.domingo_garantido.get(func.id)
            candidatos = sorted(
                [d for d in dias_folga if d != domingo_sagrado],
                key=lambda d: -cobertura(d)
            )
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

    def _garantir_domingos(self, funcionarios_regulares):
        """
        R1: Todo funcionário recebe exatamente 1 domingo de folga.
        R2: Dentro do mesmo setor/turno, domingos são distribuídos sem conflito.
        Deve rodar ANTES de qualquer outra distribuição de folgas.
        """
        domingos = [d for d in range(1, self.dias_mes + 1)
                    if date(self.ano, self.mes, d).weekday() == 6]
        if not domingos:
            self.alertas.append("⚠️ Mês sem domingo — R1 não aplicável")
            return

        # Agrupar por setor+turno para aplicar R2
        by_st = {}
        for func in funcionarios_regulares:
            key = (func.grupo_id, func.turno_id)
            by_st.setdefault(key, []).append(func)

        for (setor_id, turno_id), funcs in by_st.items():
            st_obj = SetorTurno.objects.filter(
                setor_id=setor_id, turno_id=turno_id
            ).first() if setor_id and turno_id else None
            minimo = st_obj.minimo_funcionarios if st_obj else 1

            random.shuffle(funcs)  # variar distribuição a cada geração
            domingos_usados_no_turno = {}  # domingo -> qtd de funcs já alocados

            for func in funcs:
                # R2: prefere domingos menos usados no mesmo setor/turno
                candidatos = sorted(domingos,
                                    key=lambda d: (domingos_usados_no_turno.get(d, 0), d))

                dom_escolhido = None
                for dom in candidatos:
                    # R3: verifica se mínimo do setor/turno é mantido
                    outros_trabalhando = sum(
                        1 for f in funcs
                        if f.id != func.id and
                        self.escala_gerada[f.id].get(dom, 'TRABALHA') == 'TRABALHA'
                    )
                    if len(funcs) == 1 or outros_trabalhando >= minimo:
                        dom_escolhido = dom
                        break

                # Se nenhum domingo mantém o mínimo, escolhe o de menor impacto
                if dom_escolhido is None:
                    dom_escolhido = max(
                        domingos,
                        key=lambda d: sum(
                            1 for f in funcs if f.id != func.id and
                            self.escala_gerada[f.id].get(d, 'TRABALHA') == 'TRABALHA'
                        )
                    )
                    self.alertas.append(
                        f"⚠️ R1: {func.nome} — domingo {dom_escolhido}/{self.mes:02d} "
                        f"viola mínimo do setor (sem alternativa)"
                    )

                self.escala_gerada[func.id][dom_escolhido] = 'FOLGA'
                self.domingo_garantido[func.id] = dom_escolhido  # R1: nunca remover
                domingos_usados_no_turno[dom_escolhido] = \
                    domingos_usados_no_turno.get(dom_escolhido, 0) + 1

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
    
    def _gerar_escala_setor(self, setor, feriados):
        """Gera escala para um setor, respeitando o regime individual de cada funcionário"""
        funcionarios = list(Funcionario.objects.filter(
            tipo='REGULAR',
            ativo=True,
            grupo=setor
        ).select_related('turno'))

        if not funcionarios:
            self.alertas.append(f"⚠️ Setor {setor.nome}: Nenhum funcionário!")
            return False

        # Mínimo do setor = soma dos mínimos por turno configurados em SetorTurno
        minimo = sum(
            st.minimo_funcionarios
            for st in SetorTurno.objects.filter(setor=setor)
        ) or 1

        # Folguistas habilitados para este setor funcionam como cobertura de backup.
        folguistas_backup = Funcionario.objects.filter(
            tipo='FOLGUISTA', ativo=True, grupos_habilitados=setor
        ).count()
        minimo_regulares = max(0, minimo - folguistas_backup)

        # Manter domingos já garantidos pela R1 (_garantir_domingos rodou antes)
        # Apenas preencher dias ainda não inicializados
        for func in funcionarios:
            if func.id not in self.escala_gerada:
                self.escala_gerada[func.id] = {dia: 'TRABALHA' for dia in range(1, self.dias_mes + 1)}
            else:
                # Preservar folgas já atribuídas (domingos R1) — garantir que demais dias existem
                for dia in range(1, self.dias_mes + 1):
                    self.escala_gerada[func.id].setdefault(dia, 'TRABALHA')

        semanas = self._dividir_em_semanas_correto()

        for idx_semana, semana in enumerate(semanas):
            semana_anterior = semanas[idx_semana - 1] if idx_semana > 0 else None
            sucesso = self._processar_semana(funcionarios, semana, minimo_regulares, idx_semana + 1, semana_anterior, setor=setor)
            if not sucesso:
                self.alertas.append(f"⚠️ Setor {setor.nome} — Semana {idx_semana + 1}: Impossível distribuir folgas!")

        return True

    def _dias_criticos_folguista(self, func):
        """Retorna conjunto de dias onde o folguista não pode folgar.
        Um dia é crítico se algum setor habilitado ficaria abaixo do mínimo sem ele."""
        setores_hab = list(func.grupos_habilitados.all())
        if not setores_hab:
            return set()

        # Pré-carregar SetorTurno para setores habilitados
        setor_turnos_hab = list(
            SetorTurno.objects.filter(setor__in=setores_hab).select_related('setor', 'turno')
        )

        criticos = set()
        for dia in range(1, self.dias_mes + 1):
            for st in setor_turnos_hab:
                regulares = Funcionario.objects.filter(tipo='REGULAR', ativo=True, grupo=st.setor, turno=st.turno)
                trabalhando = sum(
                    1 for f in regulares
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                if trabalhando < st.minimo_funcionarios:
                    criticos.add(dia)
                    break
        return criticos

    def _gerar_escala_folguistas(self):
        """Gera folgas para funcionários FOLGUISTA com base no regime deles.
        Nunca coloca folga em dia crítico (dia onde algum setor habilitado ficaria sem mínimo)."""
        folguistas = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('grupos_habilitados')
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

            # R1: garantir 1 domingo para o folguista (preferir não-crítico)
            domingos = [d for d in range(1, self.dias_mes + 1)
                        if date(self.ano, self.mes, d).weekday() == 6]
            dom_folguista = next((d for d in domingos if d not in dias_criticos), None)
            if dom_folguista:
                self.escala_gerada[func.id][dom_folguista] = 'FOLGA'
                self.domingo_garantido[func.id] = dom_folguista

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

                # Dias disponíveis para folga nesta semana (excluindo críticos e já marcados)
                ja_tem_semana = sum(1 for d in semana if self.escala_gerada[func.id].get(d) == 'FOLGA')
                folgas_necessarias = max(0, folgas_necessarias - ja_tem_semana)
                if folgas_necessarias == 0:
                    continue
                dias_livres = [
                    d for d in semana
                    if d not in dias_criticos
                    and self.escala_gerada[func.id].get(d) != 'FOLGA'
                ]

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
        Atribui setor+turno a cada dia de trabalho do folguista.

        Lógica: o folguista cobre o setor do funcionário REGULAR que está de
        FOLGA naquele dia (é para isso que o folguista existe).

        Prioridade:
          1. Setor×turno com regular de folga (déficit real) — habilitado p/ folguista
          2. Setor×turno configurado em SetorTurno com maior déficit — habilitado p/ folguista
          3. Fallback: turno com menor cobertura dentre os turnos_habilitados
        """
        folguistas = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('grupos_habilitados', 'turnos_habilitados')
        )
        if not folguistas:
            return

        # Cache: folguista -> set de setor_ids e turno_ids habilitados
        setores_hab_cache = {
            f.id: set(f.grupos_habilitados.values_list('id', flat=True))
            for f in folguistas
        }
        turnos_hab_cache = {
            f.id: set(f.turnos_habilitados.values_list('id', flat=True))
            for f in folguistas
        }

        # Todos os SetorTurno configurados
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())

        # Todos os regulares com setor+turno para verificar quem está de folga
        regulares = list(
            Funcionario.objects.filter(tipo='REGULAR', ativo=True)
            .select_related('grupo', 'turno')
        )

        for dia in range(1, self.dias_mes + 1):
            # Monta situação dos regulares neste dia
            # quem_de_folga: lista de (setor_id, turno_id) de regulares que estão de FOLGA
            quem_de_folga = []
            contagem_st = {}  # (setor_id, turno_id) -> quantos trabalhando

            for reg in regulares:
                if reg.grupo is None or reg.turno is None:
                    continue
                key = (reg.grupo.id, reg.turno.id)
                sit = self.escala_gerada.get(reg.id, {}).get(dia, 'TRABALHA')
                if sit == 'TRABALHA':
                    contagem_st[key] = contagem_st.get(key, 0) + 1
                else:
                    quem_de_folga.append(key)

            for func in folguistas:
                if self.escala_gerada.get(func.id, {}).get(dia) != 'TRABALHA':
                    continue
                if dia in self.setor_coberto.get(func.id, {}):
                    continue

                hab_ids_setor = setores_hab_cache.get(func.id, set())
                hab_ids_turno = turnos_hab_cache.get(func.id, set())

                # 1. Prioridade: cobrir folga real de um regular habilitado
                candidatos_folga = [
                    (sid, tid) for (sid, tid) in quem_de_folga
                    if sid in hab_ids_setor and tid in hab_ids_turno
                ]

                if candidatos_folga:
                    # Escolhe o par (setor, turno) com menor cobertura atual (mais crítico)
                    def urgencia_folga(par):
                        sid, tid = par
                        st_match = next((st for st in setor_turnos if st.setor.id == sid and st.turno.id == tid), None)
                        minimo_st = st_match.minimo_funcionarios if st_match else 1
                        atual = contagem_st.get((sid, tid), 0)
                        # Menor ratio = mais urgente; desempate: menos regulares no turno
                        total_reg = sum(1 for r in regulares if r.grupo_id == sid and r.turno_id == tid)
                        return (atual / max(minimo_st, 1), total_reg)

                    sid, tid = min(set(candidatos_folga), key=urgencia_folga)
                    setor_obj = next((st.setor for st in setor_turnos if st.setor.id == sid), None)
                    turno_obj = next((st.turno for st in setor_turnos if st.turno.id == tid), None)
                    if not setor_obj:
                        setor_obj = Grupo.objects.filter(id=sid).first()
                    if not turno_obj:
                        turno_obj = Turno.objects.filter(id=tid).first()

                    if setor_obj and turno_obj:
                        self.setor_coberto.setdefault(func.id, {})[dia] = sid
                        self.turno_coberto.setdefault(func.id, {})[dia] = tid
                        contagem_st[(sid, tid)] = contagem_st.get((sid, tid), 0) + 1
                        if (sid, tid) in quem_de_folga:
                            quem_de_folga.remove((sid, tid))
                        continue

                # 2. Fallback: SetorTurno configurado com maior déficit
                habilitados_st = [
                    st for st in setor_turnos
                    if st.setor.id in hab_ids_setor and st.turno.id in hab_ids_turno
                ]
                if habilitados_st:
                    def deficit_st(st):
                        return st.minimo_funcionarios - contagem_st.get((st.setor.id, st.turno.id), 0)
                    escolhido = max(habilitados_st, key=deficit_st)
                    self.setor_coberto.setdefault(func.id, {})[dia] = escolhido.setor.id
                    self.turno_coberto.setdefault(func.id, {})[dia] = escolhido.turno.id
                    contagem_st[(escolhido.setor.id, escolhido.turno.id)] = \
                        contagem_st.get((escolhido.setor.id, escolhido.turno.id), 0) + 1
                    continue

                # 3. Último recurso: turno habilitado com menos cobertura
                if hab_ids_turno:
                    turnos_hab = list(Turno.objects.filter(id__in=hab_ids_turno))
                    turno_escolhido = min(
                        turnos_hab,
                        key=lambda t: sum(1 for d2 in self.turno_coberto.values() if d2.get(dia) == t.id)
                    )
                    self.turno_coberto.setdefault(func.id, {})[dia] = turno_escolhido.id
                key = (escolhido.setor.id, escolhido.turno.id)
                contagem_st[key] = contagem_st.get(key, 0) + 1

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

    def _combinacao_respeita_consecutivos(self, func_id, combinacao, dias_semana, semana_anterior, limite):
        """Retorna True se a combinação de folgas não gera mais de 'limite' dias consecutivos de trabalho."""
        folgas = set(combinacao)
        # Streak no final da semana anterior
        streak = 0
        if semana_anterior:
            for d in reversed(semana_anterior):
                if self.escala_gerada[func_id].get(d) == 'TRABALHA':
                    streak += 1
                else:
                    break
        for d in dias_semana:
            if d in folgas:
                streak = 0
            else:
                streak += 1
                if streak > limite:
                    return False
        return True

    def _processar_semana(self, funcionarios, dias_semana, minimo, num_semana, semana_anterior=None, setor=None):
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

                # R1: descontar folgas já atribuídas nesta semana (domingo pré-garantido)
                ja_tem = sum(
                    1 for d in dias_semana
                    if self.escala_gerada[func_id].get(d) == 'FOLGA'
                )
                folgas_necessarias = max(0, folgas_necessarias - ja_tem)

                if folgas_necessarias == 0:
                    continue

                exigir_nc = self._regime_aplica_consecutivas(func.regime)

                # Dias disponíveis para nova folga nesta semana (excluir já marcados)
                dias_livres_semana = [
                    d for d in dias_semana
                    if self.escala_gerada[func_id].get(d) != 'FOLGA'
                ]

                # 1ª prioridade: dia fixo configurado (folga_fixa_dia)
                combinacoes_fixas = self._combinacoes_dia_fixo(func, dias_livres_semana, folgas_necessarias)

                if combinacoes_fixas:
                    combinacoes = combinacoes_fixas
                else:
                    combinacoes = self._gerar_combinacoes_validas(dias_livres_semana, folgas_necessarias, exigir_nc)

                if not combinacoes:
                    sucesso_total = False
                    break

                # Filtrar combinações que violam o limite máximo de dias consecutivos (CLT)
                limite_consec = 6 if func.regime == '6x1' else 5
                combinacoes = [
                    c for c in combinacoes
                    if self._combinacao_respeita_consecutivos(func_id, c, dias_semana, semana_anterior, limite_consec)
                ]
                if not combinacoes:
                    combinacoes = combinacoes_fixas or self._gerar_combinacoes_validas(dias_livres_semana, folgas_necessarias, False) or []

                if not combinacoes:
                    sucesso_total = False
                    break

                # Ordenar por prioridade de sábado (domingo já garantido pela R1)
                if not combinacoes_fixas:
                    sabado_semana = next(
                        (d for d in dias_semana if date(self.ano, self.mes, d).weekday() == 5),
                        None
                    )
                    if func.regime == '5x2' and sabado_semana:
                        com_sab = [c for c in combinacoes if sabado_semana in c]
                        sem_sab = [c for c in combinacoes if sabado_semana not in c]
                        random.shuffle(com_sab)
                        random.shuffle(sem_sab)
                        combinacoes = com_sab + sem_sab
                    else:
                        random.shuffle(combinacoes)

                folga_atribuida = False
                for combinacao in combinacoes:
                    if self._combinacao_mantem_minimo(func_id, combinacao, funcionarios, minimo, setor=setor):
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

        # Fallback: dá folgas ignorando mínimo, mas SEMPRE respeitando limite de consecutivos (CLT)
        sabado_semana_fb = next(
            (d for d in dias_semana if date(self.ano, self.mes, d).weekday() == 5), None
        )
        for func in funcionarios:
            folgas_necessarias = self._folgas_semana(func, dias_count)
            if folgas_necessarias == 0:
                continue
            ja_tem = sum(1 for d in dias_semana if self.escala_gerada[func.id].get(d) == 'FOLGA')
            if ja_tem >= folgas_necessarias:
                continue
            folgas_necessarias -= ja_tem
            dias_livres_fb = [
                d for d in dias_semana
                if self.escala_gerada[func.id].get(d) != 'FOLGA'
            ]

            limite_consec = 6 if func.regime == '6x1' else 5
            fixas_raw = self._combinacoes_dia_fixo(func, dias_livres_fb, folgas_necessarias) or []
            combinacoes_fixas = [
                c for c in fixas_raw
                if self._combinacao_respeita_consecutivos(func.id, c, dias_semana, semana_anterior, limite_consec)
            ]

            if combinacoes_fixas:
                # R3: no fallback, priorizar combinação que mantém mínimo
                com_minimo = [c for c in combinacoes_fixas
                              if self._combinacao_mantem_minimo(func.id, c, funcionarios, minimo, setor=setor)]
                combinacao = random.choice(com_minimo) if com_minimo else combinacoes_fixas[0]
            else:
                exigir_nc = self._regime_aplica_consecutivas(func.regime)
                combinacoes = self._gerar_combinacoes_validas(dias_livres_fb, folgas_necessarias, exigir_nc)
                if not combinacoes:
                    combinacoes = self._gerar_combinacoes_validas(dias_livres_fb, folgas_necessarias, False)
                if not combinacoes:
                    continue

                validas = [
                    c for c in combinacoes
                    if self._combinacao_respeita_consecutivos(func.id, c, dias_semana, semana_anterior, limite_consec)
                ]
                combinacoes = validas if validas else combinacoes

                # R3: priorizar combinações que mantêm mínimo
                com_minimo = [c for c in combinacoes
                              if self._combinacao_mantem_minimo(func.id, c, funcionarios, minimo, setor=setor)]
                combinacoes = com_minimo if com_minimo else combinacoes

                if sabado_semana_fb:
                    com_sab = [c for c in combinacoes if sabado_semana_fb in c]
                    combinacoes = com_sab + [c for c in combinacoes if c not in com_sab]

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
    
    def _combinacao_mantem_minimo(self, func_id, dias_folga, funcionarios, minimo, setor=None):
        """Verifica se folgas mantém mínimo em todos os dias.
        Checa tanto o mínimo total do setor quanto o mínimo por turno (SetorTurno).
        Desconta folguistas habilitados do mínimo exigido de regulares (eles cobrem a folga)."""
        setor_turnos = list(SetorTurno.objects.filter(setor=setor).select_related('turno')) if setor else []

        # Pré-computar quantos folguistas habilitados existem para cada turno deste setor
        folguistas_por_turno = {}
        for st in setor_turnos:
            folguistas_por_turno[st.turno.id] = Funcionario.objects.filter(
                tipo='FOLGUISTA', ativo=True,
                grupos_habilitados=setor,
                turnos_habilitados=st.turno
            ).count()

        for dia in dias_folga:
            # 1. Mínimo total do setor
            trabalhando = sum(
                1 for f in funcionarios
                if f.id != func_id and (
                    f.id not in self.escala_gerada or
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
            )
            if trabalhando < minimo:
                return False

            # 2. Mínimo por turno — desconta folguistas habilitados disponíveis
            for st in setor_turnos:
                regulares_no_turno = [f for f in funcionarios if f.turno_id == st.turno.id]
                if not regulares_no_turno:
                    continue

                # Folguistas habilitados reduzem o mínimo exigido de regulares
                folg_backup = folguistas_por_turno.get(st.turno.id, 0)
                minimo_regulares = max(0, min(st.minimo_funcionarios, len(regulares_no_turno)) - folg_backup)

                turno_trabalhando = sum(
                    1 for f in regulares_no_turno
                    if f.id != func_id and (
                        f.id not in self.escala_gerada or
                        self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                    )
                )
                if turno_trabalhando < minimo_regulares:
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
        ).select_related('grupo'))

        # Pré-computar colegas de setor por funcionário
        colegas_setor = {}
        for func in funcs:
            if func.grupo:
                colegas_setor[func.id] = [
                    f for f in funcs
                    if f.id != func.id and f.grupo_id == func.grupo_id
                ]
            else:
                colegas_setor[func.id] = []

        # Pré-carregar folguistas com setores habilitados
        folguistas_ativos = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('grupos_habilitados')
        )

        for func in funcs:
            if func.regime != '6x1':
                continue

            tem_domingo = any(
                self.escala_gerada[func.id].get(dom) != 'TRABALHA'
                for dom in domingos
            )
            if tem_domingo:
                continue

            st_dom = SetorTurno.objects.filter(setor=func.grupo, turno=func.turno).first() if func.grupo and func.turno else None
            minimo = st_dom.minimo_funcionarios if st_dom else 0

            for domingo in domingos:
                if self.escala_gerada[func.id].get(domingo) != 'TRABALHA':
                    continue

                semana_domingo = self._encontrar_semana_do_dia(domingo)
                if not semana_domingo:
                    continue

                # Cobertura regular no domingo
                colegas = colegas_setor[func.id]
                regulares_no_domingo = sum(
                    1 for f in colegas
                    if self.escala_gerada.get(f.id, {}).get(domingo) == 'TRABALHA'
                )

                # Folguistas cobrindo este setor no domingo
                folguistas_cobrindo = [
                    f for f in folguistas_ativos
                    if (self.escala_gerada.get(f.id, {}).get(domingo) == 'TRABALHA'
                        and func.grupo
                        and func.grupo.id in f.grupos_habilitados.values_list('id', flat=True))
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

                    # Atualizar setor_coberto do folguista ANTES de validar
                    folg_backup = None
                    if folguistas_cobrindo and func.grupo:
                        folg = folguistas_cobrindo[0]
                        old_setor = self.setor_coberto.get(folg.id, {}).get(domingo)
                        folg_backup = (folg.id, domingo, old_setor)
                        if folg.id not in self.setor_coberto:
                            self.setor_coberto[folg.id] = {}
                        self.setor_coberto[folg.id][domingo] = func.grupo.id

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
                            fid, d, old_s = folg_backup
                            if old_s is None:
                                self.setor_coberto.get(fid, {}).pop(d, None)
                            else:
                                self.setor_coberto[fid][d] = old_s

                if trocou:
                    break

        return trocas_realizadas
    
    def _folgas_esperadas_mes(self, func):
        """Retorna o total de folgas que o funcionário deve ter no mês."""
        semanas = self._dividir_em_semanas_correto()
        return sum(self._folgas_semana(func, len(sem)) for sem in semanas)

    def _validar_folgas_mes(self):
        """Retorna lista de funcionários com quantidade errada de folgas no mês."""
        problemas = []
        funcionarios = Funcionario.objects.filter(
            id__in=list(self.escala_gerada.keys()), tipo='REGULAR', ativo=True
        )
        for func in funcionarios:
            esperadas = self._folgas_esperadas_mes(func)
            reais = sum(1 for s in self.escala_gerada[func.id].values() if s != 'TRABALHA')
            if reais != esperadas:
                problemas.append(f"{func.nome} ({func.regime}): {reais} folgas, esperado {esperadas}")
        return problemas

    def _corrigir_folgas_mes(self):
        """Ajusta a quantidade de folgas de cada funcionário para o total correto do mês."""
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())
        domingos = {d for d in range(1, self.dias_mes + 1) if date(self.ano, self.mes, d).weekday() == 6}
        funcionarios = {
            f.id: f for f in Funcionario.objects.filter(
                id__in=list(self.escala_gerada.keys()), tipo='REGULAR', ativo=True
            ).select_related('grupo', 'turno')
        }

        def cobertura(func_id, dia):
            func = funcionarios.get(func_id)
            if not func:
                return 99
            return sum(
                1 for fid, esc in self.escala_gerada.items()
                if fid != func_id and esc.get(dia) == 'TRABALHA'
                and funcionarios.get(fid) and funcionarios[fid].grupo_id == func.grupo_id
                and funcionarios[fid].turno_id == func.turno_id
            )

        def minimo_st(func_id):
            func = funcionarios.get(func_id)
            if not func:
                return 1
            st = next((s for s in setor_turnos if s.setor.id == func.grupo_id and s.turno.id == func.turno_id), None)
            return st.minimo_funcionarios if st else 1

        for func_id, escala in self.escala_gerada.items():
            func = funcionarios.get(func_id)
            if not func:
                continue
            esperadas = self._folgas_esperadas_mes(func)
            reais = sum(1 for s in escala.values() if s != 'TRABALHA')
            dom_sagrado = self.domingo_garantido.get(func_id)

            if reais > esperadas:
                # Remover folgas excedentes — começar pelos dias com mais cobertura (menos impacto)
                folgas = sorted(
                    [d for d, s in escala.items() if s != 'TRABALHA' and d != dom_sagrado],
                    key=lambda d: -cobertura(func_id, d)
                )
                for d in folgas:
                    if reais <= esperadas:
                        break
                    self.escala_gerada[func_id][d] = 'TRABALHA'
                    reais -= 1

            elif reais < esperadas:
                # Adicionar folgas — escolher dias de trabalho com mais cobertura
                trabalha = sorted(
                    [d for d, s in escala.items() if s == 'TRABALHA' and d not in domingos],
                    key=lambda d: -cobertura(func_id, d)
                )
                for d in trabalha:
                    if reais >= esperadas:
                        break
                    cob = cobertura(func_id, d)
                    if cob >= minimo_st(func_id):
                        self.escala_gerada[func_id][d] = 'FOLGA'
                        reais += 1

    def _cobrir_deficits_com_folguistas(self):
        """
        Para cada déficit de lotação restante, tenta realocar um folguista habilitado:
        - Se o folguista está de FOLGA naquele dia → move a folga para outro dia válido
        - Se o folguista está TRABALHANDO mas cobrindo outro setor → reatribui para o déficit
        Só age se o folguista for habilitado para o setor E turno do déficit.
        """
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())
        folguistas = list(
            Funcionario.objects.filter(tipo='FOLGUISTA', ativo=True)
            .prefetch_related('grupos_habilitados', 'turnos_habilitados')
        )
        if not folguistas:
            return 0

        hab_setor = {f.id: set(f.grupos_habilitados.values_list('id', flat=True)) for f in folguistas}
        hab_turno = {f.id: set(f.turnos_habilitados.values_list('id', flat=True)) for f in folguistas}
        domingos = {d for d in range(1, self.dias_mes + 1) if date(self.ano, self.mes, d).weekday() == 6}
        correcoes = 0

        for dia in range(1, self.dias_mes + 1):
            for st in setor_turnos:
                if st.permite_zero:
                    continue
                regulares_st = [
                    f for f in Funcionario.objects.filter(tipo='REGULAR', ativo=True, grupo=st.setor, turno=st.turno)
                ]
                if not regulares_st:
                    continue

                reg_trabalhando = sum(
                    1 for f in regulares_st
                    if self.escala_gerada.get(f.id, {}).get(dia) == 'TRABALHA'
                )
                folg_cobrindo = sum(
                    1 for fid in self.setor_coberto
                    if self.setor_coberto[fid].get(dia) == st.setor.id
                    and self.turno_coberto.get(fid, {}).get(dia) == st.turno.id
                    and self.escala_gerada.get(fid, {}).get(dia) == 'TRABALHA'
                )
                if reg_trabalhando + folg_cobrindo >= st.minimo_funcionarios:
                    continue  # Sem déficit aqui

                # Procurar folguista habilitado
                for folg in folguistas:
                    if st.setor.id not in hab_setor.get(folg.id, set()):
                        continue
                    if st.turno.id not in hab_turno.get(folg.id, set()):
                        continue

                    sit_dia = self.escala_gerada.get(folg.id, {}).get(dia, 'TRABALHA')

                    if sit_dia == 'TRABALHA':
                        # Folguista já trabalhando — só reatribuir cobertura
                        self.setor_coberto.setdefault(folg.id, {})[dia] = st.setor.id
                        self.turno_coberto.setdefault(folg.id, {})[dia] = st.turno.id
                        correcoes += 1
                        break

                    if sit_dia == 'FOLGA':
                        # Déficit sem permite_zero = folguista habilitado vai obrigatoriamente
                        self.escala_gerada[folg.id][dia] = 'TRABALHA'
                        self.setor_coberto.setdefault(folg.id, {})[dia] = st.setor.id
                        self.turno_coberto.setdefault(folg.id, {})[dia] = st.turno.id
                        correcoes += 1
                        break

                # Re-checar se déficit foi resolvido
                reg_t = sum(1 for f in regulares_st if self.escala_gerada.get(f.id, {}).get(dia) == 'TRABALHA')
                folg_t = sum(
                    1 for fid in self.setor_coberto
                    if self.setor_coberto[fid].get(dia) == st.setor.id
                    and self.turno_coberto.get(fid, {}).get(dia) == st.turno.id
                    and self.escala_gerada.get(fid, {}).get(dia) == 'TRABALHA'
                )
                if reg_t + folg_t >= st.minimo_funcionarios:
                    continue  # Resolvido

        return correcoes

    def _validar_minimos_por_dia(self):
        """Valida se todos os dias têm lotação mínima por setor×turno.
        Conta regulares (grupo+turno) + folguistas (setor_coberto+turno_coberto)."""
        problemas = []
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())

        for dia in range(1, self.dias_mes + 1):
            for st in setor_turnos:
                funcionarios_st = Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, grupo=st.setor, turno=st.turno
                )
                if not funcionarios_st.exists():
                    continue

                regulares = sum(
                    1 for func in funcionarios_st
                    if func.id in self.escala_gerada and
                    self.escala_gerada[func.id].get(dia) == 'TRABALHA'
                )
                folguistas = sum(
                    1 for fid, dias_setor in self.setor_coberto.items()
                    if dias_setor.get(dia) == st.setor.id and
                    self.turno_coberto.get(fid, {}).get(dia) == st.turno.id
                )
                trabalhando = regulares + folguistas

                if trabalhando < st.minimo_funcionarios and not st.permite_zero:
                    problemas.append(
                        f"DIA {dia:02d}/{self.mes:02d} - "
                        f"{st.setor.nome}/{st.turno.nome}: {trabalhando}/{st.minimo_funcionarios}"
                    )

        return problemas

    def _corrigir_por_redistribuicao(self):
        """Corrige lotação movendo folgas dentro da mesma semana (por setor×turno)"""
        correcoes_feitas = 0
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())
        semanas = self._dividir_em_semanas_correto()

        for st in setor_turnos:
            funcionarios_st = list(Funcionario.objects.filter(
                tipo='REGULAR', ativo=True, grupo=st.setor, turno=st.turno
            ))

            if not funcionarios_st:
                continue

            for dia in range(1, self.dias_mes + 1):
                regulares = sum(
                    1 for f in funcionarios_st
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                folguistas = sum(
                    1 for fid, dias_setor in self.setor_coberto.items()
                    if dias_setor.get(dia) == st.setor.id and
                    self.turno_coberto.get(fid, {}).get(dia) == st.turno.id
                )
                trabalhando = regulares + folguistas
                falta = st.minimo_funcionarios - trabalhando

                if falta <= 0:
                    continue

                candidatos = [
                    f for f in funcionarios_st
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'FOLGA'
                ]

                for candidato in candidatos[:falta]:
                    if self._tentar_trocar_folga_mesma_semana(candidato.id, dia, funcionarios_st, st.minimo_funcionarios, semanas):
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
        """Valida lotação de dias específicos por setor×turno, contando regulares + folguistas."""
        setor_turnos = list(SetorTurno.objects.select_related('setor', 'turno').all())

        for dia in dias:
            for st in setor_turnos:
                funcionarios_st = Funcionario.objects.filter(
                    tipo='REGULAR', ativo=True, grupo=st.setor, turno=st.turno
                )
                if not funcionarios_st.exists():
                    continue

                regulares = sum(
                    1 for f in funcionarios_st
                    if f.id in self.escala_gerada and
                    self.escala_gerada[f.id].get(dia) == 'TRABALHA'
                )
                folguistas = sum(
                    1 for fid, dias_setor in self.setor_coberto.items()
                    if dias_setor.get(dia) == st.setor.id and
                    self.turno_coberto.get(fid, {}).get(dia) == st.turno.id
                )

                if regulares + folguistas < st.minimo_funcionarios and not st.permite_zero:
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
    
    def _corrigir_r1_pos_geracao(self):
        """
        Reparo determinístico R1: para cada funcionário sem domingo de folga,
        tenta trocar um dos seus dias de FOLGA pelo domingo mais coberto do mês.
        Se nenhuma troca valida CLT + lotação, força o domingo mesmo assim (R1 é lei).
        """
        domingos = [d for d in range(1, self.dias_mes + 1)
                    if date(self.ano, self.mes, d).weekday() == 6]
        if not domingos:
            return 0

        funcionarios_map = {
            f.id: f for f in Funcionario.objects.filter(
                ativo=True
            ).select_related('grupo', 'turno')
        }
        correcoes = 0

        for func_id, escala in self.escala_gerada.items():
            # Já tem domingo?
            if any(escala.get(d, 'TRABALHA') != 'TRABALHA' for d in domingos):
                continue

            func = funcionarios_map.get(func_id)
            if not func:
                continue

            # Colegas do mesmo setor/turno (para medir cobertura)
            colegas = [
                fid for fid, f in funcionarios_map.items()
                if fid != func_id
                and f.grupo_id == func.grupo_id
                and f.turno_id == func.turno_id
            ]

            def cobertura(dia):
                return sum(1 for fid in colegas
                           if self.escala_gerada.get(fid, {}).get(dia) == 'TRABALHA')

            # Dias de folga não-domingo disponíveis para trocar
            dias_folga = [d for d in range(1, self.dias_mes + 1)
                          if escala.get(d) == 'FOLGA' and d not in domingos]

            # Domingos ordenados por maior cobertura (mais seguros para receber folga)
            domingos_ord = sorted(domingos, key=cobertura, reverse=True)

            reparado = False
            for dom in domingos_ord:
                # Ordenar folgas a remover: escolher dia com mais cobertura (menos impacto)
                folgas_ord = sorted(dias_folga, key=cobertura, reverse=True)

                for dia_trocar in folgas_ord:
                    self.escala_gerada[func_id][dia_trocar] = 'TRABALHA'
                    self.escala_gerada[func_id][dom] = 'FOLGA'

                    valido = (
                        self._validar_consecutividade_funcionario(func_id) and
                        self._validar_lotacao_dias_especificos([dia_trocar, dom])
                    )

                    if valido:
                        self.domingo_garantido[func_id] = dom
                        dias_folga.remove(dia_trocar)
                        correcoes += 1
                        reparado = True
                        break
                    else:
                        # Desfaz
                        self.escala_gerada[func_id][dia_trocar] = 'FOLGA'
                        self.escala_gerada[func_id][dom] = 'TRABALHA'

                if reparado:
                    break

            # Se nenhuma troca válida — forçar o domingo de maior cobertura (R1 é lei)
            if not reparado and domingos_ord:
                dom_forcado = domingos_ord[0]
                # Trocar o dia de folga com menor impacto (mais coberto)
                if dias_folga:
                    dia_trocar = max(dias_folga, key=cobertura)
                    self.escala_gerada[func_id][dia_trocar] = 'TRABALHA'
                self.escala_gerada[func_id][dom_forcado] = 'FOLGA'
                self.domingo_garantido[func_id] = dom_forcado
                correcoes += 1
                self.alertas.append(
                    f"   ⚠️ R1 forçado para {func.nome} — domingo {dom_forcado:02d}/{self.mes:02d} "
                    f"(verifique cobertura desse dia)"
                )

        return correcoes

    def _validar_e_alertar_domingo_folga(self):
        """Valida R1: todo funcionário deve ter pelo menos 1 domingo de folga. Retorna lista de violações."""
        domingos = [
            dia for dia in range(1, self.dias_mes + 1)
            if date(self.ano, self.mes, dia).weekday() == 6
        ]

        if not domingos:
            return []

        problemas = []

        for func_id in self.escala_gerada.keys():
            funcionario = Funcionario.objects.get(id=func_id)

            tem_domingo = any(
                self.escala_gerada[func_id].get(dom, 'TRABALHA') != 'TRABALHA'
                for dom in domingos
            )

            if not tem_domingo:
                problemas.append(f"{funcionario.nome} ({funcionario.regime})")

        return problemas
    
    def _salvar_dias_escala(self, escala):
        """Salva escala no banco"""
        dias_para_criar = []
        turno_cache = {t.id: t for t in Turno.objects.all()}
        setor_cache = {g.id: g for g in Grupo.objects.all()}

        for func_id, dias_func in self.escala_gerada.items():
            funcionario = Funcionario.objects.get(id=func_id)

            for dia, situacao in dias_func.items():
                data = date(self.ano, self.mes, dia)
                turno_cob_id = self.turno_coberto.get(func_id, {}).get(dia)
                turno_cob = turno_cache.get(turno_cob_id) if turno_cob_id else None
                setor_cob_id = self.setor_coberto.get(func_id, {}).get(dia)
                setor_cob = setor_cache.get(setor_cob_id) if setor_cob_id else None

                dias_para_criar.append(
                    DiaEscala(
                        escala=escala,
                        funcionario=funcionario,
                        data=data,
                        situacao=situacao,
                        turno_coberto=turno_cob,
                        setor_coberto=setor_cob,
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