from decimal import Decimal

from django.db import migrations


ALLOWED_SLUGS = ("usdt-trc20", "usdt-bep20")


def enforce_crypto_withdrawals(apps, schema_editor):
    WithdrawalMethod = apps.get_model("hbl_core", "WithdrawalMethod")
    CurrencyRate = apps.get_model("hbl_core", "CurrencyRate")
    PlatformConfig = apps.get_model("hbl_core", "PlatformConfig")

    WithdrawalMethod.objects.exclude(slug__in=ALLOWED_SLUGS).update(active=False)

    usdt_rate = (
        CurrencyRate.objects.filter(code="USDT", active=True)
        .values_list("rate_to_base", flat=True)
        .first()
    )
    if not usdt_rate:
        config = PlatformConfig.objects.filter(pk=1).first()
        usdt_rate = getattr(config, "exchange_rate_usd_nio", None) or Decimal("36.62")

    WithdrawalMethod.objects.filter(slug="usdt-trc20").update(
        active=True,
        currency="USDT",
        country="",
        network="TRON (TRC20)",
        identifier_type="trc20",
        holder_required=False,
        fee_percent=Decimal("0.00"),
        fee_fixed_nio=Decimal(str(usdt_rate)),
    )
    WithdrawalMethod.objects.filter(slug="usdt-bep20").update(
        active=True,
        currency="USDT",
        country="",
        network="BNB Smart Chain (BEP20)",
        identifier_type="bep20",
        holder_required=False,
        fee_percent=Decimal("0.00"),
        fee_fixed_nio=Decimal(str(usdt_rate)),
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hbl_core", "0015_seed_official_hbl_plans"),
    ]

    operations = [
        migrations.RunPython(enforce_crypto_withdrawals, noop_reverse),
    ]
