from django.contrib import admin
from .models import Turno, Funcionario, Feriado, Escala, DiaEscala, Grupo, SetorTurno


class SetorTurnoInline(admin.TabularInline):
    model = SetorTurno
    extra = 1
    fields = ['turno', 'minimo_funcionarios']


@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    list_display = ['nome']
    search_fields = ['nome']
    inlines = [SetorTurnoInline]


@admin.register(SetorTurno)
class SetorTurnoAdmin(admin.ModelAdmin):
    list_display = ['setor', 'turno', 'minimo_funcionarios']
    list_filter = ['setor', 'turno']


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'horario_entrada', 'horario_saida', 'minimo_funcionarios']
    list_filter = ['nome']
    search_fields = ['nome']


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'turno', 'regime', 'data_nascimento', 'data_admissao', 'ativo']
    list_filter = ['tipo', 'turno', 'regime', 'ativo']
    search_fields = ['nome']
    date_hierarchy = 'data_admissao'


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'data', 'dia_semana_display', 'tipo', 'eh_dia_util']
    list_filter = ['tipo', 'data']
    search_fields = ['nome']
    date_hierarchy = 'data'

    def dia_semana_display(self, obj):
        return obj.dia_semana()
    dia_semana_display.short_description = 'Dia da Semana'


class DiaEscalaInline(admin.TabularInline):
    model = DiaEscala
    extra = 0
    can_delete = False
    fields = ['data', 'funcionario', 'situacao']
    readonly_fields = ['data', 'funcionario', 'situacao']


@admin.register(Escala)
class EscalaAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'data_geracao', 'gerada_com_sucesso']
    list_filter = ['ano', 'mes', 'gerada_com_sucesso']
    readonly_fields = ['data_geracao']
    inlines = [DiaEscalaInline]


@admin.register(DiaEscala)
class DiaEscalaAdmin(admin.ModelAdmin):
    list_display = ['data', 'funcionario', 'situacao', 'escala']
    list_filter = ['situacao', 'data', 'funcionario__turno']
    search_fields = ['funcionario__nome']
    date_hierarchy = 'data'
