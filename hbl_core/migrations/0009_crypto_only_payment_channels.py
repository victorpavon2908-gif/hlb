from django.db import migrations


DEPOSIT_KINDS = ("usdt_trc20", "usdt_bep20")
WITHDRAWAL_SLUGS = ("usdt-trc20", "usdt-bep20")


def restrict_to_crypto_channels(apps, schema_editor):
    PaymentMethod = apps.get_model("hbl_core", "PaymentMethod")
    WithdrawalMethod = apps.get_model("hbl_core", "WithdrawalMethod")

    PaymentMethod.objects.exclude(kind__in=DEPOSIT_KINDS).update(active=False)
    PaymentMethod.objects.filter(kind__in=DEPOSIT_KINDS).update(
        currency="USDT",
        require_txid=True,
        require_proof=False,
    )

    specs = {
        "usdt-trc20": {
            "name": "USDT TRC20",
            "network": "TRON (TRC20)",
            "identifier_type": "trc20",
            "identifier_placeholder": "T...",
            "identifier_help": "Dirección USDT en red TRON (TRC20). La red se detecta automáticamente.",
            "sort_order": 10,
        },
        "usdt-bep20": {
            "name": "USDT BEP20",
            "network": "BNB Smart Chain (BEP20)",
            "identifier_type": "bep20",
            "identifier_placeholder": "0x...",
            "identifier_help": "Dirección USDT en BNB Smart Chain (BEP20). La red se detecta automáticamente.",
            "sort_order": 20,
        },
    }
    for slug, spec in specs.items():
        WithdrawalMethod.objects.update_or_create(
            slug=slug,
            defaults={
                **spec,
                "currency_mode": "fixed",
                "currency": "USDT",
                "country": "",
                "icon": "₮",
                "account_label": "Dirección USDT",
                "holder_required": False,
                "active": True,
            },
        )
    WithdrawalMethod.objects.exclude(slug__in=WITHDRAWAL_SLUGS).update(active=False)


class Migration(migrations.Migration):
    dependencies = [("hbl_core", "0008_rename_hbl_core_de_status_558235_idx_hbl_core_de_status_be9473_idx_and_more")]

    operations = [
        migrations.RunPython(restrict_to_crypto_channels, migrations.RunPython.noop),
    ]
