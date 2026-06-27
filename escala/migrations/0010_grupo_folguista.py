from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('escala', '0009_remove_ocorrencias'),
    ]

    operations = [
        # 1. Criar Grupo
        migrations.CreateModel(
            name='Grupo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100, unique=True)),
            ],
            options={
                'verbose_name': 'Grupo/Setor',
                'verbose_name_plural': 'Grupos/Setores',
                'ordering': ['nome'],
            },
        ),

        # 2. Tornar turno nullable
        migrations.AlterField(
            model_name='funcionario',
            name='turno',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='escala.turno',
                help_text='Obrigatório para Regular. Folguista não tem turno fixo.'
            ),
        ),

        # 3. Adicionar grupo principal
        migrations.AddField(
            model_name='funcionario',
            name='grupo',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='escala.grupo',
                help_text='Setor/grupo principal do funcionário'
            ),
        ),

        # 4. Turnos habilitados (M2M folguista → turno)
        migrations.AddField(
            model_name='funcionario',
            name='turnos_habilitados',
            field=models.ManyToManyField(
                blank=True,
                related_name='folguistas_habilitados',
                to='escala.turno',
                help_text='Turnos que este folguista pode cobrir'
            ),
        ),

        # 5. Grupos habilitados (M2M folguista → grupo)
        migrations.AddField(
            model_name='funcionario',
            name='grupos_habilitados',
            field=models.ManyToManyField(
                blank=True,
                related_name='folguistas_habilitados',
                to='escala.grupo',
                help_text='Setores que este folguista está habilitado a cobrir'
            ),
        ),

        # 6. turno_coberto no DiaEscala
        migrations.AddField(
            model_name='diaescala',
            name='turno_coberto',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='dias_cobertos',
                to='escala.turno',
                help_text='Turno coberto pelo folguista neste dia'
            ),
        ),
    ]
