from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0008_funcionario_folga_fixa_dia'),
    ]

    operations = [
        migrations.DeleteModel(name='Ocorrencia'),
        migrations.DeleteModel(name='TipoOcorrencia'),
    ]
