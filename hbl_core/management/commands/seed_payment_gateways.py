from django.core.management.base import BaseCommand
from django.db.models import Q

from hbl_core.models import PaymentMethod


class Command(BaseCommand):
    help = "Desactiva pasarelas automáticas y fuerza comprobante en recargas manuales."

    def handle(self, *args, **options):
        automatic = (
            Q(kind=PaymentMethod.Kind.BINANCE_PAY)
            | Q(network__iexact="PAYPAL")
            | Q(network__istartswith="TILOPAY")
        )

        disabled = PaymentMethod.objects.filter(automatic).update(active=False)

        manual_qs = PaymentMethod.objects.exclude(automatic)
        manual_updated = manual_qs.update(require_proof=True)

        # Conservamos TXID/referencia cuando aplica a Binance ID o criptomonedas,
        # pero toda aprobación queda exclusivamente en manos de administración.
        PaymentMethod.objects.filter(
            kind__in=[
                PaymentMethod.Kind.BINANCE_ID,
                PaymentMethod.Kind.USDT_TRC20,
                PaymentMethod.Kind.USDT_BEP20,
                PaymentMethod.Kind.CRYPTO_OTHER,
            ]
        ).exclude(automatic).update(require_txid=True)

        self.stdout.write(self.style.SUCCESS(
            "Pagos manuales listos: "
            f"pasarelas automáticas desactivadas={disabled}; "
            f"métodos manuales con comprobante obligatorio={manual_updated}."
        ))
