from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0012_add_setor_turno'),
    ]

    operations = [
        migrations.AddField(
            model_name='setorturno',
            name='permite_zero',
            field=models.BooleanField(
                default=False,
                help_text='Se marcado, este setor/turno pode ficar com zero funcionários sem gerar alerta'
            ),
        ),
    ]
