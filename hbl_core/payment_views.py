"""Depósitos multimoneda por NOWPayments y conciliación automática."""

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

from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig, RewardLedger
from .nowpayments import (
    NOWPAYMENTS_PROVIDER,
    NowPaymentsClient,
    NowPaymentsError,
    create_payment_for_deposit,
    order_id_for,
    reconcile_deposit,
    verify_ipn_signature,
)
from .nowpayments_catalog import decorate_method, sync_nowpayments_methods
from .payment_forms import CryptoDepositForm
from .payment_policies import CRYPTO_DEPOSIT_KINDS, USDT_OPERATION_FEE
from .services import HBLError, display_money

logger = logging.getLogger(__name__)
CRYPTO_KINDS = list(CRYPTO_DEPOSIT_KINDS)
ALLOWED_KINDS = CRYPTO_KINDS
CRYPTO_QUANT = Decimal("0.00000001")


def _payment_methods():
    return PaymentMethod.objects.filter(active=True, kind__in=ALLOWED_KINDS).order_by("sort_order", "label")


def _credit_rate_usdt():
    config = PlatformConfig.get_solo()
    row = CurrencyRate.objects.filter(code="USDT", active=True).first()
    if row and Decimal(row.rate_to_base or 0) > 0:
        return Decimal(row.rate_to_base)
    usd = CurrencyRate.objects.filter(code="USD", active=True).first()
    if usd and Decimal(usd.rate_to_base or 0) > 0:
        return Decimal(usd.rate_to_base)
    return Decimal(config.exchange_rate_usd_nio or 0)


def _callback_url(request):
    configured = settings.NOWPAYMENTS_IPN_CALLBACK_URL
    if configured:
        return configured
    return request.build_absolute_uri(reverse("hbl_nowpayments_ipn"))


def _integration_ready():
    return bool(settings.NOWPAYMENTS_API_KEY and settings.NOWPAYMENTS_IPN_SECRET)


def _decorate_deposit_for_ui(deposit, provider_data=None):
    if not deposit:
        return None
    target = Decimal(deposit.payment_amount or 0)
    received = Decimal(deposit.provider_actual_paid or 0)
    deposit.remaining_payment = max(target - received, Decimal("0")).quantize(CRYPTO_QUANT)
    deposit.is_partial_payment = (
        deposit.provider_status == "partially_paid"
        or (received > 0 and target > 0 and received < target)
    )
    deposit.operation_fee_usdt = USDT_OPERATION_FEE
    decorate_method(deposit.payment_method)
    deposit.ui_icon = deposit.payment_method.ui_icon
    deposit.ui_network = deposit.payment_method.ui_network
    deposit.ui_extra_id = (deposit.reference or "").strip()
    deposit.ui_expiration_iso = (deposit.prepay_id or "").strip()
    if isinstance(provider_data, dict):
        deposit.ui_extra_id = str(provider_data.get("payin_extra_id") or deposit.ui_extra_id or "").strip()
        deposit.ui_expiration_iso = str(provider_data.get("expiration_estimate_date") or deposit.ui_expiration_iso or "").strip()
        deposit.ui_network = str(provider_data.get("network") or deposit.ui_network or "").strip()
    return deposit


def _refresh_active_metadata(deposit):
    """Trae fecha real de expiración y memo/tag en producción."""
    if not deposit or not deposit.provider_payment_id or not _integration_ready() or settings.DEBUG:
        return _decorate_deposit_for_ui(deposit)
    try:
        data = NowPaymentsClient().get_payment(deposit.provider_payment_id)
    except NowPaymentsError:
        logger.info("No se pudo refrescar metadata de orden %s", deposit.provider_payment_id)
        return _decorate_deposit_for_ui(deposit)
    except Exception:
        logger.exception("Error refrescando metadata de orden %s", deposit.provider_payment_id)
        return _decorate_deposit_for_ui(deposit)

    update_fields = []
    expiry = str(data.get("expiration_estimate_date") or "").strip()
    extra_id = str(data.get("payin_extra_id") or "").strip()
    if expiry and expiry != (deposit.prepay_id or ""):
        deposit.prepay_id = expiry[:64]
        update_fields.append("prepay_id")
    if extra_id and extra_id != (deposit.reference or ""):
        deposit.reference = extra_id[:180]
        update_fields.append("reference")
    if update_fields:
        Deposit.objects.filter(pk=deposit.pk).update(**{name: getattr(deposit, name) for name in update_fields})
    return _decorate_deposit_for_ui(deposit, data)


@login_required
def wallet(request):
    if _integration_ready():
        try:
            sync_nowpayments_methods()
        except Exception:
            logger.exception("No se pudo sincronizar el catálogo NOWPayments al abrir la billetera")

    methods = list(_payment_methods())
    for method in methods:
        decorate_method(method)

    form = CryptoDepositForm(request.POST or None)
    form.fields["payment_method"].queryset = PaymentMethod.objects.filter(pk__in=[m.pk for m in methods]).order_by("sort_order", "label")

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        requested_usdt = Decimal(form.cleaned_data["payment_amount"])
        rate = _credit_rate_usdt()
        config = PlatformConfig.get_solo()

        if method.kind not in ALLOWED_KINDS:
            form.add_error("payment_method", "Selecciona una criptomoneda disponible en NOWPayments.")
        elif not _integration_ready():
            form.add_error(None, "Los depósitos automáticos están temporalmente fuera de servicio.")
        elif rate <= 0:
            form.add_error(None, "La tasa USDT de acreditación no está configurada correctamente.")
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
                    payment_currency=(method.currency or "CRYPTO").upper()[:12],
                    balance_rate=rate,
                    sender_network_fee_estimate=Decimal("0"),
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
                    deposit.payment_amount = remote["pay_amount"].quantize(CRYPTO_QUANT)
                    deposit.provider_fee_amount = USDT_OPERATION_FEE
                    deposit.reference = str(remote.get("payin_extra_id") or "")[:180]
                    deposit.prepay_id = str(remote.get("expiration_estimate_date") or "")[:64]
                    deposit.notes = "Orden creada. Esperando que NOWPayments confirme el pago."
                    deposit.save()
                except (NowPaymentsError, IntegrityError) as exc:
                    logger.warning("No se pudo crear la orden NOWPayments para el usuario %s: %s", request.user.pk, exc)
                    form.add_error(None, str(exc) if isinstance(exc, NowPaymentsError) else "No se pudo guardar la orden de pago. Intenta nuevamente.")
                else:
                    messages.success(
                        request,
                        f"Orden creada: acreditarás {requested_usdt} USDT + 1 USDT de cargo HBL. Paga el equivalente exacto mostrado en {deposit.payment_currency}.",
                    )
                    return redirect("hbl_wallet")

    deposits = list(Deposit.objects.filter(user=request.user).select_related("payment_method")[:12])
    for item in deposits:
        _decorate_deposit_for_ui(item)

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
    _refresh_active_metadata(active_payment)

    ledger = RewardLedger.objects.filter(user=request.user)[:15]
    config = PlatformConfig.get_solo()
    usd_rate_row = CurrencyRate.objects.filter(code="USD", active=True).first()
    usd_rate = Decimal(usd_rate_row.rate_to_base) if usd_rate_row else Decimal(config.exchange_rate_usd_nio or 0)
    minimum_deposit_usdt = Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT) if settings.NOWPAYMENTS_TEST_MODE else Decimal(config.minimum_deposit_usd)
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
        "featured_methods": methods[:12],
        "methods_count": len(methods),
        "deposits": deposits,
        "active_payment": active_payment,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_usdt": minimum_deposit_usdt,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
        "nowpayments_ready": _integration_ready(),
        "nowpayments_test_mode": settings.NOWPAYMENTS_TEST_MODE,
        "usdt_operation_fee": USDT_OPERATION_FEE,
    })


@login_required
@require_POST
def recheck_crypto_deposits(request):
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
    expired = 0
    for deposit_id in pending_ids:
        try:
            obj, changed = reconcile_deposit(deposit_id)
        except Exception:
            logger.exception("Falló la consulta de la recarga NOWPayments %s", deposit_id)
            continue
        if obj.status == Deposit.Status.APPROVED and changed:
            approved += 1
        if obj.status == Deposit.Status.EXPIRED:
            expired += 1

    processing = Deposit.objects.filter(
        user=request.user,
        provider=NOWPAYMENTS_PROVIDER,
        status__in=[Deposit.Status.PROCESSING, Deposit.Status.PENDING],
        payment_method__kind__in=CRYPTO_KINDS,
    ).count()
    return JsonResponse({"ok": True, "checked": len(pending_ids), "approved": approved, "expired": expired, "processing": processing})


@csrf_exempt
@require_POST
def nowpayments_ipn(request):
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
        deposit = Deposit.objects.get(provider=NOWPAYMENTS_PROVIDER, provider_payment_id=payment_id)
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
