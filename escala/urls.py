from django.urls import path
from . import views

app_name = 'escala'

urlpatterns = [
    # Autenticação
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Páginas protegidas
    path('', views.dashboard, name='dashboard'),
    
    # Escalas
    path('escalas/', views.escala_lista, name='escala_lista'),
    path('escalas/<int:pk>/', views.escala_detalhe, name='escala_detalhe'),
    path('gerar/', views.gerar_escala_view, name='gerar_escala'),
    path('trocar-folga/', views.trocar_folga, name='trocar_folga'),
    path('alterar-dia/', views.alterar_situacao_dia, name='alterar_situacao_dia'),
    path('alterar-turno-coberto/', views.alterar_turno_coberto, name='alterar_turno_coberto'),
    path('escalas/<int:pk>/revalidar/', views.revalidar_escala, name='revalidar_escala'),
    path('escalas/<int:pk>/auto-corrigir/', views.auto_corrigir_escala, name='auto_corrigir_escala'),
    path('escalas/<int:pk>/exportar-excel/', views.exportar_escala_excel, name='exportar_escala_excel'),
    
    # Funcionários
    path('funcionarios/', views.funcionario_lista, name='funcionario_lista'),
    path('funcionarios/novo/', views.funcionario_novo, name='funcionario_novo'),
    path('funcionarios/<int:pk>/editar/', views.funcionario_editar, name='funcionario_editar'),
    path('funcionarios/<int:pk>/deletar/', views.funcionario_deletar, name='funcionario_deletar'),
    
    
    # Turnos
    path('turnos/', views.turno_lista, name='turno_lista'),
    path('turnos/novo/', views.turno_novo, name='turno_novo'),
    path('turnos/<int:pk>/editar/', views.turno_editar, name='turno_editar'),
    path('turnos/<int:pk>/deletar/', views.turno_deletar, name='turno_deletar'),
    
    # Feriados (NOVO)
    path('feriados/', views.feriado_lista, name='feriado_lista'),
    path('feriados/novo/', views.feriado_novo, name='feriado_novo'),
    path('feriados/<int:pk>/editar/', views.feriado_editar, name='feriado_editar'),
    path('feriados/<int:pk>/deletar/', views.feriado_deletar, name='feriado_deletar'),
    
    # Calendário
    path('calendario/', views.calendario_view, name='calendario'),

    # Grupos/Setores
    path('grupos/', views.grupo_lista, name='grupo_lista'),
    path('grupos/novo/', views.grupo_novo, name='grupo_novo'),
    path('grupos/<int:pk>/editar/', views.grupo_editar, name='grupo_editar'),
    path('grupos/<int:pk>/deletar/', views.grupo_deletar, name='grupo_deletar'),

    # Configurações
    path('configuracoes/', views.configuracao_view, name='configuracao'),

    # Portal do funcionário
    path('funcionario/', views.portal_funcionario, name='portal_funcionario'),
    path('funcionario/logout/', views.logout_funcionario, name='logout_funcionario'),
    path('funcionarios/<int:pk>/resetar-senha/', views.resetar_senha_funcionario, name='resetar_senha_funcionario'),

    path('funcionarios/<int:pk>/logs/', views.logs_acesso_funcionario, name='logs_acesso_funcionario'),

    # Ocorrências
    path('funcionario/ocorrencia/', views.registrar_ocorrencia, name='registrar_ocorrencia'),
    path('funcionario/minhas-ocorrencias/', views.minhas_ocorrencias, name='minhas_ocorrencias'),
    path('ocorrencias/', views.ocorrencias_lista, name='ocorrencias_lista'),
    path('ocorrencias/api/count/', views.api_ocorrencias_count, name='api_ocorrencias_count'),
    path('ocorrencias/api/meu-status/', views.api_minhas_ocorrencias_status, name='api_minhas_ocorrencias_status'),
    path('ocorrencias/<int:pk>/vista/', views.marcar_ocorrencia_vista, name='marcar_ocorrencia_vista'),
    path('funcionario/minha-escala/', views.minha_escala, name='minha_escala'),
    path('funcionarios/<int:pk>/qrcode/', views.gerar_qrcode_funcionario, name='qrcode_funcionario'),
]