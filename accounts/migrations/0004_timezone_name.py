from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0003_preferred_currency')]
    operations = [
        migrations.AddField(
            model_name='user',
            name='timezone_name',
            field=models.CharField(blank=True, default='UTC', help_text='Zona horaria IANA detectada en el dispositivo, por ejemplo America/Managua.', max_length=64),
        ),
    ]
