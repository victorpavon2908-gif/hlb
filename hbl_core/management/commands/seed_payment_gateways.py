from decimal import Decimal

from django.conf import settings

from django.core.management.base import BaseCommand

from hbl_core.models import CurrencyRate, PaymentMethod, PlatformConfig


class Command(BaseCommand):
    help = "Deja HBL únicamente con depósitos USDT por TRC20 y BEP20."

    def _usdt_rate(self, config):
        row = CurrencyRate.objects.filter(code="USDT", active=True).first()
        if row and Decimal(row.rate_to_base) > 0:
            return Decimal(row.rate_to_base)
        return Decimal(config.exchange_rate_usd_nio)

    def handle(self, *args, **options):
        config = PlatformConfig.get_solo()
        min_usdt = Decimal(config.minimum_deposit_usd)
        rate = self._usdt_rate(config)
        nowpayments_ready = bool(settings.NOWPAYMENTS_API_KEY and settings.NOWPAYMENTS_IPN_SECRET)
        keep_ids = []

        specs = [
            {
                "kind": PaymentMethod.Kind.USDT_TRC20,
                "label": "USDT por TRC20",
                "network_label": "TRON (TRC20)",
                "sort_order": 10,
            },
            {
                "kind": PaymentMethod.Kind.USDT_BEP20,
                "label": "USDT por BEP20",
                "network_label": "BNB Smart Chain (BEP20)",
                "sort_order": 20,
            },
        ]

        for spec in specs:
            method, _ = PaymentMethod.objects.update_or_create(
                kind=spec["kind"],
                label=spec["label"],
                defaults={
                    "currency": "USDT",
                    "network": spec["network_label"],
                    "destination": "",
                    "instructions": (
                        f"Envía únicamente USDT por {spec['network_label']}. "
                        "NOWPayments generará el monto y la dirección exactos para esta orden."
                    ),
                    "min_amount": min_usdt,
                    "max_amount": Decimal("0"),
                    "require_proof": False,
                    "require_txid": False,
                    "balance_rate": rate,
                    "active": nowpayments_ready,
                    "sort_order": spec["sort_order"],
                },
            )
            keep_ids.append(method.pk)
            if nowpayments_ready:
                self.stdout.write(self.style.SUCCESS(
                    f"{spec['label']} activo mediante NOWPayments."
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"{spec['label']} desactivado: faltan NOWPAYMENTS_API_KEY o NOWPAYMENTS_IPN_SECRET."
                ))

        obsolete = PaymentMethod.objects.exclude(pk__in=keep_ids)
        deactivated = obsolete.update(active=False)
        deleted, _ = PaymentMethod.objects.exclude(pk__in=keep_ids).filter(deposits__isnull=True).delete()

        self.stdout.write(self.style.SUCCESS(
            "Configuración terminada: visibles únicamente USDT TRC20 y USDT BEP20; "
            f"métodos antiguos desactivados={deactivated}, eliminados sin historial={deleted}."
        ))
