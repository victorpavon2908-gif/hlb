import os
from decimal import Decimal

from django.core.management.base import BaseCommand

from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_value(name):
    return (os.getenv(name, "") or "").strip()


class Command(BaseCommand):
    help = "Crea/normaliza métodos automáticos y activa solo los que tienen configuración completa."

    def _rate(self, code):
        config = PlatformConfig.get_solo()
        code = code.upper()
        if code == config.base_currency_code.upper():
            return Decimal("1")
        row = CurrencyRate.objects.filter(code=code, active=True).first()
        if row:
            return Decimal(row.rate_to_base)
        if code in {"USD", "USDT"}:
            return Decimal(config.exchange_rate_usd_nio)
        return Decimal("1")

    def _upsert(self, *, lookup, defaults, force_fields=None):
        obj, created = PaymentMethod.objects.get_or_create(**lookup, defaults=defaults)
        changed = []
        if not created:
            for field, value in (force_fields or {}).items():
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed.append(field)
            if changed:
                obj.save(update_fields=changed)
        return obj

    def handle(self, *args, **options):
        config = PlatformConfig.get_solo()
        min_usd = Decimal(config.minimum_deposit_usd)

        binance_ready = (
            env_bool("BINANCE_PAY_ENABLED", False)
            and bool(env_value("BINANCE_PAY_API_KEY"))
            and bool(env_value("BINANCE_PAY_SECRET_KEY"))
        )
        paypal_ready = (
            env_bool("PAYPAL_ENABLED", False)
            and bool(env_value("PAYPAL_CLIENT_ID"))
            and bool(env_value("PAYPAL_CLIENT_SECRET"))
        )
        tilopay_ready = (
            env_bool("TILOPAY_ENABLED", False)
            and bool(env_value("TILOPAY_API_KEY"))
            and bool(env_value("TILOPAY_API_USER"))
            and bool(env_value("TILOPAY_API_PASSWORD"))
        )

        trc_wallet = env_value("USDT_TRC20_WALLET")
        trc_contract = env_value("USDT_TRC20_CONTRACT")
        trc_ready = (
            env_bool("USDT_TRC20_ENABLED", False)
            and bool(trc_wallet)
            and bool(trc_contract)
        )

        bep_wallet = env_value("USDT_BEP20_WALLET")
        bep_contract = env_value("USDT_BEP20_CONTRACT")
        bep_ready = (
            env_bool("USDT_BEP20_ENABLED", False)
            and bool(bep_wallet)
            and bool(bep_contract)
            and bool(env_value("BSC_RPC_URL"))
        )

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.BINANCE_PAY, "label": "Binance Pay automático"},
            defaults={
                "currency": "USDT",
                "network": "BINANCE_PAY",
                "min_amount": min_usd,
                "balance_rate": self._rate("USDT"),
                "require_proof": False,
                "require_txid": False,
                "active": binance_ready,
                "sort_order": 10,
                "instructions": "Checkout automático de Binance Pay. HBL acredita únicamente tras confirmación del proveedor.",
            },
            force_fields={
                "network": "BINANCE_PAY",
                "require_proof": False,
                "require_txid": False,
                "active": binance_ready,
            },
        )

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.MOBILE_WALLET, "label": "PayPal"},
            defaults={
                "currency": "USD",
                "network": "PAYPAL",
                "min_amount": min_usd,
                "balance_rate": self._rate("USD"),
                "require_proof": False,
                "require_txid": False,
                "active": paypal_ready,
                "sort_order": 20,
                "instructions": "Checkout automático PayPal. No compartas contraseñas con HBL.",
            },
            force_fields={
                "currency": "USD",
                "network": "PAYPAL",
                "require_proof": False,
                "require_txid": False,
                "active": paypal_ready,
            },
        )

        tilopay_currency = (env_value("TILOPAY_CURRENCY") or "USD").upper()
        self._upsert(
            lookup={"kind": PaymentMethod.Kind.MOBILE_WALLET, "label": "Tarjeta / Tilopay"},
            defaults={
                "currency": tilopay_currency,
                "network": "TILOPAY",
                "min_amount": min_usd,
                "balance_rate": self._rate(tilopay_currency),
                "require_proof": False,
                "require_txid": False,
                "active": tilopay_ready,
                "sort_order": 30,
                "instructions": "Checkout alojado por Tilopay. Los datos sensibles de tarjeta no pasan por el servidor HBL.",
            },
            force_fields={
                "currency": tilopay_currency,
                "network": "TILOPAY",
                "require_proof": False,
                "require_txid": False,
                "active": tilopay_ready,
            },
        )

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.USDT_TRC20, "label": "USDT por TRC20"},
            defaults={
                "currency": "USDT",
                "network": "TRON (TRC20)",
                "destination": trc_wallet,
                "min_amount": min_usd,
                "balance_rate": self._rate("USDT"),
                "require_proof": False,
                "require_txid": True,
                "active": trc_ready,
                "sort_order": 40,
                "instructions": "Envía exclusivamente USDT TRC20 a la wallet indicada y pega el TXID. HBL valida token, destino, monto y confirmación.",
            },
            force_fields={
                "destination": trc_wallet,
                "require_proof": False,
                "require_txid": True,
                "active": trc_ready,
            },
        )

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.USDT_BEP20, "label": "USDT por BEP20"},
            defaults={
                "currency": "USDT",
                "network": "BNB Smart Chain (BEP20)",
                "destination": bep_wallet,
                "min_amount": min_usd,
                "balance_rate": self._rate("USDT"),
                "require_proof": False,
                "require_txid": True,
                "active": bep_ready,
                "sort_order": 50,
                "instructions": "Envía exclusivamente el token USDT configurado en BEP20 a la wallet indicada y pega el TXID. HBL valida receipt, contrato, destino, monto y confirmaciones.",
            },
            force_fields={
                "destination": bep_wallet,
                "require_proof": False,
                "require_txid": True,
                "active": bep_ready,
            },
        )

        self.stdout.write(self.style.SUCCESS(
            "Gateways listos. Activos solo con configuración completa: "
            f"Binance={binance_ready}, PayPal={paypal_ready}, Tilopay={tilopay_ready}, "
            f"TRC20={trc_ready}, BEP20={bep_ready}."
        ))
