from decimal import Decimal
from django.db import migrations, models


def configure_existing_methods(apps, schema_editor):
    WithdrawalMethod = apps.get_model("hbl_core", "WithdrawalMethod")
    mapping = {
        "bank": {"currency_mode": "user_local", "identifier_type": "bank", "identifier_placeholder": "Ej. número de cuenta o IBAN", "identifier_help": "Escribe la cuenta exactamente como aparece en tu banco."},
        "binance-id": {"currency_mode": "fixed", "identifier_type": "binance_id", "identifier_placeholder": "Ej. 123456789", "identifier_help": "Solo el Binance Pay ID numérico del destinatario."},
        "usdt-trc20": {"currency_mode": "fixed", "identifier_type": "trc20", "identifier_placeholder": "Ej. TAbc...", "identifier_help": "Dirección USDT en red TRON (TRC20). Verifica la red antes de guardar."},
        "usdt-bep20": {"currency_mode": "fixed", "identifier_type": "bep20", "identifier_placeholder": "Ej. 0xabc...", "identifier_help": "Dirección USDT en BNB Smart Chain (BEP20/EVM). Verifica la red antes de guardar."},
    }
    for slug, values in mapping.items():
        WithdrawalMethod.objects.filter(slug=slug).update(**values)


class Migration(migrations.Migration):
    dependencies = [('hbl_core', '0005_currency_rates_listen_seconds')]
    operations = [
        migrations.AddField(model_name='withdrawal', name='base_currency', field=models.CharField(default='NIO', max_length=12)),
        migrations.AddField(model_name='withdrawal', name='requested_amount', field=models.DecimalField(decimal_places=8, default=Decimal('0.00000000'), max_digits=18)),
        migrations.AddField(model_name='withdrawal', name='requested_currency', field=models.CharField(default='NIO', max_length=12)),
        migrations.AddField(model_name='withdrawal', name='payout_amount', field=models.DecimalField(decimal_places=8, default=Decimal('0.00000000'), max_digits=18)),
        migrations.AddField(model_name='withdrawal', name='payout_currency', field=models.CharField(default='NIO', max_length=12)),
        migrations.AddField(model_name='withdrawal', name='requested_rate_to_base', field=models.DecimalField(decimal_places=10, default=Decimal('1.0000000000'), max_digits=24)),
        migrations.AddField(model_name='withdrawal', name='payout_rate_to_base', field=models.DecimalField(decimal_places=10, default=Decimal('1.0000000000'), max_digits=24)),
        migrations.AddField(model_name='withdrawalmethod', name='currency_mode', field=models.CharField(choices=[('fixed', 'Moneda fija del método'), ('user_local', 'Moneda local del usuario')], default='fixed', max_length=16)),
        migrations.AddField(model_name='withdrawalmethod', name='country', field=models.CharField(blank=True, default='', help_text='Vacío = disponible en todos los países.', max_length=2)),
        migrations.AddField(model_name='withdrawalmethod', name='identifier_type', field=models.CharField(choices=[('bank', 'Cuenta bancaria / IBAN'), ('binance_id', 'Binance Pay ID'), ('trc20', 'Wallet TRC20'), ('bep20', 'Wallet BEP20 / EVM'), ('email', 'Correo electrónico'), ('phone', 'Teléfono internacional'), ('custom', 'Texto libre')], default='custom', max_length=20)),
        migrations.AddField(model_name='withdrawalmethod', name='identifier_placeholder', field=models.CharField(blank=True, default='', max_length=120)),
        migrations.AddField(model_name='withdrawalmethod', name='identifier_help', field=models.CharField(blank=True, default='', max_length=220)),
        migrations.RunPython(configure_existing_methods, migrations.RunPython.noop),
    ]
