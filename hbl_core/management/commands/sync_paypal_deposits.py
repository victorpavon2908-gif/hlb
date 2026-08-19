from django.core.management.base import BaseCommand

from hbl_core.models import Deposit
from hbl_core.payment_gateways import PayPalClient, PaymentGatewayError
from hbl_core.services import HBLError, approve_deposit


class Command(BaseCommand):
    help = "Reconcilia órdenes PayPal pendientes consultando Orders v2 directamente."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"] or 100), 1000))
        client = PayPalClient()
        qs = (
            Deposit.objects
            .select_related("payment_method")
            .filter(
                status__in=[Deposit.Status.PENDING, Deposit.Status.PROCESSING],
                payment_method__network__iexact="PAYPAL",
            )
            .exclude(reference="")
            .order_by("submitted_at")[:limit]
        )

        checked = approved = pending = 0
        for deposit in qs:
            checked += 1
            try:
                order = client.get_order(deposit.reference)
                capture_id = client.validate_completed_order(order, deposit=deposit)
                _, created = approve_deposit(
                    deposit.id,
                    transaction_id=capture_id,
                    notes="Confirmado por reconciliación PayPal Orders v2",
                )
                if created:
                    approved += 1
                    self.stdout.write(self.style.SUCCESS(f"APPROVED {deposit.id} {capture_id}"))
            except (PaymentGatewayError, HBLError) as exc:
                pending += 1
                self.stdout.write(f"PENDING {deposit.id}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Reconciliación terminada: checked={checked} approved={approved} pending={pending}"
        ))
