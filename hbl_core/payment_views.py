"""Depósitos USDT por NOWPayments y revisión administrativa de respaldo."""

import json
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import DepositForm
from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig, RewardLedger
from .nowpayments import (
    NOWPAYMENTS_PROVIDER,
    NowPaymentsError,
    create_payment_for_deposit,
    order_id_for,
    reconcile_deposit,
    verify_ipn_signature,
)
from .payment_policies import CRYPTO_DEPOSIT_KINDS
from .services import HBLError, display_money


logger = logging.getLogger(__name__)
CRYPTO_KINDS = list(CRYPTO_DEPOSIT_KINDS)
ALLOWED_KINDS = CRYPTO_KINDS


def _payment_methods():
    return (
        PaymentMethod.objects
        .filter(active=True, kind__in=ALLOWED_KINDS)
        .order_by("sort_order", "label")
    )


def _rate_for(method):
    config = PlatformConfig.get_solo()
    code = (method.currency or config.base_currency_code).upper()
    if code == config.base_currency_code.upper():
        return Decimal("1")
    row = CurrencyRate.objects.filter(code=code, active=True).first()
    return Decimal(row.rate_to_base) if row else Decimal(method.balance_rate or 0)


def _callback_url(request):
    configured = settings.NOWPAYMENTS_IPN_CALLBACK_URL
    if configured:
        return configured
    return request.build_absolute_uri(reverse("hbl_nowpayments_ipn"))


def _integration_ready():
    return bool(settings.NOWPAYMENTS_API_KEY and settings.NOWPAYMENTS_IPN_SECRET)


@login_required
def wallet(request):
    form = DepositForm(request.POST or None)
    methods = _payment_methods()
    form.fields["payment_method"].queryset = methods

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        requested_usdt = Decimal(form.cleaned_data["payment_amount"])
        rate = _rate_for(method)
        config = PlatformConfig.get_solo()

        if method.kind not in ALLOWED_KINDS:
            form.add_error("payment_method", "Solo se aceptan depósitos USDT por TRC20 o BEP20.")
        elif not _integration_ready():
            form.add_error(None, "Los depósitos automáticos están temporalmente fuera de servicio. Administración debe configurar NOWPayments.")
        elif rate <= 0:
            form.add_error("payment_method", "Este método no tiene una tasa de conversión válida.")
        else:
            credit_amount = (requested_usdt * rate).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                form.add_error("payment_amount", "El monto convertido debe ser mayor que cero.")
            else:
                deposit = Deposit(
                    user=request.user,
                    payment_method=method,
                    amount=credit_amount,
                    currency=config.base_currency_code.upper(),
                    payment_amount=requested_usdt,
                    payment_currency="USDT",
                    balance_rate=rate,
                    sender_network_fee_estimate=method.sender_network_fee_estimate,
                    status=Deposit.Status.PROCESSING,
                    provider=NOWPAYMENTS_PROVIDER,
                    provider_price_amount=requested_usdt,
                    notes="Creando orden de depósito en NOWPayments.",
                )
                try:
                    remote = create_payment_for_deposit(deposit, _callback_url(request))
                    deposit.provider_payment_id = remote["payment_id"]
                    deposit.provider_status = remote["payment_status"]
                    deposit.pay_address = remote["pay_address"]
                    deposit.payment_amount = remote["pay_amount"].quantize(Decimal("0.00000001"))
                    deposit.provider_fee_amount = remote["fee_amount"]
                    deposit.notes = "Orden creada. Esperando que NOWPayments confirme el pago como finalizado."
                    deposit.save()
                except (NowPaymentsError, IntegrityError) as exc:
                    logger.warning("No se pudo crear la orden NOWPayments para el usuario %s: %s", request.user.pk, exc)
                    form.add_error(None, str(exc) if isinstance(exc, NowPaymentsError) else "No se pudo guardar la orden de pago. Intenta nuevamente.")
                else:
                    messages.success(
                        request,
                        "Orden creada. Envía exactamente el monto indicado a la dirección generada; HBL validará el depósito automáticamente.",
                    )
                    return redirect("hbl_wallet")

    deposits = Deposit.objects.filter(user=request.user).select_related("payment_method")[:12]
    active_payment = (
        Deposit.objects.filter(
            user=request.user,
            provider=NOWPAYMENTS_PROVIDER,
            status__in=[Deposit.Status.PROCESSING, Deposit.Status.PENDING],
        )
        .exclude(pay_address="")
        .select_related("payment_method")
        .first()
    )
    ledger = RewardLedger.objects.filter(user=request.user)[:15]
    config = PlatformConfig.get_solo()
    usd_rate_row = CurrencyRate.objects.filter(code="USD", active=True).first()
    usd_rate = Decimal(usd_rate_row.rate_to_base) if usd_rate_row else Decimal(config.exchange_rate_usd_nio or 0)
    minimum_deposit_usdt = (
        Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
        if settings.NOWPAYMENTS_TEST_MODE
        else Decimal(config.minimum_deposit_usd)
    )
    minimum_deposit_nio = (minimum_deposit_usdt * usd_rate).quantize(Decimal("0.01"))
    try:
        minimum_withdraw_preferred = display_money(
            config.withdrawal_min,
            getattr(request.user, "preferred_currency", "USD") or "USD",
        )
    except HBLError:
        minimum_withdraw_preferred = Decimal("0")

    return render(request, "hbl/wallet.html", {
        "form": form,
        "methods": methods,
        "deposits": deposits,
        "active_payment": active_payment,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_usdt": minimum_deposit_usdt,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
        "nowpayments_ready": _integration_ready(),
        "nowpayments_test_mode": settings.NOWPAYMENTS_TEST_MODE,
    })


@login_required
@require_POST
def recheck_crypto_deposits(request):
    """Consulta a NOWPayments por las órdenes del usuario aún no finalizadas."""
    pending_ids = list(
        Deposit.objects.filter(
            user=request.user,
            provider=NOWPAYMENTS_PROVIDER,
            status__in=[Deposit.Status.PROCESSING, Deposit.Status.PENDING],
            payment_method__kind__in=CRYPTO_KINDS,
        )
        .exclude(provider_payment_id="")
        .order_by("submitted_at")
        .values_list("id", flat=True)[:5]
    )

    approved = 0
    for deposit_id in pending_ids:
        try:
            obj, changed = reconcile_deposit(deposit_id)
        except Exception:
            logger.exception("Falló la consulta de la recarga NOWPayments %s", deposit_id)
            continue
        if obj.status == Deposit.Status.APPROVED and changed:
            approved += 1

    processing = Deposit.objects.filter(
        user=request.user,
        provider=NOWPAYMENTS_PROVIDER,
        status=Deposit.Status.PROCESSING,
        payment_method__kind__in=CRYPTO_KINDS,
    ).count()
    return JsonResponse({
        "ok": True,
        "checked": len(pending_ids),
        "approved": approved,
        "processing": processing,
    })


@csrf_exempt
@require_POST
def nowpayments_ipn(request):
    """IPN público: autentica la firma y reconfirma el pago mediante la API."""
    if not settings.NOWPAYMENTS_IPN_SECRET:
        return JsonResponse({"ok": False, "error": "IPN no configurado"}, status=503)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    signature = request.headers.get("x-nowpayments-sig", "")
    if not verify_ipn_signature(payload, signature):
        return JsonResponse({"ok": False, "error": "Firma inválida"}, status=401)

    payment_id = str(payload.get("payment_id") or "").strip()
    try:
        deposit = Deposit.objects.get(
            provider=NOWPAYMENTS_PROVIDER,
            provider_payment_id=payment_id,
        )
    except Deposit.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Pago desconocido"}, status=404)
    if str(payload.get("order_id") or "").strip() != order_id_for(deposit.id):
        return JsonResponse({"ok": False, "error": "Orden inválida"}, status=400)

    try:
        obj, changed = reconcile_deposit(deposit.id)
    except NowPaymentsError as exc:
        logger.warning("No se pudo reconciliar el IPN %s: %s", payment_id, exc)
        return JsonResponse({"ok": False, "error": "No fue posible reconfirmar el pago"}, status=503)
    except Exception:
        logger.exception("Error inesperado reconciliando el IPN %s", payment_id)
        return JsonResponse({"ok": False, "error": "Error de conciliación"}, status=503)

    return JsonResponse({"ok": True, "status": obj.status, "credited": bool(changed)})
