from decimal import Decimal
from django.db import migrations, models


def seed_rates(apps, schema_editor):
    CurrencyRate = apps.get_model('hbl_core', 'CurrencyRate')
    PlatformConfig = apps.get_model('hbl_core', 'PlatformConfig')
    config = PlatformConfig.objects.get(pk=1) if PlatformConfig.objects.filter(pk=1).exists() else None
    base = (getattr(config, 'base_currency_code', None) or 'NIO').upper()
    usd_rate = Decimal(str(getattr(config, 'exchange_rate_usd_nio', Decimal('36.62')) or Decimal('36.62')))
    seed = {
        base: (base, Decimal('1.0')),
        'USD': ('US Dollar', usd_rate if base == 'NIO' else Decimal('1.0')),
        'NIO': ('Córdoba nicaragüense', Decimal('1.0') if base == 'NIO' else (Decimal('1.0') / usd_rate)),
        'USDT': ('Tether USD', usd_rate if base == 'NIO' else Decimal('1.0')),
    }
    for code, (name, rate) in seed.items():
        CurrencyRate.objects.update_or_create(code=code, defaults={'name': name, 'rate_to_base': rate, 'active': True})


class Migration(migrations.Migration):
    dependencies = [('hbl_core', '0004_ultra_polish_logic')]
    operations = [
        migrations.AddField(
            model_name='platformconfig',
            name='listen_verification_seconds',
            field=models.PositiveSmallIntegerField(default=10, help_text='Segundos efectivos requeridos por canción para validar la tarea.'),
        ),
        migrations.CreateModel(
            name='CurrencyRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=3, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('symbol', models.CharField(blank=True, max_length=12)),
                ('rate_to_base', models.DecimalField(decimal_places=10, default=Decimal('1.0000000000'), max_digits=24)),
                ('active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['code']},
        ),
        migrations.RunPython(seed_rates, migrations.RunPython.noop),
    ]
