from django.core.management.base import BaseCommand
from escala.models import Feriado
from datetime import date


class Command(BaseCommand):
    help = 'Popula feriados nacionais de 2025'

    def handle(self, *args, **options):
        self.stdout.write('🎉 Populando feriados de 2025...\n')
        
        feriados_2025 = [
            {'nome': 'Ano Novo', 'data': date(2025, 1, 1), 'tipo': 'NACIONAL'},
            {'nome': 'Carnaval', 'data': date(2025, 3, 4), 'tipo': 'NACIONAL'},
            {'nome': 'Sexta-feira Santa', 'data': date(2025, 4, 18), 'tipo': 'NACIONAL'},
            {'nome': 'Tiradentes', 'data': date(2025, 4, 21), 'tipo': 'NACIONAL'},
            {'nome': 'Dia do Trabalho', 'data': date(2025, 5, 1), 'tipo': 'NACIONAL'},
            {'nome': 'Corpus Christi', 'data': date(2025, 6, 19), 'tipo': 'NACIONAL'},
            {'nome': 'Independência do Brasil', 'data': date(2025, 9, 7), 'tipo': 'NACIONAL'},
            {'nome': 'Nossa Senhora Aparecida', 'data': date(2025, 10, 12), 'tipo': 'NACIONAL'},
            {'nome': 'Finados', 'data': date(2025, 11, 2), 'tipo': 'NACIONAL'},
            {'nome': 'Proclamação da República', 'data': date(2025, 11, 15), 'tipo': 'NACIONAL'},
            {'nome': 'Consciência Negra', 'data': date(2025, 11, 20), 'tipo': 'NACIONAL'},
            {'nome': 'Natal', 'data': date(2025, 12, 25), 'tipo': 'NACIONAL'},
        ]
        
        criados = 0
        existentes = 0
        
        for fer_data in feriados_2025:
            feriado, created = Feriado.objects.get_or_create(
                data=fer_data['data'],
                defaults={
                    'nome': fer_data['nome'],
                    'tipo': fer_data['tipo']
                }
            )
            
            if created:
                dia_semana = feriado.dia_semana()
                eh_util = '📅 Dia útil' if feriado.eh_dia_util() else '📆 Fim de semana'
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ {feriado.nome} - {feriado.data.strftime("%d/%m")} ({dia_semana}) - {eh_util}'
                    )
                )
                criados += 1
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠️  {fer_data["nome"]} - já existe'
                    )
                )
                existentes += 1
        
        # Resumo
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(f'\n✅ Operação concluída!'))
        self.stdout.write(f'📊 Feriados criados: {criados}')
        self.stdout.write(f'⚠️  Já existentes: {existentes}')
        self.stdout.write(f'🎉 Total de feriados em 2025: {Feriado.objects.filter(data__year=2025).count()}')
        self.stdout.write('\n' + '=' * 70 + '\n')