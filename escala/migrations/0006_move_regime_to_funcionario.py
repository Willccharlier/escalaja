from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0005_merge_20260616_1906'),
    ]

    operations = [
        migrations.AddField(
            model_name='funcionario',
            name='regime',
            field=models.CharField(
                choices=[('5x2', '5x2 — trabalha 5, folga 2 por semana'), ('6x1', '6x1 — trabalha 6, folga 1 por semana')],
                default='5x2',
                max_length=3,
            ),
        ),
        migrations.RemoveField(
            model_name='turno',
            name='regime',
        ),
    ]
