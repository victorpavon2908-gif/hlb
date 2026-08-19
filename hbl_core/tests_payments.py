import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hbl_core.models import PaymentMethod
from hbl_core.payment_gateways import (
    PayPalClient,
    PaymentGatewayError,
    _TRANSFER_TOPIC,
    verify_bep20_deposit,
    verify_trc20_deposit,
)


class PayPalValidationTests(SimpleTestCase):
    def _deposit(self):
        return SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            payment_amount=Decimal("100.00"),
            payment_currency="USD",
        )

    def _order(self, value="100.00", currency="USD"):
        dep = self._deposit()
        return {
            "status": "COMPLETED",
            "purchase_units": [{
                "reference_id": str(dep.id),
                "custom_id": str(dep.id),
                "payments": {"captures": [{
                    "id": "CAPTURE123",
                    "status": "COMPLETED",
                    "amount": {"currency_code": currency, "value": value},
                }]},
            }],
        }

    def test_accepts_exact_completed_order(self):
        capture_id = PayPalClient.validate_completed_order(self._order(), deposit=self._deposit())
        self.assertEqual(capture_id, "CAPTURE123")

    def test_rejects_wrong_amount(self):
        with self.assertRaises(PaymentGatewayError):
            PayPalClient.validate_completed_order(self._order(value="99.00"), deposit=self._deposit())

    def test_rejects_wrong_currency(self):
        with self.assertRaises(PaymentGatewayError):
            PayPalClient.validate_completed_order(self._order(currency="EUR"), deposit=self._deposit())


class TronValidationTests(SimpleTestCase):
    @patch.dict(os.environ, {
        "USDT_TRC20_CONTRACT": "TUSDTCONTRACTADDRESS",
        "USDT_TRC20_DECIMALS": "6",
    }, clear=False)
    @patch("hbl_core.payment_gateways._json_request")
    def test_validates_confirmed_usdt_trc20_transfer(self, mock_request):
        mock_request.return_value = {
            "data": [{
                "event_name": "Transfer",
                "contract_address": "TUSDTCONTRACTADDRESS",
                "result": {
                    "to": "TRECIPIENTADDRESS1234567890123456",
                    "from": "TSENDER",
                    "value": "100000000",
                },
            }]
        }
        deposit = SimpleNamespace(
            txid="a" * 64,
            payment_amount=Decimal("100"),
            payment_currency="USDT",
            payment_method=SimpleNamespace(
                kind=PaymentMethod.Kind.USDT_TRC20,
                destination="TRECIPIENTADDRESS1234567890123456",
            ),
        )
        result = verify_trc20_deposit(deposit)
        self.assertEqual(result["amount"], "100")
        self.assertEqual(result["network"], "TRC20")


class BscValidationTests(SimpleTestCase):
    @patch.dict(os.environ, {
        "BSC_RPC_URL": "https://rpc.invalid.example",
        "USDT_BEP20_CONTRACT": "0x1111111111111111111111111111111111111111",
        "USDT_BEP20_DECIMALS": "18",
        "BSC_REQUIRED_CONFIRMATIONS": "12",
    }, clear=False)
    @patch("hbl_core.payment_gateways._bsc_rpc")
    def test_validates_confirmed_bep20_transfer(self, mock_rpc):
        recipient = "0x2222222222222222222222222222222222222222"
        recipient_topic = "0x" + ("0" * 24) + recipient[2:]
        amount_hex = hex(100 * 10**18)
        receipt = {
            "status": "0x1",
            "blockNumber": hex(100),
            "logs": [{
                "address": "0x1111111111111111111111111111111111111111",
                "topics": [_TRANSFER_TOPIC, "0x" + "0" * 64, recipient_topic],
                "data": amount_hex,
            }],
        }
        mock_rpc.side_effect = [receipt, hex(111)]
        deposit = SimpleNamespace(
            txid="0x" + "a" * 64,
            payment_amount=Decimal("100"),
            payment_currency="USDT",
            payment_method=SimpleNamespace(
                kind=PaymentMethod.Kind.USDT_BEP20,
                destination=recipient,
            ),
        )
        result = verify_bep20_deposit(deposit)
        self.assertEqual(result["amount"], "100")
        self.assertEqual(result["confirmations"], 12)
