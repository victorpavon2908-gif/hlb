from django.core.management.base import BaseCommand

from hbl_core.models import Deposit
from hbl_core.services import HBLError, approve_deposit
from hbl_core.tilopay import TilopayClient, TilopayError, tilopay_enabled


class Command(BaseCommand):
    help = "Reconcilia recargas Tilopay pendientes consultando el detalle del link antes de acreditar."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not tilopay_enabled():
            self.stdout.write(self.style.WARNING("TILOPAY_ENABLED=False; no se procesó ninguna recarga."))
            return

        limit = max(1, min(int(options["limit"] or 100), 1000))
        deposits = (
            Deposit.objects.select_related("payment_method")
            .filter(
                status__in=[Deposit.Status.PENDING, Deposit.Status.PROCESSING],
                payment_method__network__istartswith="TILOPAY",
            )
            .exclude(reference="")[:limit]
        )

        client = TilopayClient()
        approved = 0
        pending = 0
        failed = 0

        for deposit in deposits:
            try:
                detail = client.payment_link_detail(deposit.reference)
                transaction_id = client.validate_paid_detail(detail, deposit=deposit)
                _, changed = approve_deposit(
                    deposit.id,
                    transaction_id=transaction_id,
                    notes="Confirmado por reconciliación Tilopay",
                )
                approved += int(bool(changed))
            except TilopayError as exc:
                pending += 1
                deposit.notes = f"Reconciliación Tilopay pendiente: {exc}"
                deposit.save(update_fields=["notes"])
            except HBLError as exc:
                failed += 1
                self.stderr.write(f"{deposit.id}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Tilopay reconciliado: aprobadas={approved}, pendientes={pending}, errores={failed}."
            )
        )
