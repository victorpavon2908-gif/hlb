"""Cliente mínimo para Binance Pay Merchant.

Basado en la API oficial:
- Create Order v3: POST /binancepay/openapi/v3/order
- Query Order v2: POST /binancepay/openapi/v2/order/query

Las claves se leen únicamente del entorno del servidor.
"""
import base64
import hashlib
import hmac
import json
import secrets
import string
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache


class BinancePayError(Exception):
    pass


class BinancePayClient:
    host = "https://bpay.binanceapi.com"

    def __init__(self, api_key=None, secret_key=None, timeout=12):
        self.api_key = api_key or getattr(settings, "BINANCE_PAY_API_KEY", "")
        self.secret_key = secret_key or getattr(settings, "BINANCE_PAY_SECRET_KEY", "")
        self.timeout = timeout
        if not self.api_key or not self.secret_key:
            raise BinancePayError("Binance Pay no está configurado en el servidor.")

    @staticmethod
    def _nonce():
        alphabet = string.ascii_letters
        return "".join(secrets.choice(alphabet) for _ in range(32))

    def _post(self, path, payload):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(time.time() * 1000))
        nonce = self._nonce()
        signing_payload = f"{timestamp}\n{nonce}\n{body}\n"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            signing_payload.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest().upper()
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "BinancePay-Timestamp": timestamp,
                "BinancePay-Nonce": nonce,
                "BinancePay-Certificate-SN": self.api_key,
                "BinancePay-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise BinancePayError(f"Binance Pay respondió HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BinancePayError("No fue posible comunicarse correctamente con Binance Pay.") from exc

        if data.get("status") != "SUCCESS" or data.get("code") not in {None, "000000"}:
            raise BinancePayError(data.get("errorMessage") or data.get("code") or "Binance Pay rechazó la solicitud.")
        return data

    def create_order(self, *, amount, merchant_trade_no, return_url, cancel_url, webhook_url=None, currency=None, support_currency=None):
        amount = Decimal(amount)
        payload = {
            "env": {"terminalType": "WEB"},
            "merchantTradeNo": merchant_trade_no,
            "orderAmount": str(amount),
            "currency": currency or getattr(settings, "BINANCE_PAY_CURRENCY", "USDT"),
            "returnUrl": return_url,
            "cancelUrl": cancel_url,
            "description": "HBL music membership credit",
            "goodsDetails": [
                {
                    "goodsType": "02",
                    "goodsCategory": "1000",
                    "referenceGoodsId": merchant_trade_no,
                    "goodsName": "HBL Platform Credit",
                    "goodsDetail": "Credit for HBL music membership services",
                }
            ],
            "passThroughInfo": merchant_trade_no,
        }
        support_currency = support_currency if support_currency is not None else getattr(settings, "BINANCE_PAY_SUPPORT_CURRENCY", "USDT")
        if support_currency:
            payload["supportPayCurrency"] = support_currency
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        return self._post("/binancepay/openapi/v3/order", payload)

    def query_certificates(self):
        return self._post("/binancepay/openapi/certificates", {})

    def public_certificate(self, serial):
        cache_key = f"hbl:binance:cert:{serial}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        result = self.query_certificates()
        rows = result.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("certificates") or rows.get("data") or []
        for row in rows:
            if str(row.get("certSerial", "")) == str(serial):
                public_key = row.get("certPublic", "")
                if public_key:
                    cache.set(cache_key, public_key, 21600)
                    return public_key
        raise BinancePayError("No se encontró el certificado público de Binance Pay.")

    def verify_webhook(self, *, body, timestamp, nonce, signature, certificate_sn):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
            raise BinancePayError("Falta la dependencia cryptography para validar webhooks.") from exc
        if not all([timestamp, nonce, signature, certificate_sn]):
            raise BinancePayError("Webhook Binance incompleto.")
        try:
            timestamp_ms = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise BinancePayError("Timestamp Binance inválido.") from exc
        max_age = int(getattr(settings, "BINANCE_WEBHOOK_MAX_AGE_SECONDS", 300) or 300)
        if abs(int(time.time() * 1000) - timestamp_ms) > max_age * 1000:
            raise BinancePayError("Webhook Binance fuera de la ventana de tiempo permitida.")
        public_pem = self.public_certificate(certificate_sn)
        payload = f"{timestamp}\n{nonce}\n{body}\n".encode("utf-8")
        try:
            key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
            key.verify(base64.b64decode(signature), payload, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise BinancePayError("Firma de webhook Binance inválida.") from exc
        return True


    @staticmethod
    def validate_order_data(data, *, merchant_trade_no, expected_amount, expected_currency, expected_prepay_id=None, require_paid=False):
        """Compara la orden consultada con la recarga local antes de acreditar saldo."""
        if not isinstance(data, dict):
            raise BinancePayError("Binance devolvió una orden inválida.")
        if str(data.get("merchantTradeNo") or "") != str(merchant_trade_no):
            raise BinancePayError("La referencia de la orden Binance no coincide.")
        if expected_prepay_id and str(data.get("prepayId") or "") != str(expected_prepay_id):
            raise BinancePayError("El prepayId de Binance no coincide con la orden creada.")
        if str(data.get("currency") or "").upper() != str(expected_currency or "").upper():
            raise BinancePayError("La moneda confirmada por Binance no coincide con la recarga.")
        try:
            actual_amount = Decimal(str(data.get("orderAmount")))
            expected = Decimal(str(expected_amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise BinancePayError("Binance devolvió un monto inválido.") from exc
        if actual_amount != expected:
            raise BinancePayError("El monto confirmado por Binance no coincide con la recarga.")
        if require_paid and data.get("status") != "PAID":
            raise BinancePayError("La orden Binance todavía no está pagada.")
        return True

    def query_order(self, *, merchant_trade_no=None, prepay_id=None):
        if not merchant_trade_no and not prepay_id:
            raise ValueError("merchant_trade_no o prepay_id es obligatorio")
        payload = {"prepayId": prepay_id} if prepay_id else {"merchantTradeNo": merchant_trade_no}
        return self._post("/binancepay/openapi/v2/order/query", payload)
