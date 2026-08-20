from django.core.management.base import BaseCommand

from hbl_core.crypto_payments import verify_and_credit_deposit
from hbl_core.models import Deposit, PaymentMethod


class Command(BaseCommand):
    help = "Reintenta la validación automática de depósitos USDT TRC20/BEP20 pendientes."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument(
            "--include-pending",
            action="store_true",
            help="Incluye depósitos enviados a revisión manual además de los que están procesando.",
        )

    def handle(self, *args, **options):
        limit = max(1, min(int(options["limit"] or 100), 1000))
        statuses = [Deposit.Status.PROCESSING]
        if options["include_pending"]:
            statuses.append(Deposit.Status.PENDING)

        queryset = (
            Deposit.objects.select_related("payment_method")
            .filter(
                status__in=statuses,
                payment_method__kind__in=[
                    PaymentMethod.Kind.USDT_TRC20,
                    PaymentMethod.Kind.USDT_BEP20,
                ],
            )
            .exclude(txid="")
            .order_by("submitted_at")[:limit]
        )

        checked = approved = errors = 0
        for deposit in queryset:
            checked += 1
            try:
                obj, changed = verify_and_credit_deposit(deposit.id)
            except Exception as exc:
                errors += 1
                self.stderr.write(f"{deposit.id}: {exc}")
                continue
            if obj.status == Deposit.Status.APPROVED and changed:
                approved += 1
                self.stdout.write(self.style.SUCCESS(f"{deposit.id}: aprobado automáticamente"))
            else:
                self.stdout.write(f"{deposit.id}: {obj.status} · {obj.notes[:160]}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciliación USDT terminada: revisados={checked}, aprobados={approved}, errores={errors}."
            )
        )
