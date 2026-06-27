from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0006_move_regime_to_funcionario'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoSistema',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('consecutivas_ativo', models.BooleanField(default=True)),
                ('consecutivas_regime', models.CharField(
                    choices=[('5x2', 'Apenas 5x2'), ('6x1', 'Apenas 6x1'), ('AMBOS', 'Ambos os regimes')],
                    default='AMBOS',
                    max_length=5,
                )),
                ('domingo_ativo', models.BooleanField(default=True)),
            ],
            options={'verbose_name': 'Configuração do Sistema'},
        ),
    ]
