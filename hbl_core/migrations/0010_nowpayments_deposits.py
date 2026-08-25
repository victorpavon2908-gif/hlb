from decimal import Decimal

from django.db import migrations, models


def configure_nowpayments_methods(apps, schema_editor):
    PaymentMethod = apps.get_model("hbl_core", "PaymentMethod")
    PaymentMethod.objects.filter(kind__in=("usdt_trc20", "usdt_bep20")).update(
        destination="",
        require_txid=False,
        require_proof=False,
    )


class Migration(migrations.Migration):
    dependencies = [("hbl_core", "0009_crypto_only_payment_channels")]

    operations = [
        migrations.AddField(
            model_name="deposit",
            name="provider",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name="deposit",
            name="provider_payment_id",
            field=models.CharField(blank=True, db_index=True, max_length=80),
        ),
        migrations.AddField(
            model_name="deposit",
            name="provider_status",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="deposit",
            name="provider_price_amount",
            field=models.DecimalField(decimal_places=8, default=Decimal("0.00000000"), max_digits=18),
        ),
        migrations.AddField(
            model_name="deposit",
            name="pay_address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddConstraint(
            model_name="deposit",
            constraint=models.UniqueConstraint(
                condition=~models.Q(provider_payment_id=""),
                fields=("provider", "provider_payment_id"),
                name="uniq_hbl_provider_payment_id",
            ),
        ),
        migrations.RunPython(configure_nowpayments_methods, migrations.RunPython.noop),
    ]
