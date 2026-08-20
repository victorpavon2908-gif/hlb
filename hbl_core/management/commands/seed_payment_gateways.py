from decimal import Decimal

from django.core.management.base import BaseCommand

from hbl_core.binance_wallet import BinanceWalletError, resolve_usdt_deposit_address, validate_usdt_address
from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


class Command(BaseCommand):
    help = "Deja HBL únicamente con depósitos USDT TRC20 y BEP20 hacia la cuenta configurada."

    def _usdt_rate(self, config):
        row = CurrencyRate.objects.filter(code="USDT", active=True).first()
        if row and Decimal(row.rate_to_base) > 0:
            return Decimal(row.rate_to_base)
        return Decimal(config.exchange_rate_usd_nio)

    def _existing_address(self, kind, network_code):
        for method in PaymentMethod.objects.filter(kind=kind).exclude(destination="").order_by("sort_order", "id"):
            try:
                return validate_usdt_address(network_code, method.destination)
            except BinanceWalletError:
                continue
        return ""

    def handle(self, *args, **options):
        config = PlatformConfig.get_solo()
        min_usdt = Decimal(config.minimum_deposit_usd)
        rate = self._usdt_rate(config)
        keep_ids = []

        specs = [
            {
                "kind": PaymentMethod.Kind.USDT_TRC20,
                "label": "USDT por TRC20",
                "network_label": "TRON (TRC20)",
                "network_code": "TRX",
                "sort_order": 10,
            },
            {
                "kind": PaymentMethod.Kind.USDT_BEP20,
                "label": "USDT por BEP20",
                "network_label": "BNB Smart Chain (BEP20)",
                "network_code": "BSC",
                "sort_order": 20,
            },
        ]

        for spec in specs:
            address = ""
            source = ""
            try:
                address, source = resolve_usdt_deposit_address(spec["network_code"])
            except BinanceWalletError as exc:
                address = self._existing_address(spec["kind"], spec["network_code"])
                if address:
                    source = "database"
                    self.stdout.write(self.style.WARNING(
                        f"{spec['label']}: Binance/Environment no disponible; se conserva la dirección pública ya guardada."
                    ))
                else:
                    self.stdout.write(self.style.WARNING(f"{spec['label']} desactivado: {exc}"))

            method, _ = PaymentMethod.objects.update_or_create(
                kind=spec["kind"],
                label=spec["label"],
                defaults={
                    "currency": "USDT",
                    "network": spec["network_label"],
                    "destination": address,
                    "instructions": (
                        f"Envía únicamente USDT por {spec['network_label']}. "
                        "Después pega el TXID de la transacción. No uses otra moneda ni otra red."
                    ),
                    "min_amount": min_usdt,
                    "max_amount": Decimal("0"),
                    "require_proof": False,
                    "require_txid": True,
                    "balance_rate": rate,
                    "active": bool(address),
                    "sort_order": spec["sort_order"],
                },
            )
            keep_ids.append(method.pk)

            if address:
                self.stdout.write(self.style.SUCCESS(
                    f"{spec['label']} activo · dirección obtenida desde {source}."
                ))

        disabled = PaymentMethod.objects.exclude(pk__in=keep_ids).update(active=False)
        self.stdout.write(self.style.SUCCESS(
            f"Configuración terminada: solo TRC20/BEP20 pueden quedar activos; otros métodos desactivados={disabled}."
        ))
