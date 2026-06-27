from django.core.management.base import BaseCommand
from escala.models import Turno, Funcionario, Feriado
from datetime import date, time


class Command(BaseCommand):
    help = 'Popula o banco com dados de exemplo para testes'

    def handle(self, *args, **options):
        self.stdout.write('🔄 Populando banco de dados com dados de exemplo...\n')
        
        # 1. Criar Turnos
        self.stdout.write('📋 Criando turnos...')
        
        turno_manha, created = Turno.objects.get_or_create(
            nome='MANHA',
            defaults={
                'horario_entrada': time(6, 0),
                'horario_saida': time(14, 0),
                'minimo_funcionarios': 3
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✓ {turno_manha}'))
        
        turno_tarde, created = Turno.objects.get_or_create(
            nome='TARDE',
            defaults={
                'horario_entrada': time(14, 0),
                'horario_saida': time(22, 0),
                'minimo_funcionarios': 2
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✓ {turno_tarde}'))
        
        turno_noite, created = Turno.objects.get_or_create(
            nome='NOITE',
            defaults={
                'horario_entrada': time(22, 0),
                'horario_saida': time(6, 0),
                'minimo_funcionarios': 2
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✓ {turno_noite}'))
        
        # 2. Criar Funcionários do turno MANHÃ (5 fixos)
        self.stdout.write('\n👥 Criando funcionários do turno MANHÃ...')
        
        funcionarios_manha = [
            {'nome': 'João Silva', 'data_nasc': date(1990, 3, 15)},
            {'nome': 'Maria Santos', 'data_nasc': date(1985, 7, 22)},
            {'nome': 'Pedro Oliveira', 'data_nasc': date(1992, 11, 8)},
            {'nome': 'Ana Costa', 'data_nasc': date(1988, 5, 30)},
            {'nome': 'Carlos Souza', 'data_nasc': date(1995, 9, 12)},
        ]
        
        for func_data in funcionarios_manha:
            func, created = Funcionario.objects.get_or_create(
                nome=func_data['nome'],
                defaults={
                    'data_nascimento': func_data['data_nasc'],
                    'data_admissao': date(2023, 1, 10),
                    'tipo': 'REGULAR',
                    'turno': turno_manha,
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # 3. Criar Funcionários do turno TARDE (3 regulares)
        self.stdout.write('\n👥 Criando funcionários do turno TARDE...')
        
        funcionarios_tarde = [
            {'nome': 'Lucas Ferreira', 'data_nasc': date(1991, 2, 18)},
            {'nome': 'Juliana Lima', 'data_nasc': date(1987, 12, 5)},
            {'nome': 'Roberto Alves', 'data_nasc': date(1993, 6, 25)},
        ]
        
        for func_data in funcionarios_tarde:
            func, created = Funcionario.objects.get_or_create(
                nome=func_data['nome'],
                defaults={
                    'data_nascimento': func_data['data_nasc'],
                    'data_admissao': date(2023, 1, 10),
                    'tipo': 'REGULAR',
                    'turno': turno_tarde,
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # 4. Criar Funcionários do turno NOITE (3 regulares)
        self.stdout.write('\n👥 Criando funcionários do turno NOITE...')
        
        funcionarios_noite = [
            {'nome': 'Marcos Pereira', 'data_nasc': date(1989, 4, 10)},
            {'nome': 'Fernanda Rocha', 'data_nasc': date(1994, 8, 20)},
            {'nome': 'Paulo Mendes', 'data_nasc': date(1986, 10, 15)},
        ]
        
        for func_data in funcionarios_noite:
            func, created = Funcionario.objects.get_or_create(
                nome=func_data['nome'],
                defaults={
                    'data_nascimento': func_data['data_nasc'],
                    'data_admissao': date(2023, 1, 10),
                    'tipo': 'REGULAR',
                    'turno': turno_noite,
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # 5. Criar Folguistas
        self.stdout.write('\n🔄 Criando folguistas...')
        
        folguistas = [
            {'nome': 'Ricardo Folguista', 'turno': turno_manha, 'data_nasc': date(1992, 1, 5)},
            {'nome': 'Sandra Folguista', 'turno': turno_tarde, 'data_nasc': date(1990, 3, 12)},
            {'nome': 'José Folguista', 'turno': turno_noite, 'data_nasc': date(1988, 7, 8)},
        ]
        
        for folg_data in folguistas:
            folg, created = Funcionario.objects.get_or_create(
                nome=folg_data['nome'],
                defaults={
                    'data_nascimento': folg_data['data_nasc'],
                    'data_admissao': date(2023, 1, 10),
                    'tipo': 'FOLGUISTA',
                    'turno': folg_data['turno'],
                    'ativo': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {folg.nome}'))
        
        # 6. Criar Feriados de 2025
        self.stdout.write('\n🎉 Criando feriados de 2025...')
        
        feriados_2025 = [
            {'nome': 'Ano Novo', 'data': date(2025, 1, 1), 'tipo': 'NACIONAL'},
            {'nome': 'Carnaval', 'data': date(2025, 3, 4), 'tipo': 'NACIONAL'},
            {'nome': 'Sexta-feira Santa', 'data': date(2025, 4, 18), 'tipo': 'NACIONAL'},
            {'nome': 'Tiradentes', 'data': date(2025, 4, 21), 'tipo': 'NACIONAL'},
            {'nome': 'Dia do Trabalho', 'data': date(2025, 5, 1), 'tipo': 'NACIONAL'},
            {'nome': 'Corpus Christi', 'data': date(2025, 6, 19), 'tipo': 'NACIONAL'},
            {'nome': 'Independência', 'data': date(2025, 9, 7), 'tipo': 'NACIONAL'},
            {'nome': 'Nossa Senhora Aparecida', 'data': date(2025, 10, 12), 'tipo': 'NACIONAL'},
            {'nome': 'Finados', 'data': date(2025, 11, 2), 'tipo': 'NACIONAL'},
            {'nome': 'Proclamação da República', 'data': date(2025, 11, 15), 'tipo': 'NACIONAL'},
            {'nome': 'Consciência Negra', 'data': date(2025, 11, 20), 'tipo': 'NACIONAL'},
            {'nome': 'Natal', 'data': date(2025, 12, 25), 'tipo': 'NACIONAL'},
        ]
        
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
                eh_util = '📅 Dia útil' if feriado.eh_dia_util() else '📆 Final de semana'
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ {feriado.nome} - {feriado.data.strftime("%d/%m")} ({dia_semana}) - {eh_util}'
                    )
                )
        
        # Resumo final
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('\n✅ Banco de dados populado com sucesso!\n'))
        self.stdout.write(f'📊 Total de turnos: {Turno.objects.count()}')
        self.stdout.write(f'👥 Total de funcionários regulares: {Funcionario.objects.filter(tipo="REGULAR").count()}')
        self.stdout.write(f'🔄 Total de folguistas: {Funcionario.objects.filter(tipo="FOLGUISTA").count()}')
        self.stdout.write(f'🎉 Total de feriados: {Feriado.objects.count()}')
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('\n💡 Próximo passo: python manage.py gerar_escala --mes 3 --ano 2025\n')