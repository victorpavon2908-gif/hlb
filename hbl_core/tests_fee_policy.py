from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from .models import PaymentMethod
from .nowpayments import create_payment_for_deposit
from .payment_policies import USDT_OPERATION_FEE, usdt_fee_from_total, usdt_total_with_fee


class FixedUsdtFeePolicyTests(SimpleTestCase):
    def test_ten_usdt_becomes_eleven(self):
        self.assertEqual(USDT_OPERATION_FEE, Decimal("1.00000000"))
        self.assertEqual(usdt_total_with_fee(Decimal("10")), Decimal("11.00000000"))
        self.assertEqual(
            usdt_fee_from_total(Decimal("11"), Decimal("10")),
            Decimal("1.00000000"),
        )

    def test_nowpayments_order_is_created_with_fixed_extra_usdt(self):
        class FakeClient:
            def __init__(self):
                self.kwargs = None

            def create_payment(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "payment_id": "6326159425",
                    "payment_status": "waiting",
                    "pay_address": "TQnFakeAddressForUnitTestOnly11111111",
                    "pay_currency": "usdttrc20",
                    "price_amount": "11.00000000",
                    "pay_amount": "11.00000000",
                }

        deposit = SimpleNamespace(
            id="fee-test",
            provider_price_amount=Decimal("10.00000000"),
            payment_method=SimpleNamespace(kind=PaymentMethod.Kind.USDT_TRC20),
        )
        client = FakeClient()

        remote = create_payment_for_deposit(
            deposit,
            "https://example.test/ipn/",
            client=client,
        )

        self.assertEqual(client.kwargs["price_amount"], Decimal("11.00000000"))
        self.assertFalse(client.kwargs["fee_paid_by_user"])
        self.assertEqual(remote["pay_amount"], Decimal("11.00000000"))
        self.assertEqual(remote["fee_amount"], Decimal("1.00000000"))
