import os
from decimal import Decimal

from django.core.management.base import BaseCommand

from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Crea/normaliza métodos automáticos y toma destinos públicos/flags desde Environment."

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

        binance_enabled = env_bool("BINANCE_PAY_ENABLED", False)
        paypal_enabled = env_bool("PAYPAL_ENABLED", False)
        tilopay_enabled = env_bool("TILOPAY_ENABLED", False)
        trc20_enabled = env_bool("USDT_TRC20_ENABLED", False)
        bep20_enabled = env_bool("USDT_BEP20_ENABLED", False)

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.BINANCE_PAY, "label": "Binance Pay automático"},
            defaults={
                "currency": "USDT", "network": "BINANCE_PAY", "min_amount": min_usd,
                "balance_rate": self._rate("USDT"), "require_proof": False,
                "require_txid": False, "active": binance_enabled, "sort_order": 10,
                "instructions": "Checkout automático de Binance Pay. HBL acredita únicamente tras confirmación del proveedor.",
            },
            force_fields={"network": "BINANCE_PAY", "require_proof": False, "require_txid": False, "active": binance_enabled},
        )

        self._upsert(
            lookup={"kind": PaymentMethod.Kind.MOBILE_WALLET, "label": "PayPal"},
            defaults={
                "currency": "USD", "network": "PAYPAL", "min_amount": min_usd,
                "balance_rate": self._rate("USD"), "require_proof": False,
                "require_txid": False, "active": paypal_enabled, "sort_order": 20,
                "instructions": "Checkout automático PayPal. No compartas contraseñas con HBL.",
            },
            force_fields={"currency": "USD", "network": "PAYPAL", "require_proof": False, "require_txid": False, "active": paypal_enabled},
        )

        tilopay_currency = (os.getenv("TILOPAY_CURRENCY", "USD") or "USD").strip().upper()
        self._upsert(
            lookup={"kind": PaymentMethod.Kind.MOBILE_WALLET, "label": "Tarjeta / Tilopay"},
            defaults={
                "currency": tilopay_currency, "network": "TILOPAY", "min_amount": min_usd,
                "balance_rate": self._rate(tilopay_currency), "require_proof": False,
                "require_txid": False, "active": tilopay_enabled, "sort_order": 30,
                "instructions": "Checkout alojado por Tilopay. Los datos sensibles de tarjeta no pasan por el servidor HBL.",
            },
            force_fields={"currency": tilopay_currency, "network": "TILOPAY", "require_proof": False, "require_txid": False, "active": tilopay_enabled},
        )

        trc_wallet = (os.getenv("USDT_TRC20_WALLET", "") or "").strip()
        trc_contract = (os.getenv("USDT_TRC20_CONTRACT", "") or "").strip()
        trc_ready = trc20_enabled and bool(trc_wallet and trc_contract)
        self._upsert(
            lookup={"kind": PaymentMethod.Kind.USDT_TRC20, "label": "USDT por TRC20"},
            defaults={
                "currency": "USDT", "network": "TRON (TRC20)", "destination": trc_wallet,
                "min_amount": min_usd, "balance_rate": self._rate("USDT"),
                "require_proof": False, "require_txid": True, "active": trc_ready, "sort_order": 40,
                "instructions": "Envía exclusivamente USDT TRC20 a la wallet indicada y pega el TXID. HBL valida token, destino, monto y confirmación.",
            },
            force_fields={"destination": trc_wallet, "require_proof": False, "require_txid": True, "active": trc_ready},
        )

        bep_wallet = (os.getenv("USDT_BEP20_WALLET", "") or "").strip()
        bep_contract = (os.getenv("USDT_BEP20_CONTRACT", "") or "").strip()
        bep_ready = bep20_enabled and bool(bep_wallet and bep_contract and os.getenv("BSC_RPC_URL", "").strip())
        self._upsert(
            lookup={"kind": PaymentMethod.Kind.USDT_BEP20, "label": "USDT por BEP20"},
            defaults={
                "currency": "USDT", "network": "BNB Smart Chain (BEP20)", "destination": bep_wallet,
                "min_amount": min_usd, "balance_rate": self._rate("USDT"),
                "require_proof": False, "require_txid": True, "active": bep_ready, "sort_order": 50,
                "instructions": "Envía exclusivamente el token USDT configurado en BEP20 a la wallet indicada y pega el TXID. HBL valida receipt, contrato, destino, monto y confirmaciones.",
            },
            force_fields={"destination": bep_wallet, "require_proof": False, "require_txid": True, "active": bep_ready},
        )

        self.stdout.write(self.style.SUCCESS(
            "Gateways listos. Activos según Environment: "
            f"Binance={binance_enabled}, PayPal={paypal_enabled}, Tilopay={tilopay_enabled}, "
            f"TRC20={trc_ready}, BEP20={bep_ready}."
        ))
