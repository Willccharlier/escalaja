from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from datetime import date


# =========================
# TURNO
# =========================
class Turno(models.Model):
    nome = models.CharField(max_length=50, unique=True)
    horario_entrada = models.TimeField()
    horario_saida = models.TimeField()
    minimo_funcionarios = models.IntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ['horario_entrada']

    def __str__(self):
        return self.nome


# =========================
# GRUPO / SETOR
# =========================
class Grupo(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Grupo/Setor'
        verbose_name_plural = 'Grupos/Setores'

    def __str__(self):
        return self.nome


# =========================
# SETOR + TURNO (mínimos)
# =========================
class SetorTurno(models.Model):
    """Define quais turnos um setor opera e o mínimo de funcionários por turno."""
    setor = models.ForeignKey(
        Grupo, on_delete=models.CASCADE,
        related_name='turnos_operados'
    )
    turno = models.ForeignKey(
        'Turno', on_delete=models.CASCADE,
        related_name='setores_operados'
    )
    minimo_funcionarios = models.IntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text='Mínimo de funcionários neste setor neste turno'
    )

    class Meta:
        unique_together = ['setor', 'turno']
        ordering = ['setor__nome', 'turno__horario_entrada']
        verbose_name = 'Setor × Turno'
        verbose_name_plural = 'Setores × Turnos'

    def __str__(self):
        return f'{self.setor.nome} — {self.turno.nome} (mín. {self.minimo_funcionarios})'


# =========================
# FUNCIONÁRIO
# =========================
class Funcionario(models.Model):
    TIPO_CHOICES = [
        ('REGULAR', 'Regular'),
        ('FOLGUISTA', 'Folguista'),
    ]

    REGIME_CHOICES = [
        ('5x2', '5x2 — trabalha 5, folga 2 por semana'),
        ('6x1', '6x1 — trabalha 6, folga 1 por semana'),
    ]

    DIA_SEMANA_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    nome = models.CharField(max_length=200)
    data_nascimento = models.DateField()
    data_admissao = models.DateField()
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='REGULAR')
    turno = models.ForeignKey(
        Turno, on_delete=models.PROTECT,
        null=True, blank=True,
        help_text='Obrigatório para Regular. Folguista não tem turno fixo.'
    )
    grupo = models.ForeignKey(
        Grupo, on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text='Setor/grupo principal do funcionário'
    )
    turnos_habilitados = models.ManyToManyField(
        Turno, blank=True,
        related_name='folguistas_habilitados',
        help_text='Turnos que este folguista pode cobrir'
    )
    grupos_habilitados = models.ManyToManyField(
        Grupo, blank=True,
        related_name='folguistas_habilitados',
        help_text='Setores que este folguista está habilitado a cobrir'
    )
    regime = models.CharField(max_length=3, choices=REGIME_CHOICES, default='6x1')
    folga_fixa_dia = models.IntegerField(
        null=True, blank=True, choices=DIA_SEMANA_CHOICES,
        help_text='Dia fixo de início das folgas (5x2: 2 dias consecutivos a partir deste)'
    )
    ativo = models.BooleanField(default=True)
    ferias_inicio = models.DateField(null=True, blank=True)
    ferias_fim = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def clean(self):
        idade = self.data_admissao.year - self.data_nascimento.year
        if (self.data_admissao.month, self.data_admissao.day) < (
            self.data_nascimento.month,
            self.data_nascimento.day
        ):
            idade -= 1
        if idade < 18:
            raise ValidationError('Funcionário deve ter no mínimo 18 anos.')


# =========================
# FERIADO
# =========================
class Feriado(models.Model):
    TIPO_CHOICES = [
        ('NACIONAL', 'Nacional'),
        ('ESTADUAL', 'Estadual'),
        ('MUNICIPAL', 'Municipal'),
    ]

    nome = models.CharField(max_length=100)
    data = models.DateField(unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)

    class Meta:
        ordering = ['data']

    def __str__(self):
        return f'{self.nome} ({self.data.strftime("%d/%m")})'

    def dia_semana(self):
        return self.data.strftime('%A')

    def eh_dia_util(self):
        return self.data.weekday() < 5


# =========================
# ESCALA
# =========================
class Escala(models.Model):
    mes = models.IntegerField(validators=[MinValueValidator(1)])
    ano = models.IntegerField(validators=[MinValueValidator(2024)])
    data_geracao = models.DateTimeField(auto_now_add=True)
    gerada_com_sucesso = models.BooleanField(default=True)
    observacoes = models.TextField(blank=True)

    class Meta:
        unique_together = ['mes', 'ano']
        ordering = ['-ano', '-mes']

    def __str__(self):
        return f'{self.mes:02d}/{self.ano}'


# =========================
# DIA DA ESCALA
# =========================
class DiaEscala(models.Model):
    SITUACAO_CHOICES = [
        ('TRABALHA', 'Trabalha'),
        ('FOLGA', 'Folga'),
        ('FOLGA_COMPENSADA', 'Folga Compensada'),
        ('FALTA', 'Falta'),
        ('ATESTADO', 'Atestado'),
        ('FERIAS', 'Férias'),
    ]

    escala = models.ForeignKey(Escala, on_delete=models.CASCADE)
    funcionario = models.ForeignKey(Funcionario, on_delete=models.PROTECT)
    data = models.DateField()
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES)
    turno_coberto = models.ForeignKey(
        Turno, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dias_cobertos',
        help_text='Turno coberto pelo folguista neste dia'
    )
    setor_coberto = models.ForeignKey(
        'Grupo', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dias_cobertos',
        help_text='Setor coberto pelo folguista neste dia'
    )

    class Meta:
        unique_together = ['escala', 'funcionario', 'data']
        ordering = ['data']

    def __str__(self):
        return f'{self.funcionario} - {self.data}'


# =========================
# CONFIGURAÇÃO DO SISTEMA
# =========================
class ConfiguracaoSistema(models.Model):
    REGIME_CHOICES = [
        ('5x2', 'Apenas 5x2'),
        ('6x1', 'Apenas 6x1'),
        ('AMBOS', 'Ambos os regimes'),
    ]

    # Regra: sem folgas consecutivas
    consecutivas_ativo = models.BooleanField(default=True)
    consecutivas_regime = models.CharField(max_length=5, choices=REGIME_CHOICES, default='AMBOS')

    # Regra: priorizar domingo (sempre só para 6x1 conforme definição do gestor)
    domingo_ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Configuração do Sistema'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return 'Configurações do Sistema'


