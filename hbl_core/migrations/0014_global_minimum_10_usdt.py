from decimal import Decimal

from django.db import migrations


CRYPTO_KINDS = ("usdt_trc20", "usdt_bep20", "crypto_other")
GLOBAL_MIN_USDT = Decimal("10.00000000")


def set_global_minimum(apps, schema_editor):
    PlatformConfig = apps.get_model("hbl_core", "PlatformConfig")
    PaymentMethod = apps.get_model("hbl_core", "PaymentMethod")

    PlatformConfig.objects.filter(pk=1).update(
        minimum_deposit_usd=Decimal("10.00"),
    )
    PaymentMethod.objects.filter(kind__in=CRYPTO_KINDS).update(
        min_amount=GLOBAL_MIN_USDT,
    )


def noop_reverse(apps, schema_editor):
    # La política de 10 USDT es intencionalmente global; no restauramos
    # mínimos históricos distintos al revertir esta migración.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hbl_core", "0013_deposit_sender_network_fee_estimate_and_more"),
    ]

    operations = [
        migrations.RunPython(set_global_minimum, noop_reverse),
    ]
