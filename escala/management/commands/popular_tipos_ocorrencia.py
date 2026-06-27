from django.core.management.base import BaseCommand
from escala.models import TipoOcorrencia

class Command(BaseCommand):
    help = 'Cria tipos padrão de ocorrência'

    def handle(self, *args, **options):
        tipos = [
            # Controle de Acesso
            ('Tentativa de entrada sem autorização', 'ACESSO', 'CRITICA'),
            ('Acesso fora do horário permitido', 'ACESSO', 'ATENCAO'),
            ('Portão aberto indevidamente', 'ACESSO', 'ATENCAO'),

            # Presença Suspeita
            ('Pessoa em local restrito', 'SUSPEITA', 'CRITICA'),
            ('Indivíduo em atitude suspeita', 'SUSPEITA', 'ATENCAO'),
            ('Veículo suspeito', 'SUSPEITA', 'ATENCAO'),

            # Tentativas
            ('Tentativa de invasão', 'TENTATIVA', 'CRITICA'),
            ('Tentativa de furto', 'TENTATIVA', 'CRITICA'),
            ('Indício de arrombamento', 'TENTATIVA', 'CRITICA'),

            # Ronda
            ('Ronda realizada sem alteração', 'RONDA', 'INFO'),
            ('Ronda com ponto de atenção', 'RONDA', 'ATENCAO'),
        ]

        for nome, categoria, gravidade in tipos:
            TipoOcorrencia.objects.get_or_create(
                nome=nome,
                defaults={
                    'categoria': categoria,
                    'gravidade': gravidade,
                    'ativo': True
                }
            )

        self.stdout.write(self.style.SUCCESS('Tipos de ocorrência criados.'))
