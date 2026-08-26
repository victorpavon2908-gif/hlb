from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from .models import PaymentMethod
from .nowpayments import NowPaymentsClient, NowPaymentsError, create_payment_for_deposit


@override_settings(
    NOWPAYMENTS_API_KEY="test-key",
    NOWPAYMENTS_API_BASE_URL="https://api.nowpayments.io/v1",
    NOWPAYMENTS_TIMEOUT_SECONDS=15,
    NOWPAYMENTS_USER_AGENT="HBL-Payments-Test/1.0",
    NOWPAYMENTS_FEE_PAID_BY_USER=False,
)
class NowPaymentsExactAmountTests(SimpleTestCase):
    @patch.object(NowPaymentsClient, "_request")
    def test_client_sends_explicit_crypto_pay_amount(self, request):
        request.return_value = {}
        client = NowPaymentsClient(api_key="test-key")

        client.create_payment(
            price_amount=Decimal("11.00000000"),
            pay_amount=Decimal("11.00000000"),
            pay_currency="usdtbsc",
            order_id="hbl-deposit:test",
            callback_url="https://example.test/ipn/",
            fee_paid_by_user=False,
        )

        payload = request.call_args.args[2]
        self.assertEqual(payload["price_amount"], "11.00000000")
        self.assertEqual(payload["pay_amount"], "11.00000000")
        self.assertFalse(payload["is_fee_paid_by_user"])

    def _deposit(self):
        return SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            provider_price_amount=Decimal("10.00000000"),
            payment_method=SimpleNamespace(kind=PaymentMethod.Kind.USDT_BEP20),
        )

    def test_deposit_requests_exact_credit_plus_one_usdt(self):
        client = MagicMock()
        client.create_payment.return_value = {
            "payment_id": "6326159425",
            "payment_status": "waiting",
            "pay_address": "0xe3D3976ee990CE7655eD7c8BE36c46DF6f1F55Ff",
            "pay_amount": "11.00000000",
            "pay_currency": "usdtbsc",
            "price_amount": "11.00000000",
        }

        result = create_payment_for_deposit(
            self._deposit(),
            "https://example.test/ipn/",
            client=client,
        )

        kwargs = client.create_payment.call_args.kwargs
        self.assertEqual(kwargs["price_amount"], Decimal("11.00000000"))
        self.assertEqual(kwargs["pay_amount"], Decimal("11.00000000"))
        self.assertEqual(result["pay_amount"], Decimal("11.00000000"))
        self.assertEqual(result["fee_amount"], Decimal("1.00000000"))

    def test_provider_quote_drift_is_rejected_instead_of_displayed(self):
        client = MagicMock()
        client.create_payment.return_value = {
            "payment_id": "6326159425",
            "payment_status": "waiting",
            "pay_address": "0xe3D3976ee990CE7655eD7c8BE36c46DF6f1F55Ff",
            "pay_amount": "11.01794658",
            "pay_currency": "usdtbsc",
            "price_amount": "11.00000000",
        }

        with self.assertRaisesMessage(
            NowPaymentsError,
            "NOWPayments no respetó el total exacto solicitado",
        ):
            create_payment_for_deposit(
                self._deposit(),
                "https://example.test/ipn/",
                client=client,
            )
