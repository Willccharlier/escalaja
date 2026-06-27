from django.core.management.base import BaseCommand
from escala.models import Funcionario
from datetime import date


class Command(BaseCommand):
    help = 'Apaga todos funcionários e cria nova configuração'

    def handle(self, *args, **options):
        self.stdout.write('🗑️  Apagando todos os funcionários...')
        
        # Deletar todos
        total = Funcionario.objects.count()
        Funcionario.objects.all().delete()
        self.stdout.write(self.style.WARNING(f'  ✓ {total} funcionários removidos'))
        
        # Buscar turnos
        from escala.models import Turno
        turno_manha = Turno.objects.get(nome='MANHA')
        turno_tarde = Turno.objects.get(nome='TARDE')
        turno_noite = Turno.objects.get(nome='NOITE')
        
        self.stdout.write('\n👥 Criando novos funcionários...\n')
        
        # 5 MANHÃ
        self.stdout.write('🌅 Turno MANHÃ (5 funcionários):')
        funcionarios_manha = [
            {'nome': 'João Silva', 'data_nasc': date(1990, 3, 15)},
            {'nome': 'Maria Santos', 'data_nasc': date(1985, 7, 22)},
            {'nome': 'Pedro Oliveira', 'data_nasc': date(1992, 11, 8)},
            {'nome': 'Ana Costa', 'data_nasc': date(1988, 5, 30)},
            {'nome': 'Carlos Souza', 'data_nasc': date(1995, 9, 12)},
        ]
        
        for func_data in funcionarios_manha:
            func = Funcionario.objects.create(
                nome=func_data['nome'],
                data_nascimento=func_data['data_nasc'],
                data_admissao=date(2023, 1, 10),
                tipo='REGULAR',
                turno=turno_manha,
                ativo=True
            )
            self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # 4 TARDE
        self.stdout.write('\n☀️  Turno TARDE (4 funcionários):')
        funcionarios_tarde = [
            {'nome': 'Lucas Ferreira', 'data_nasc': date(1991, 2, 18)},
            {'nome': 'Juliana Lima', 'data_nasc': date(1987, 12, 5)},
            {'nome': 'Roberto Alves', 'data_nasc': date(1993, 6, 25)},
            {'nome': 'Renata Silva', 'data_nasc': date(1994, 8, 20)},
        ]
        
        for func_data in funcionarios_tarde:
            func = Funcionario.objects.create(
                nome=func_data['nome'],
                data_nascimento=func_data['data_nasc'],
                data_admissao=date(2023, 1, 10),
                tipo='REGULAR',
                turno=turno_tarde,
                ativo=True
            )
            self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # 4 NOITE
        self.stdout.write('\n🌙 Turno NOITE (4 funcionários):')
        funcionarios_noite = [
            {'nome': 'Marcos Pereira', 'data_nasc': date(1989, 4, 10)},
            {'nome': 'Fernanda Rocha', 'data_nasc': date(1990, 3, 12)},
            {'nome': 'Paulo Mendes', 'data_nasc': date(1986, 10, 15)},
            {'nome': 'Carla Santos', 'data_nasc': date(1992, 1, 5)},
        ]
        
        for func_data in funcionarios_noite:
            func = Funcionario.objects.create(
                nome=func_data['nome'],
                data_nascimento=func_data['data_nasc'],
                data_admissao=date(2023, 1, 10),
                tipo='REGULAR',
                turno=turno_noite,
                ativo=True
            )
            self.stdout.write(self.style.SUCCESS(f'  ✓ {func.nome}'))
        
        # Resumo
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS('\n✅ Funcionários resetados com sucesso!\n'))
        self.stdout.write(f'🌅 MANHÃ: {Funcionario.objects.filter(turno=turno_manha).count()} funcionários (mínimo: 3)')
        self.stdout.write(f'☀️  TARDE: {Funcionario.objects.filter(turno=turno_tarde).count()} funcionários (mínimo: 2)')
        self.stdout.write(f'🌙 NOITE: {Funcionario.objects.filter(turno=turno_noite).count()} funcionários (mínimo: 2)')
        self.stdout.write(f'\n📊 TOTAL: {Funcionario.objects.count()} funcionários')
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write('\n💡 Próximo passo: python manage.py gerar_escala --mes 3 --ano 2025 --force\n')
        