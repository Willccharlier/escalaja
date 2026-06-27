from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0007_configuracaosistema'),
    ]

    operations = [
        migrations.AddField(
            model_name='funcionario',
            name='folga_fixa_dia',
            field=models.IntegerField(
                blank=True,
                null=True,
                choices=[
                    (0, 'Segunda-feira'),
                    (1, 'Terça-feira'),
                    (2, 'Quarta-feira'),
                    (3, 'Quinta-feira'),
                    (4, 'Sexta-feira'),
                    (5, 'Sábado'),
                    (6, 'Domingo'),
                ],
                help_text='Dia fixo de início das folgas (5x2: 2 dias consecutivos a partir deste)',
            ),
        ),
    ]
