import json

from django.core.management.base import BaseCommand

from hbl_core.models import Deposit, PaymentMethod
from hbl_core.payment_gateways import PaymentGatewayError, verify_crypto_deposit
from hbl_core.services import HBLError, approve_deposit


class Command(BaseCommand):
    help = "Revisa depósitos USDT TRC20/BEP20 pendientes y acredita solo los confirmados on-chain."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"] or 100), 1000))
        qs = (
            Deposit.objects
            .select_related("payment_method")
            .filter(
                status__in=[Deposit.Status.PENDING, Deposit.Status.PROCESSING],
                payment_method__kind__in=[PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20],
            )
            .exclude(txid="")
            .order_by("submitted_at")[:limit]
        )

        checked = approved = pending = 0
        for deposit in qs:
            checked += 1
            try:
                verified = verify_crypto_deposit(deposit)
                _, created = approve_deposit(
                    deposit.id,
                    transaction_id=deposit.txid,
                    notes=f"Confirmado por reconciliación blockchain: {json.dumps(verified, ensure_ascii=False)}",
                )
                if created:
                    approved += 1
                    self.stdout.write(self.style.SUCCESS(f"APPROVED {deposit.id} {deposit.txid}"))
            except (PaymentGatewayError, HBLError) as exc:
                pending += 1
                self.stdout.write(f"PENDING {deposit.id}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Reconciliación terminada: checked={checked} approved={approved} pending={pending}"
        ))
