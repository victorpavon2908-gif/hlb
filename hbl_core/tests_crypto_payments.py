from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from .crypto_payments import (
    BSC_USDT_CONTRACT_DEFAULT,
    TRANSFER_TOPIC,
    TRON_USDT_CONTRACT_DEFAULT,
    _tron_evm_hex,
    verify_bep20,
    verify_trc20,
)
from .models import PaymentMethod


class CryptoPaymentVerificationTests(SimpleTestCase):
    def _deposit(self, *, kind, destination, amount="100.00000000", txid=None):
        return SimpleNamespace(
            txid=txid or ("a" * 64),
            payment_amount=amount,
            submitted_at=timezone.now(),
            payment_method=SimpleNamespace(kind=kind, destination=destination),
        )

    @patch("hbl_core.crypto_payments._http_json")
    def test_trc20_requires_matching_usdt_transfer_to_destination(self, mocked_http):
        destination = TRON_USDT_CONTRACT_DEFAULT
        destination_hex = _tron_evm_hex(destination)
        contract_hex = _tron_evm_hex(TRON_USDT_CONTRACT_DEFAULT)
        amount_units = 100 * 10**6
        mocked_http.return_value = {
            "id": "a" * 64,
            "blockNumber": 123456,
            "blockTimeStamp": int(timezone.now().timestamp() * 1000),
            "receipt": {"result": "SUCCESS"},
            "log": [{
                "address": contract_hex,
                "topics": [
                    TRANSFER_TOPIC,
                    "0" * 64,
                    "0" * 24 + destination_hex,
                ],
                "data": f"{amount_units:064x}",
            }],
        }

        result = verify_trc20(
            self._deposit(
                kind=PaymentMethod.Kind.USDT_TRC20,
                destination=destination,
            )
        )
        self.assertEqual(result.amount, 100)
        self.assertEqual(result.network, "TRC20")

    @patch("hbl_core.crypto_payments._rpc")
    def test_bep20_requires_confirmed_matching_usdt_transfer(self, mocked_rpc):
        destination = "0x1111111111111111111111111111111111111111"
        amount_units = 100 * 10**18
        receipt = {
            "status": "0x1",
            "blockNumber": "0x64",
            "logs": [{
                "address": BSC_USDT_CONTRACT_DEFAULT,
                "topics": [
                    "0x" + TRANSFER_TOPIC,
                    "0x" + "0" * 64,
                    "0x" + "0" * 24 + destination.removeprefix("0x"),
                ],
                "data": hex(amount_units),
            }],
        }
        block = {"timestamp": hex(int(timezone.now().timestamp()))}

        def rpc_side_effect(url, method, params):
            if method == "eth_getTransactionReceipt":
                return receipt
            if method == "eth_blockNumber":
                return "0x80"
            if method == "eth_getBlockByNumber":
                return block
            raise AssertionError(method)

        mocked_rpc.side_effect = rpc_side_effect
        result = verify_bep20(
            self._deposit(
                kind=PaymentMethod.Kind.USDT_BEP20,
                destination=destination,
                txid="0x" + "b" * 64,
            )
        )
        self.assertEqual(result.amount, 100)
        self.assertEqual(result.network, "BEP20")
        self.assertGreaterEqual(result.confirmations, 12)
