from django.core.management.base import BaseCommand
from escala.services import GeradorEscala
from escala.models import Escala
from datetime import date


class Command(BaseCommand):
    help = 'Gera escala mensal automaticamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mes',
            type=int,
            help='Mês (1-12). Se não informado, usa o mês atual',
        )
        parser.add_argument(
            '--ano',
            type=int,
            help='Ano. Se não informado, usa o ano atual',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Força regerar escala mesmo se já existir',
        )

    def handle(self, *args, **options):
        # Definir mês e ano
        hoje = date.today()
        mes = options['mes'] or hoje.month
        ano = options['ano'] or hoje.year
        
        # Validar mês
        if mes < 1 or mes > 12:
            self.stdout.write(self.style.ERROR('❌ Mês inválido! Use valores entre 1 e 12.'))
            return
        
        # Verificar se já existe escala
        escala_existente = Escala.objects.filter(mes=mes, ano=ano).first()
        
        if escala_existente and not options['force']:
            self.stdout.write(
                self.style.WARNING(
                    f'⚠️  Já existe escala para {mes}/{ano}. '
                    f'Use --force para regerar.'
                )
            )
            return
        
        # Deletar escala existente se --force
        if escala_existente and options['force']:
            escala_existente.delete()
            self.stdout.write(
                self.style.WARNING(f'🗑️  Escala anterior de {mes}/{ano} removida.')
            )
        
        # Gerar escala
        self.stdout.write(f'🔄 Gerando escala para {mes:02d}/{ano}...\n')
        
        gerador = GeradorEscala(mes, ano)
        sucesso, escala, alertas = gerador.gerar()
        
        # Exibir resultado
        self.stdout.write('')
        self.stdout.write('=' * 70)
        
        for alerta in alertas:
            if '✅' in alerta:
                self.stdout.write(self.style.SUCCESS(alerta))
            elif '❌' in alerta:
                self.stdout.write(self.style.ERROR(alerta))
            else:
                self.stdout.write(self.style.WARNING(alerta))
        
        self.stdout.write('=' * 70)
        
        if sucesso:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Escala gerada com sucesso! ID: {escala.id}'
                )
            )
            self.stdout.write(
                f'\n📋 Visualize no admin: http://127.0.0.1:8000/admin/escala/escala/{escala.id}/change/'
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    '\n❌ Escala gerada com problemas! '
                    'Revise os alertas acima e faça ajustes manuais.'
                )
            )
            if escala:
                self.stdout.write(
                    f'\n📋 Visualize no admin: http://127.0.0.1:8000/admin/escala/escala/{escala.id}/change/'
                )