"""Integración server-side con Tilopay Hosted Payment Link.

HBL nunca recibe PAN/CVV. El usuario es enviado al checkout alojado por
Tilopay y, antes de acreditar saldo, HBL consulta nuevamente el detalle del
link usando las credenciales del comercio.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from .models import Deposit


class TilopayError(Exception):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class TilopayClient:
    def __init__(self, *, api_key=None, api_user=None, api_password=None, api_url=None, timeout=15):
        self.api_key = api_key or os.getenv("TILOPAY_API_KEY", "").strip()
        self.api_user = api_user or os.getenv("TILOPAY_API_USER", "").strip()
        self.api_password = api_password or os.getenv("TILOPAY_API_PASSWORD", "").strip()
        self.api_url = (api_url or os.getenv("TILOPAY_API_URL", "https://app.tilopay.com/api/v1")).rstrip("/")
        self.timeout = timeout
        if not all([self.api_key, self.api_user, self.api_password]):
            raise TilopayError("Tilopay no está configurado en el servidor.")

    def _request(self, path, *, method="GET", payload=None, token=""):
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{self.api_url}{path}", data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:700]
            raise TilopayError(f"Tilopay respondió HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TilopayError("No fue posible comunicarse correctamente con Tilopay.") from exc
        if not isinstance(data, dict):
            raise TilopayError("Tilopay devolvió una respuesta inválida.")
        return data

    def access_token(self):
        data = self._request(
            "/login",
            method="POST",
            payload={"apiuser": self.api_user, "password": self.api_password},
        )
        token = str(data.get("access_token") or data.get("token") or "").strip()
        if not token:
            raise TilopayError("Tilopay no devolvió access_token.")
        return token

    def create_payment_link(self, *, deposit: Deposit, callback_url: str, client_name=""):
        token = self.access_token()
        amount = Decimal(deposit.payment_amount).quantize(Decimal("0.01"))
        payload = {
            "key": self.api_key,
            "amount": f"{amount:.2f}",
            "currency": (deposit.payment_currency or "USD").upper(),
            "reference": str(deposit.id),
            "type": 1,
            "description": "HBL wallet credit",
            "client": (client_name or "HBL customer")[:120],
            "callback_url": callback_url,
        }
        data = self._request("/createLinkPayment", method="POST", payload=payload, token=token)
        link_id = str(data.get("id") or data.get("tilopayLinkId") or "").strip()
        checkout_url = str(data.get("url") or data.get("linkUrl") or data.get("paymentUrl") or "").strip()
        if not link_id or not checkout_url:
            raise TilopayError("Tilopay no devolvió un link de pago válido.")
        return {"id": link_id, "url": checkout_url, "raw": data}

    def payment_link_detail(self, link_id: str):
        link_id = (link_id or "").strip()
        if not link_id:
            raise TilopayError("Falta el identificador del link Tilopay.")
        token = self.access_token()
        encoded_id = urllib.parse.quote(link_id, safe="")
        encoded_key = urllib.parse.quote(self.api_key, safe="")
        return self._request(f"/getDetailLinkPayment/{encoded_id}/{encoded_key}", token=token)

    @staticmethod
    def validate_paid_detail(data, *, deposit: Deposit):
        if not isinstance(data, dict):
            raise TilopayError("Tilopay devolvió un detalle inválido.")
        detail = data.get("detail") or data.get("data") or {}
        if not isinstance(detail, dict):
            raise TilopayError("Tilopay no devolvió el detalle del link.")

        reference = str(detail.get("reference") or "").strip()
        if reference != str(deposit.id):
            raise TilopayError("La referencia Tilopay no coincide con la recarga HBL.")

        currency = str(detail.get("currency") or "").upper().strip()
        expected_currency = str(deposit.payment_currency or "").upper().strip()
        if currency != expected_currency:
            raise TilopayError("La moneda confirmada por Tilopay no coincide.")

        try:
            actual = Decimal(str(detail.get("amount"))).quantize(Decimal("0.01"))
            expected = Decimal(deposit.payment_amount).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise TilopayError("Tilopay devolvió un monto inválido.") from exc
        if actual != expected:
            raise TilopayError("El monto confirmado por Tilopay no coincide.")

        payments = data.get("payments") or []
        if isinstance(payments, dict):
            payments = [payments]
        approved = next((p for p in payments if str((p or {}).get("code") or "") == "1"), None)
        if not approved:
            raise TilopayError("El pago Tilopay todavía no está aprobado.")

        transaction_id = str(
            approved.get("tilopayOrderId")
            or approved.get("transactionId")
            or approved.get("orderNumber")
            or approved.get("id")
            or deposit.reference
            or ""
        )
        return transaction_id[:80]


def tilopay_enabled():
    return _env_bool("TILOPAY_ENABLED", False)
