import os
from decimal import Decimal

from django.core.management.base import BaseCommand

from hbl_core.binance_wallet import BinanceWalletError, resolve_usdt_deposit_address, validate_usdt_address
from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


class Command(BaseCommand):
    help = "Deja HBL únicamente con TRC20, BEP20 y transferencia bancaria."

    def _usdt_rate(self, config):
        row = CurrencyRate.objects.filter(code="USDT", active=True).first()
        if row and Decimal(row.rate_to_base) > 0:
            return Decimal(row.rate_to_base)
        return Decimal(config.exchange_rate_usd_nio)

    def _usd_rate(self, config):
        row = CurrencyRate.objects.filter(code="USD", active=True).first()
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

    def _configure_bank(self, config):
        existing = PaymentMethod.objects.filter(kind=PaymentMethod.Kind.BANK).order_by("id").first()
        destination = (os.getenv("BANK_TRANSFER_DESTINATION", "") or "").strip()
        network = (os.getenv("BANK_TRANSFER_NETWORK", "") or "").strip()
        instructions = (os.getenv("BANK_TRANSFER_INSTRUCTIONS", "") or "").strip()

        if existing:
            destination = destination or (existing.destination or "").strip()
            network = network or (existing.network or "").strip()
            instructions = instructions or (existing.instructions or "").strip()

        bank_min = (Decimal(config.minimum_deposit_usd) * self._usd_rate(config)).quantize(Decimal("0.01"))
        defaults = {
            "label": "Transferencia bancaria",
            "currency": config.base_currency_code.upper(),
            "network": network or "Transferencia bancaria",
            "destination": destination,
            "instructions": instructions or (
                "Realiza la transferencia a la cuenta indicada y sube el comprobante. "
                "El saldo se acredita después de la revisión administrativa."
            ),
            "min_amount": bank_min,
            "max_amount": Decimal("0"),
            "require_proof": True,
            "require_txid": False,
            "balance_rate": Decimal("1"),
            "active": True,
            "sort_order": 30,
        }

        if existing:
            for field, value in defaults.items():
                setattr(existing, field, value)
            existing.save(update_fields=list(defaults.keys()))
            return existing
        return PaymentMethod.objects.create(kind=PaymentMethod.Kind.BANK, **defaults)

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
                        f"{spec['label']}: se conserva la dirección pública ya guardada."
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
                        "Después pega el TXID real. No uses otra moneda ni otra red."
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

        bank = self._configure_bank(config)
        keep_ids.append(bank.pk)

        obsolete = PaymentMethod.objects.exclude(pk__in=keep_ids)
        deactivated = obsolete.update(active=False)
        deleted, _ = PaymentMethod.objects.exclude(pk__in=keep_ids).filter(deposits__isnull=True).delete()

        self.stdout.write(self.style.SUCCESS(
            "Configuración terminada: visibles únicamente TRC20, BEP20 y transferencia bancaria; "
            f"métodos antiguos desactivados={deactivated}, eliminados sin historial={deleted}."
        ))
