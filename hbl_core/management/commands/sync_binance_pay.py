from django.core.management.base import BaseCommand

from hbl_core.binance_pay import BinancePayClient, BinancePayError
from hbl_core.models import Deposit, PaymentMethod
from hbl_core.services import approve_deposit


class Command(BaseCommand):
    help = "Consulta Binance Pay y confirma recargas pendientes sin confiar en el navegador del usuario."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        client = BinancePayClient()
        qs = Deposit.objects.filter(
            payment_method__kind=PaymentMethod.Kind.BINANCE_PAY,
            status__in=[Deposit.Status.PENDING, Deposit.Status.PROCESSING],
            merchant_trade_no__isnull=False,
        ).exclude(merchant_trade_no="")[: options["limit"]]
        approved = checked = errors = 0
        for deposit in qs:
            checked += 1
            try:
                response = client.query_order(merchant_trade_no=deposit.merchant_trade_no)
                data = response.get("data") or {}
                if data.get("status") == "PAID":
                    client.validate_order_data(
                        data, merchant_trade_no=deposit.merchant_trade_no,
                        expected_amount=deposit.payment_amount, expected_currency=deposit.payment_currency,
                        expected_prepay_id=deposit.prepay_id or None, require_paid=True,
                    )
                    _, changed = approve_deposit(
                        deposit.id,
                        transaction_id=data.get("transactionId", ""),
                        notes="Confirmado por sync_binance_pay",
                    )
                    approved += int(changed)
            except BinancePayError as exc:
                errors += 1
                self.stderr.write(f"{deposit.id}: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Revisadas: {checked}; aprobadas: {approved}; errores: {errors}."))
