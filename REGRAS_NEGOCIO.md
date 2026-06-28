# EscalaJa — Regras de Negócio

> **IMPORTANTE:** Sempre ler este arquivo antes de qualquer alteração no sistema de geração de escala (`services.py`). A ordem das regras é obrigatória — regras anteriores têm prioridade absoluta sobre as posteriores.

---

## Regras em Ordem de Prioridade

### Regra 1 — Domingo garantido (LEI — prioridade máxima)
- Todo trabalhador recebe **exatamente 1 domingo de folga por mês**
- O domingo é atribuído **PRIMEIRO**, antes de qualquer outra folga
- Nenhuma outra regra pode remover o domingo de um funcionário

### Regra 2 — Domingo distribuído (LEI)
- Dentro do mesmo **setor/turno**, dois trabalhadores **não podem folgar no mesmo domingo**
- Se não houver domingos suficientes para todos sem conflito, gera alerta mas todos ainda recebem pelo menos 1 domingo
- Desempate: quem está há mais tempo sem domingo tem prioridade

### Regra 3 — Lotação mínima é absoluta (LEI)
- Nenhum `SetorTurno` configurado com `minimo_funcionarios ≥ 1` pode chegar a **0 trabalhadores** em qualquer dia
- Contagem = regulares trabalhando + folguistas cobrindo aquele setor/turno naquele dia
- Se impossível resolver → escala marcada como **INVÁLIDA** com alerta claro: `"DIA XX - Setor/Turno: 0/mínimo"`
- **NUNCA silencioso. NUNCA gera com sucesso se houver 0 cobertura.**

### Regra 4 — Dias fixos (preferência, não lei)
- Após garantir domingo (R1) e mínimo (R3), tenta encaixar o `folga_fixa_dia` de cada funcionário
- Se conflitar com R1–R3, o dia fixo cede

### Regra 5 — Máximo consecutivos 5x2 (LEI)
- Regime `5x2`: **nunca mais de 5 dias seguidos** trabalhando
- Vale para todo o mês (não só dentro de uma semana)

### Regra 6 — Máximo consecutivos 6x1 (LEI)
- Regime `6x1`: **nunca mais de 6 dias seguidos** trabalhando
- Vale para todo o mês

### Regra 7 — Configurações do sistema
- Respeitar `ConfiguracaoSistema`: folgas consecutivas, regime alvo, domingo_ativo, etc.
- São preferências configuráveis, não lei — cedem para R1–R6

---

## Modelo de Dados

| Modelo | Descrição |
|---|---|
| `Grupo` | Setor (Bar, Recepção, Copa) |
| `Turno` | Horário (MANHA, TARDE, INTERMEDIARIO, NOITE) |
| `SetorTurno` | Liga Grupo ↔ Turno com `minimo_funcionarios` por combinação |
| `Funcionario.tipo` | `REGULAR` (turno+grupo fixos) ou `FOLGUISTA` (cobre múltiplos via `grupos_habilitados` + `turnos_habilitados`) |
| `DiaEscala.situacao` | `TRABALHA` ou `FOLGA` |
| `DiaEscala.setor_coberto` | Qual setor o folguista cobriu naquele dia |
| `DiaEscala.turno_coberto` | Qual turno o folguista cobriu naquele dia |

### Estruturas em memória durante geração
```python
self.escala_gerada  # {func_id: {dia: situacao}}
self.setor_coberto  # {func_id: {dia: setor_id}}  — só folguistas
self.turno_coberto  # {func_id: {dia: turno_id}}  — só folguistas
```

---

## Ordem de Execução em `services.py`

```
1. Atribuir 1 domingo por funcionário         → R1 + R2
2. Distribuir folgas restantes por semana     → R3 + R4 + R5/R6
3. Gerar folgas dos folguistas                → nunca em dia crítico
4. Atribuir cobertura dos folguistas          → prioridade: menor ratio cobertura/mínimo
5. Corrigir consecutivos remanescentes        → R5/R6
6. Validar mínimos finais                     → R3 bloqueia sucesso se violado
7. Aplicar configurações do sistema           → R7
8. Salvar
```

---

## Cobertura de Folguista — Lógica de Prioridade

Quando o folguista está trabalhando, ele é atribuído ao setor/turno seguindo esta ordem:

1. **Setor/turno com regular de FOLGA** que tenha a **menor cobertura atual** (ratio `atual/mínimo`)
2. **SetorTurno com maior déficit** que o folguista seja habilitado
3. **Último recurso:** turno com menor cobertura dentre os `turnos_habilitados`

---

## Infraestrutura

| Item | Valor |
|---|---|
| Servidor | `root@177.153.50.29` |
| Projeto | `/root/escalaja/` |
| Serviço | `systemctl restart escalaja` |
| Python/venv | `/root/rota_express/venv/bin/python` |
| Banco | SQLite com WAL mode ativo |
| Deploy | Copiar arquivo local → servidor via SFTP + restart serviço |

---

## Funcionários (referência)

| Setor | Funcionário | Turno | Regime |
|---|---|---|---|
| Bar | WAY | TARDE | 6x1 |
| Copa | ANA PAULA, ISABELLE, PATRICIA | MANHA | — |
| Copa | CELIA, REGINA | TARDE | — |
| Copa | KARINE, TALITA, YANDA | INTERMEDIARIO | — |
| Recepção | ISABELA, JOSE | MANHA | — |
| Recepção | JANAINA | INTERMEDIARIO | — |
| Recepção | AMANDA, LETICIA | TARDE | — |
| Recepção | WILLIAM | NOITE | 6x1 |
| Folguista | AUGUSTO | grupos: Recepção / turnos: MANHA, INT, TARDE, NOITE | — |

> **Atenção:** AUGUSTO não está habilitado para Bar. Bar/TARDE e Bar/NOITE ficam sem cobertura quando WAY folga. Pendente decisão: adicionar Bar ao AUGUSTO ou remover SetorTurno Bar/NOITE e Bar/TARDE.
