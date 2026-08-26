from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand

from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


class Command(BaseCommand):
    help = "Prepara los métodos base NOWPayments sin borrar el catálogo multimoneda dinámico."

    def _usdt_rate(self, config):
        row = CurrencyRate.objects.filter(code="USDT", active=True).first()
        if row and Decimal(row.rate_to_base) > 0:
            return Decimal(row.rate_to_base)
        return Decimal(config.exchange_rate_usd_nio)

    def handle(self, *args, **options):
        config = PlatformConfig.get_solo()
        min_usdt = (
            Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
            if settings.NOWPAYMENTS_TEST_MODE
            else Decimal(config.minimum_deposit_usd)
        )
        rate = self._usdt_rate(config)
        nowpayments_ready = bool(settings.NOWPAYMENTS_API_KEY and settings.NOWPAYMENTS_IPN_SECRET)

        specs = [
            {
                "kind": PaymentMethod.Kind.USDT_TRC20,
                "provider_code": "usdttrc20",
                "label": "Tether · TRON (TRC20)",
                "network_label": "TRON (TRC20)",
                "sort_order": 10,
            },
            {
                "kind": PaymentMethod.Kind.USDT_BEP20,
                "provider_code": "usdtbsc",
                "label": "Tether · BNB Smart Chain (BEP20)",
                "network_label": "BNB Smart Chain (BEP20)",
                "sort_order": 20,
            },
        ]

        for spec in specs:
            method = PaymentMethod.objects.filter(kind=spec["kind"]).order_by("id").first()
            if not method:
                method = PaymentMethod(kind=spec["kind"])
            method.label = spec["label"]
            method.currency = "USDT"
            method.network = spec["network_label"]
            method.destination = spec["provider_code"]
            method.instructions = (
                f"Paga con USDT por {spec['network_label']}. "
                "HBL suma 1 USDT al monto que deseas acreditar y NOWPayments genera la orden."
            )
            method.min_amount = min_usdt
            method.max_amount = Decimal("0")
            method.require_proof = False
            method.require_txid = False
            method.balance_rate = rate
            method.sender_network_fee_estimate = Decimal("0")
            method.active = nowpayments_ready
            method.sort_order = spec["sort_order"]
            method.save()

        # Se mantienen los crypto_other porque representan el catálogo dinámico.
        # Los canales antiguos (banco, remesa, etc.) sí quedan fuera de la interfaz
        # de depósito automático para conservar un único flujo NOWPayments.
        PaymentMethod.objects.exclude(
            kind__in=[
                PaymentMethod.Kind.USDT_TRC20,
                PaymentMethod.Kind.USDT_BEP20,
                PaymentMethod.Kind.CRYPTO_OTHER,
            ]
        ).update(active=False)

        self.stdout.write(self.style.SUCCESS(
            "Métodos base NOWPayments listos. El catálogo completo de criptomonedas se sincroniza dinámicamente en la billetera."
        ))
