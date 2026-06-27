from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0002_tipoocorrencia_alter_diaescala_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='turno',
            name='regime',
            field=models.CharField(
                choices=[('5x2', '5x2 — trabalha 5, folga 2 por semana'), ('6x1', '6x1 — trabalha 6, folga 1 por semana')],
                default='5x2',
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name='funcionario',
            name='ferias_inicio',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='funcionario',
            name='ferias_fim',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='diaescala',
            name='situacao',
            field=models.CharField(
                choices=[
                    ('TRABALHA', 'Trabalha'),
                    ('FOLGA', 'Folga'),
                    ('FOLGA_COMPENSADA', 'Folga Compensada'),
                    ('FALTA', 'Falta'),
                    ('ATESTADO', 'Atestado'),
                    ('FERIAS', 'Férias'),
                ],
                max_length=20,
            ),
        ),
    ]
