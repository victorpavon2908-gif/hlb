"""Pasarelas y verificadores de recargas HBL.

Principios:
- Ninguna pasarela modifica el saldo del usuario directamente.
- El saldo solo se acredita mediante services.approve_deposit().
- Las credenciales privadas se leen del entorno del servidor.
- Las wallets públicas pueden vivir en PaymentMethod.destination.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings

from .models import Deposit, PaymentMethod


class PaymentGatewayError(Exception):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _json_request(url, *, method="GET", payload=None, headers=None, timeout=15):
    body = None
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:700]
        raise PaymentGatewayError(f"Proveedor respondió HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PaymentGatewayError("No fue posible comunicarse correctamente con el proveedor de pago.") from exc


class PayPalClient:
    """Cliente mínimo de PayPal Checkout Orders v2 + verificación de webhooks."""

    def __init__(self, *, client_id=None, client_secret=None, mode=None, timeout=15):
        self.client_id = client_id or os.getenv("PAYPAL_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
        self.mode = (mode or os.getenv("PAYPAL_MODE", "sandbox")).strip().lower()
        self.timeout = timeout
        if not self.client_id or not self.client_secret:
            raise PaymentGatewayError("PayPal no está configurado en el servidor.")
        self.host = "https://api-m.paypal.com" if self.mode == "live" else "https://api-m.sandbox.paypal.com"

    def _token(self):
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            f"{self.host}/v1/oauth2/token",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise PaymentGatewayError(f"PayPal rechazó autenticación HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PaymentGatewayError("No fue posible autenticar con PayPal.") from exc
        token = payload.get("access_token")
        if not token:
            raise PaymentGatewayError("PayPal no devolvió access_token.")
        return token

    def _api(self, path, *, method="GET", payload=None, request_id=""):
        headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id[:108]
        return _json_request(f"{self.host}{path}", method=method, payload=payload, headers=headers, timeout=self.timeout)

    def create_order(self, *, deposit: Deposit, return_url: str, cancel_url: str):
        currency = (deposit.payment_currency or "USD").upper()
        amount = Decimal(deposit.payment_amount).quantize(Decimal("0.01"))
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": str(deposit.id),
                "custom_id": str(deposit.id),
                "description": "HBL wallet credit",
                "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        return self._api("/v2/checkout/orders", method="POST", payload=payload, request_id=f"hbl-create-{deposit.id}")

    def get_order(self, order_id: str):
        return self._api(f"/v2/checkout/orders/{urllib.parse.quote(order_id)}")

    def capture_order(self, order_id: str, *, deposit_id: str):
        return self._api(
            f"/v2/checkout/orders/{urllib.parse.quote(order_id)}/capture",
            method="POST",
            payload={},
            request_id=f"hbl-capture-{deposit_id}",
        )

    @staticmethod
    def approval_url(order_data):
        for link in order_data.get("links") or []:
            if link.get("rel") in {"payer-action", "approve"} and link.get("href"):
                return link["href"]
        return ""

    @staticmethod
    def validate_completed_order(order_data, *, deposit: Deposit):
        if not isinstance(order_data, dict) or order_data.get("status") != "COMPLETED":
            raise PaymentGatewayError("La orden PayPal todavía no está completada.")
        units = order_data.get("purchase_units") or []
        if not units:
            raise PaymentGatewayError("PayPal no devolvió purchase_units.")
        unit = units[0]
        expected_id = str(deposit.id)
        if str(unit.get("reference_id") or unit.get("custom_id") or "") != expected_id and str(unit.get("custom_id") or "") != expected_id:
            raise PaymentGatewayError("La referencia PayPal no coincide con la recarga HBL.")
        captures = (((unit.get("payments") or {}).get("captures")) or [])
        if not captures:
            raise PaymentGatewayError("PayPal no devolvió una captura confirmada.")
        capture = captures[0]
        if capture.get("status") != "COMPLETED":
            raise PaymentGatewayError("La captura PayPal no está completada.")
        amount_data = capture.get("amount") or unit.get("amount") or {}
        currency = str(amount_data.get("currency_code") or "").upper()
        if currency != str(deposit.payment_currency or "").upper():
            raise PaymentGatewayError("La moneda confirmada por PayPal no coincide.")
        try:
            actual = Decimal(str(amount_data.get("value")))
            expected = Decimal(deposit.payment_amount).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PaymentGatewayError("PayPal devolvió un monto inválido.") from exc
        if actual != expected:
            raise PaymentGatewayError("El monto confirmado por PayPal no coincide.")
        return str(capture.get("id") or "")

    def verify_webhook(self, *, headers, event):
        webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
        if not webhook_id:
            raise PaymentGatewayError("PAYPAL_WEBHOOK_ID no está configurado.")
        payload = {
            "auth_algo": headers.get("PAYPAL-AUTH-ALGO", ""),
            "cert_url": headers.get("PAYPAL-CERT-URL", ""),
            "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID", ""),
            "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG", ""),
            "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME", ""),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        result = self._api("/v1/notifications/verify-webhook-signature", method="POST", payload=payload)
        if result.get("verification_status") != "SUCCESS":
            raise PaymentGatewayError("Firma de webhook PayPal inválida.")
        return True


def _normalize_evm_address(value: str) -> str:
    value = (value or "").strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise PaymentGatewayError("La wallet BEP20 configurada no es válida.")
    return value


def verify_trc20_deposit(deposit: Deposit):
    """Verifica una transferencia TRC20 confirmada usando TronGrid v1 events."""
    if deposit.payment_method.kind != PaymentMethod.Kind.USDT_TRC20:
        raise PaymentGatewayError("La recarga no es TRC20.")
    txid = (deposit.txid or "").strip()
    if len(txid) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in txid):
        raise PaymentGatewayError("TXID TRC20 inválido.")
    recipient = (deposit.payment_method.destination or "").strip()
    if not recipient:
        raise PaymentGatewayError("No hay wallet TRC20 configurada para este método.")
    contract = os.getenv("USDT_TRC20_CONTRACT", "").strip()
    if not contract:
        raise PaymentGatewayError("USDT_TRC20_CONTRACT no está configurado.")
    decimals = int(os.getenv("USDT_TRC20_DECIMALS", "6"))
    base = os.getenv("TRONGRID_API_URL", "https://api.trongrid.io").rstrip("/")
    headers = {}
    api_key = os.getenv("TRONGRID_API_KEY", "").strip()
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key
    data = _json_request(f"{base}/v1/transactions/{txid}/events?only_confirmed=true", headers=headers)
    events = data.get("data") or []
    expected = Decimal(deposit.payment_amount)
    for event in events:
        if str(event.get("event_name") or "") != "Transfer":
            continue
        if str(event.get("contract_address") or "") != contract:
            continue
        result = event.get("result") or {}
        if str(result.get("to") or "") != recipient:
            continue
        try:
            actual = Decimal(str(result.get("value"))) / (Decimal(10) ** decimals)
        except (InvalidOperation, TypeError, ValueError):
            continue
        if actual >= expected:
            return {"txid": txid, "amount": str(actual), "currency": deposit.payment_currency, "network": "TRC20"}
    raise PaymentGatewayError("La transferencia TRC20 aún no está confirmada o no coincide con wallet/monto/token.")


_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _bsc_rpc(method, params):
    url = os.getenv("BSC_RPC_URL", "").strip()
    if not url:
        raise PaymentGatewayError("BSC_RPC_URL no está configurado.")
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    result = _json_request(url, method="POST", payload=payload)
    if result.get("error"):
        raise PaymentGatewayError(f"RPC BSC respondió error: {result['error']}")
    return result.get("result")


def verify_bep20_deposit(deposit: Deposit):
    """Verifica receipt, contrato, evento Transfer, receptor, monto y confirmaciones en BSC."""
    if deposit.payment_method.kind != PaymentMethod.Kind.USDT_BEP20:
        raise PaymentGatewayError("La recarga no es BEP20.")
    txid = (deposit.txid or "").strip().lower()
    if not txid.startswith("0x") or len(txid) != 66:
        raise PaymentGatewayError("TXID BEP20 inválido.")
    recipient = _normalize_evm_address(deposit.payment_method.destination)
    contract = _normalize_evm_address(os.getenv("USDT_BEP20_CONTRACT", ""))
    decimals = int(os.getenv("USDT_BEP20_DECIMALS", "18"))
    required_confirmations = max(1, int(os.getenv("BSC_REQUIRED_CONFIRMATIONS", "12")))
    receipt = _bsc_rpc("eth_getTransactionReceipt", [txid])
    if not receipt:
        raise PaymentGatewayError("La transacción BEP20 todavía no tiene receipt.")
    if str(receipt.get("status") or "").lower() != "0x1":
        raise PaymentGatewayError("La transacción BEP20 falló en la blockchain.")
    block_hex = receipt.get("blockNumber")
    if not block_hex:
        raise PaymentGatewayError("La transacción BEP20 aún no tiene bloque confirmado.")
    current_hex = _bsc_rpc("eth_blockNumber", [])
    confirmations = int(current_hex, 16) - int(block_hex, 16) + 1
    if confirmations < required_confirmations:
        raise PaymentGatewayError(f"La transacción BEP20 tiene {confirmations}/{required_confirmations} confirmaciones.")
    expected = Decimal(deposit.payment_amount)
    recipient_topic = "0x" + ("0" * 24) + recipient[2:]
    for log in receipt.get("logs") or []:
        if str(log.get("address") or "").lower() != contract:
            continue
        topics = [str(x).lower() for x in (log.get("topics") or [])]
        if len(topics) < 3 or topics[0] != _TRANSFER_TOPIC or topics[2] != recipient_topic:
            continue
        try:
            actual = Decimal(int(str(log.get("data") or "0x0"), 16)) / (Decimal(10) ** decimals)
        except (ValueError, InvalidOperation):
            continue
        if actual >= expected:
            return {"txid": txid, "amount": str(actual), "currency": deposit.payment_currency, "network": "BEP20", "confirmations": confirmations}
    raise PaymentGatewayError("La transferencia BEP20 no coincide con contrato/wallet/monto configurados.")


def verify_crypto_deposit(deposit: Deposit):
    if deposit.payment_method.kind == PaymentMethod.Kind.USDT_TRC20:
        return verify_trc20_deposit(deposit)
    if deposit.payment_method.kind == PaymentMethod.Kind.USDT_BEP20:
        return verify_bep20_deposit(deposit)
    raise PaymentGatewayError("Este método no tiene verificador automático configurado.")


def paypal_enabled():
    return _env_bool("PAYPAL_ENABLED", False)
