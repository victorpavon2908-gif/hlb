"""Integración mínima y segura con NOWPayments para depósitos USDT."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction

from .models import Deposit, PaymentMethod
from .payment_policies import USDT_OPERATION_FEE, usdt_fee_from_total, usdt_total_with_fee
from .services import approve_deposit


NOWPAYMENTS_PROVIDER = "nowpayments"
PAY_CURRENCY_BY_KIND = {
    PaymentMethod.Kind.USDT_TRC20: "usdttrc20",
    PaymentMethod.Kind.USDT_BEP20: "usdtbsc",
}
IN_PROGRESS_STATUSES = {"waiting", "confirming", "confirmed", "sending"}
PARTIAL_STATUS = "partially_paid"
REJECTED_STATUSES = {"failed", "refunded"}
FINAL_STATUS = "finished"


class NowPaymentsError(Exception):
    """Error controlado al comunicarse o conciliar un pago."""


def order_id_for(deposit_id) -> str:
    return f"hbl-deposit:{deposit_id}"


def pay_currency_for_kind(kind: str) -> str:
    try:
        return PAY_CURRENCY_BY_KIND[kind]
    except KeyError as exc:
        raise NowPaymentsError("La red seleccionada no está permitida en NOWPayments.") from exc


def _decimal(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise NowPaymentsError(f"NOWPayments devolvió {field_name} inválido.") from exc
    if not result.is_finite() or result < 0:
        raise NowPaymentsError(f"NOWPayments devolvió {field_name} inválido.")
    return result


def verify_ipn_signature(payload: dict, signature: str, secret: str | None = None) -> bool:
    """Verifica x-nowpayments-sig usando el JSON ordenado y HMAC-SHA512."""
    secret = (secret if secret is not None else settings.NOWPAYMENTS_IPN_SECRET).strip()
    signature = (signature or "").strip().lower()
    if not secret or not signature or not isinstance(payload, dict):
        return False
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


class NowPaymentsClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: int | None = None):
        self.api_key = (api_key if api_key is not None else settings.NOWPAYMENTS_API_KEY).strip()
        self.base_url = (base_url or settings.NOWPAYMENTS_API_BASE_URL).strip().rstrip("/")
        self.timeout = int(timeout or settings.NOWPAYMENTS_TIMEOUT_SECONDS)
        self.user_agent = settings.NOWPAYMENTS_USER_AGENT.strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.api_key:
            raise NowPaymentsError("NOWPayments no está configurado todavía.")

        body = None
        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(f"{self.base_url}/{path.lstrip('/')}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")[:500]
            try:
                error_data = json.loads(raw_error)
                detail = error_data.get("message") or error_data.get("detail") or error_data.get("title") or raw_error
                if error_data.get("error_code") == 1010:
                    ray_id = str(error_data.get("ray_id") or "").strip()
                    detail = "Cloudflare bloqueó la identificación del cliente HTTP"
                    if ray_id:
                        detail += f" (Ray ID: {ray_id})"
            except (json.JSONDecodeError, AttributeError):
                detail = raw_error
            raise NowPaymentsError(f"NOWPayments rechazó la solicitud ({exc.code}): {detail or 'sin detalle'}") from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise NowPaymentsError("NOWPayments no respondió a tiempo. Intenta nuevamente.") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NowPaymentsError("NOWPayments devolvió una respuesta no válida.") from exc
        if not isinstance(data, dict):
            raise NowPaymentsError("NOWPayments devolvió una respuesta inesperada.")
        return data

    def create_payment(
        self,
        *,
        price_amount: Decimal,
        pay_currency: str,
        order_id: str,
        callback_url: str,
        fee_paid_by_user: bool | None = None,
    ) -> dict:
        if fee_paid_by_user is None:
            fee_paid_by_user = settings.NOWPAYMENTS_FEE_PAID_BY_USER
        return self._request("POST", "payment", {
            "price_amount": format(Decimal(price_amount), "f"),
            "price_currency": "usd",
            "pay_currency": pay_currency,
            "ipn_callback_url": callback_url,
            "order_id": order_id,
            "order_description": "Recarga de saldo HBL",
            "is_fee_paid_by_user": bool(fee_paid_by_user),
        })

    def get_payment(self, payment_id: str) -> dict:
        payment_id = str(payment_id).strip()
        if not payment_id or not payment_id.isdigit():
            raise NowPaymentsError("El identificador de NOWPayments no es válido.")
        return self._request("GET", f"payment/{payment_id}")


def create_payment_for_deposit(deposit: Deposit, callback_url: str, client: NowPaymentsClient | None = None) -> dict:
    """Crea una orden cuyo total incluye siempre 1 USDT sobre el saldo a acreditar."""
    client = client or NowPaymentsClient()
    pay_currency = pay_currency_for_kind(deposit.payment_method.kind)
    requested_credit = _decimal(deposit.provider_price_amount, "price_amount")
    if requested_credit <= 0:
        raise NowPaymentsError("El monto del depósito debe ser mayor que cero.")

    # HBL acredita requested_credit, pero la orden remota se crea por +1 USDT.
    # NOWPayments no añade su comisión de servicio al pagador: el cargo fijo HBL
    # ya está incluido en el precio de la orden. La billetera del usuario todavía
    # puede cobrar su propia comisión de red por enviar.
    order_price = usdt_total_with_fee(requested_credit)
    data = client.create_payment(
        price_amount=order_price,
        pay_currency=pay_currency,
        order_id=order_id_for(deposit.id),
        callback_url=callback_url,
        fee_paid_by_user=False,
    )
    payment_id = str(data.get("payment_id") or "").strip()
    pay_address = str(data.get("pay_address") or "").strip()
    returned_currency = str(data.get("pay_currency") or "").strip().lower()
    returned_price = _decimal(data.get("price_amount"), "price_amount")
    pay_amount = _decimal(data.get("pay_amount"), "pay_amount")
    if not payment_id.isdigit() or not pay_address or pay_amount <= 0:
        raise NowPaymentsError("NOWPayments no devolvió instrucciones de pago completas.")
    if returned_currency != pay_currency or returned_price != order_price:
        raise NowPaymentsError("NOWPayments devolvió una moneda o monto distinto al solicitado.")

    total_extra = usdt_fee_from_total(pay_amount, requested_credit)
    if total_extra < USDT_OPERATION_FEE:
        # El cargo comercial de HBL es fijo aunque la cotización del proveedor
        # redondee el pay_amount ligeramente por debajo del price_amount.
        total_extra = USDT_OPERATION_FEE

    return {
        "payment_id": payment_id,
        "payment_status": str(data.get("payment_status") or "waiting").strip().lower(),
        "pay_address": pay_address,
        "pay_amount": pay_amount,
        "pay_currency": returned_currency,
        "price_amount": returned_price,
        "fee_amount": total_extra.quantize(Decimal("0.00000001")),
    }


def _manual_review(deposit: Deposit, provider_status: str, note: str):
    deposit.provider_status = provider_status[:32]
    deposit.status = Deposit.Status.PENDING
    deposit.notes = note
    deposit.save(update_fields=["provider_status", "provider_actual_paid", "status", "notes"])
    return deposit, False


def _partial_payment(deposit: Deposit, provider_status: str):
    """Mantiene una orden parcial activa para que pueda completarse normalmente."""
    deposit.provider_status = provider_status[:32]
    deposit.status = Deposit.Status.PROCESSING
    deposit.notes = (
        "Pago parcial recibido. La orden sigue activa y se acreditará automáticamente "
        "cuando NOWPayments confirme el total completo."
    )
    deposit.save(update_fields=["provider_status", "provider_actual_paid", "status", "notes"])
    return deposit, False


@transaction.atomic
def apply_payment_status(deposit_id, data: dict):
    """Aplica un estado consultado por API; solo ``finished`` acredita saldo."""
    deposit = (
        Deposit.objects.select_for_update()
        .select_related("payment_method")
        .get(pk=deposit_id)
    )
    if deposit.provider != NOWPAYMENTS_PROVIDER or not deposit.provider_payment_id:
        raise NowPaymentsError("La recarga no pertenece a NOWPayments.")
    if deposit.status == Deposit.Status.APPROVED:
        return deposit, False

    payment_id = str(data.get("payment_id") or "").strip()
    order_id = str(data.get("order_id") or "").strip()
    pay_currency = str(data.get("pay_currency") or "").strip().lower()
    provider_status = str(data.get("payment_status") or "").strip().lower()
    expected_currency = pay_currency_for_kind(deposit.payment_method.kind)

    if payment_id != deposit.provider_payment_id:
        return _manual_review(deposit, provider_status, "El ID del proveedor no coincide. Revisión administrativa requerida.")
    if order_id != order_id_for(deposit.id):
        return _manual_review(deposit, provider_status, "La orden informada por NOWPayments no coincide. Revisión administrativa requerida.")
    if pay_currency != expected_currency:
        return _manual_review(deposit, provider_status, "La moneda o red informada por NOWPayments no coincide. Revisión administrativa requerida.")
    try:
        price_amount = _decimal(data.get("price_amount"), "price_amount")
    except NowPaymentsError:
        return _manual_review(deposit, provider_status, "NOWPayments no informó un monto verificable. Revisión administrativa requerida.")

    expected_price = usdt_total_with_fee(Decimal(deposit.provider_price_amount))
    if price_amount != expected_price:
        return _manual_review(deposit, provider_status, "El monto informado por NOWPayments no coincide con la orden HBL. Revisión administrativa requerida.")

    actually_paid = data.get("actually_paid")
    if actually_paid not in (None, ""):
        try:
            deposit.provider_actual_paid = _decimal(actually_paid, "actually_paid")
        except NowPaymentsError:
            return _manual_review(
                deposit,
                provider_status,
                "NOWPayments informó un monto recibido inválido. Revisión administrativa requerida.",
            )

    deposit.provider_status = provider_status[:32]
    if provider_status == FINAL_STATUS:
        # Una orden puede recibir el pago después de haber aparecido expirada.
        # La consulta autenticada al proveedor permite reabrirla de forma segura.
        deposit.status = Deposit.Status.PROCESSING
        deposit.save(update_fields=["provider_status", "provider_actual_paid", "status"])
        return approve_deposit(
            deposit.id,
            transaction_id=deposit.provider_payment_id,
            notes="Pago finalizado y confirmado automáticamente por NOWPayments.",
        )
    if provider_status == PARTIAL_STATUS:
        return _partial_payment(deposit, provider_status)
    if provider_status in IN_PROGRESS_STATUSES:
        deposit.status = Deposit.Status.PROCESSING
        deposit.notes = "Pago detectado. Esperando las confirmaciones necesarias de la red."
        deposit.save(update_fields=["provider_status", "provider_actual_paid", "status", "notes"])
        return deposit, False
    if provider_status == "expired":
        deposit.status = Deposit.Status.EXPIRED
        deposit.notes = "La orden de NOWPayments expiró sin finalizarse."
        deposit.save(update_fields=["provider_status", "provider_actual_paid", "status", "notes"])
        return deposit, False
    if provider_status in REJECTED_STATUSES:
        deposit.status = Deposit.Status.REJECTED
        deposit.notes = f"NOWPayments marcó el pago como {provider_status}. No se acreditó saldo."
        deposit.save(update_fields=["provider_status", "provider_actual_paid", "status", "notes"])
        return deposit, False
    return _manual_review(deposit, provider_status, "Estado no reconocido por NOWPayments. Revisión administrativa requerida.")


def reconcile_deposit(deposit_id, client: NowPaymentsClient | None = None):
    deposit = Deposit.objects.only("provider_payment_id").get(pk=deposit_id)
    client = client or NowPaymentsClient()
    data = client.get_payment(deposit.provider_payment_id)
    return apply_payment_status(deposit_id, data)
