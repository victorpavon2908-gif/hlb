"""Vistas de recarga unificadas.

Mantiene los métodos manuales existentes y agrega:
- Binance Pay Merchant (checkout automático existente)
- PayPal Checkout Orders v2
- USDT TRC20 con validación TronGrid
- USDT BEP20 con validación JSON-RPC BSC

El saldo siempre se acredita a través de services.approve_deposit().
"""
import json
import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .binance_pay import BinancePayClient, BinancePayError
from .forms import DepositForm
from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig, RewardLedger
from .payment_gateways import PayPalClient, PaymentGatewayError, paypal_enabled, verify_crypto_deposit
from .services import HBLError, approve_deposit, display_money


def _merchant_trade_no():
    return f"HBL{timezone.now():%y%m%d%H%M%S}{secrets.token_hex(6)}"[:32]


def _rate_for(method):
    config = PlatformConfig.get_solo()
    code = (method.currency or config.base_currency_code).upper()
    if code == config.base_currency_code.upper():
        return Decimal("1")
    row = CurrencyRate.objects.filter(code=code, active=True).first()
    return Decimal(row.rate_to_base) if row else Decimal(method.balance_rate or 0)


def _paypal_method(method):
    return (method.network or "").strip().upper() == "PAYPAL"


def _tilopay_method(method):
    return (method.network or "").strip().upper().startswith("TILOPAY")


def _crypto_auto_method(method):
    return method.kind in {PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20}


def _create_local_deposit(*, request, method, payment_amount, rate, status=Deposit.Status.PENDING, **extra):
    config = PlatformConfig.get_solo()
    credit_amount = (Decimal(payment_amount) * Decimal(rate)).quantize(Decimal("0.01"))
    return Deposit.objects.create(
        user=request.user,
        payment_method=method,
        amount=credit_amount,
        currency=config.base_currency_code.upper(),
        payment_amount=payment_amount,
        payment_currency=(method.currency or config.base_currency_code).upper(),
        balance_rate=rate,
        status=status,
        txid=extra.get("txid", ""),
        reference=extra.get("reference", ""),
        proof=extra.get("proof"),
        merchant_trade_no=extra.get("merchant_trade_no"),
        notes=extra.get("notes", ""),
    )


@login_required
def wallet(request):
    form = DepositForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        payment_amount = form.cleaned_data["payment_amount"]
        rate = _rate_for(method)
        config = PlatformConfig.get_solo()

        if rate <= 0:
            form.add_error("payment_method", "Este método no tiene una tasa de conversión válida.")
        else:
            credit_amount = (Decimal(payment_amount) * rate).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                form.add_error("payment_amount", "El monto convertido debe ser mayor que cero.")

            elif method.kind == PaymentMethod.Kind.BINANCE_PAY:
                if not getattr(settings, "BINANCE_PAY_ENABLED", False):
                    form.add_error("payment_method", "Binance Pay automático aún no está habilitado en el servidor.")
                else:
                    trade_no = _merchant_trade_no()
                    deposit = _create_local_deposit(
                        request=request,
                        method=method,
                        payment_amount=payment_amount,
                        rate=rate,
                        status=Deposit.Status.PROCESSING,
                        merchant_trade_no=trade_no,
                    )
                    try:
                        base = request.build_absolute_uri("/").rstrip("/")
                        result = BinancePayClient().create_order(
                            amount=payment_amount,
                            merchant_trade_no=trade_no,
                            return_url=f"{base}{reverse('hbl_binance_return')}?order={trade_no}",
                            cancel_url=f"{base}{reverse('hbl_wallet')}?payment=cancelled",
                            webhook_url=f"{base}{reverse('hbl_binance_webhook')}",
                            currency=method.currency,
                            support_currency=method.currency,
                        )
                        data = result.get("data") or {}
                        deposit.prepay_id = data.get("prepayId", "")
                        deposit.checkout_url = data.get("checkoutUrl", "")
                        deposit.save(update_fields=["prepay_id", "checkout_url"])
                        if not deposit.checkout_url:
                            raise BinancePayError("Binance no devolvió checkoutUrl.")
                        return redirect(deposit.checkout_url)
                    except BinancePayError as exc:
                        deposit.status = Deposit.Status.PENDING
                        deposit.notes = f"Error al crear orden Binance: {exc}"
                        deposit.save(update_fields=["status", "notes"])
                        form.add_error(None, "No se pudo crear la orden de Binance Pay. Intenta de nuevo o usa otro método.")

            elif _paypal_method(method):
                if not paypal_enabled():
                    form.add_error("payment_method", "PayPal automático aún no está habilitado en el servidor.")
                else:
                    deposit = _create_local_deposit(
                        request=request,
                        method=method,
                        payment_amount=payment_amount,
                        rate=rate,
                        status=Deposit.Status.PROCESSING,
                    )
                    try:
                        base = request.build_absolute_uri("/").rstrip("/")
                        result = PayPalClient().create_order(
                            deposit=deposit,
                            return_url=f"{base}{reverse('hbl_paypal_return')}",
                            cancel_url=f"{base}{reverse('hbl_paypal_cancel')}?deposit={deposit.id}",
                        )
                        order_id = str(result.get("id") or "")
                        checkout = PayPalClient.approval_url(result)
                        if not order_id or not checkout:
                            raise PaymentGatewayError("PayPal no devolvió una orden/URL de aprobación válida.")
                        deposit.reference = order_id
                        deposit.checkout_url = checkout
                        deposit.save(update_fields=["reference", "checkout_url"])
                        return redirect(checkout)
                    except PaymentGatewayError as exc:
                        deposit.status = Deposit.Status.PENDING
                        deposit.notes = f"Error al crear orden PayPal: {exc}"
                        deposit.save(update_fields=["status", "notes"])
                        form.add_error(None, "No se pudo crear la orden PayPal. Intenta de nuevo o usa otro método.")

            elif _crypto_auto_method(method):
                try:
                    deposit = _create_local_deposit(
                        request=request,
                        method=method,
                        payment_amount=payment_amount,
                        rate=rate,
                        status=Deposit.Status.PROCESSING,
                        txid=form.cleaned_data.get("txid", ""),
                        reference=form.cleaned_data.get("reference", ""),
                        proof=form.cleaned_data.get("proof"),
                    )
                except IntegrityError:
                    form.add_error("txid", "Ese TXID ya fue registrado anteriormente.")
                else:
                    try:
                        verified = verify_crypto_deposit(deposit)
                        approve_deposit(
                            deposit.id,
                            transaction_id=deposit.txid,
                            notes=f"Confirmado automáticamente en blockchain: {json.dumps(verified, ensure_ascii=False)}",
                        )
                        messages.success(request, "Transacción confirmada en blockchain. Tu saldo fue acreditado automáticamente.")
                    except (PaymentGatewayError, HBLError) as exc:
                        deposit.notes = f"Pendiente de confirmación automática: {exc}"
                        deposit.save(update_fields=["notes"])
                        messages.info(request, "Recarga registrada. La blockchain todavía no cumple todas las confirmaciones; puedes verificarla nuevamente desde el historial.")
                    return redirect("hbl_wallet")

            elif _tilopay_method(method):
                # No se procesan datos de tarjeta dentro de HBL. Hasta disponer de
                # credenciales + contrato/API exacta de la cuenta Tilopay, el método
                # permanece como registro manual y nunca se autoacredita.
                try:
                    _create_local_deposit(
                        request=request,
                        method=method,
                        payment_amount=payment_amount,
                        rate=rate,
                        txid=form.cleaned_data.get("txid", ""),
                        reference=form.cleaned_data.get("reference", ""),
                        proof=form.cleaned_data.get("proof"),
                        notes="Tilopay pendiente de checkout/API merchant. No autoacreditar sin confirmación del proveedor.",
                    )
                except IntegrityError:
                    form.add_error("txid", "Ese TXID ya fue registrado anteriormente.")
                else:
                    messages.success(request, "Solicitud Tilopay registrada. La acreditación permanecerá pendiente hasta confirmar la integración merchant.")
                    return redirect("hbl_wallet")

            else:
                try:
                    _create_local_deposit(
                        request=request,
                        method=method,
                        payment_amount=payment_amount,
                        rate=rate,
                        txid=form.cleaned_data.get("txid", ""),
                        reference=form.cleaned_data.get("reference", ""),
                        proof=form.cleaned_data.get("proof"),
                    )
                except IntegrityError:
                    form.add_error("txid", "Ese TXID ya fue registrado anteriormente.")
                else:
                    messages.success(request, "Recarga enviada para revisión.")
                    return redirect("hbl_wallet")

    methods = PaymentMethod.objects.filter(active=True)
    deposits = Deposit.objects.filter(user=request.user).select_related("payment_method")[:12]
    ledger = RewardLedger.objects.filter(user=request.user)[:15]
    config = PlatformConfig.get_solo()
    usd_rate_row = CurrencyRate.objects.filter(code="USD", active=True).first()
    usd_rate = Decimal(usd_rate_row.rate_to_base) if usd_rate_row else Decimal(config.exchange_rate_usd_nio or 0)
    minimum_deposit_nio = (Decimal(config.minimum_deposit_usd) * usd_rate).quantize(Decimal("0.01"))
    try:
        minimum_withdraw_preferred = display_money(config.withdrawal_min, getattr(request.user, "preferred_currency", "USD") or "USD")
    except HBLError:
        minimum_withdraw_preferred = Decimal("0")
    return render(request, "hbl/wallet.html", {
        "form": form,
        "methods": methods,
        "deposits": deposits,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
    })


@login_required
@require_GET
def paypal_return(request):
    order_id = (request.GET.get("token") or "").strip()
    if not order_id:
        messages.error(request, "PayPal no devolvió el identificador de la orden.")
        return redirect("hbl_wallet")
    deposit = get_object_or_404(Deposit, user=request.user, reference=order_id, payment_method__network__iexact="PAYPAL")
    if deposit.status == Deposit.Status.APPROVED:
        messages.info(request, "Ese pago PayPal ya estaba acreditado.")
        return redirect("hbl_wallet")
    try:
        client = PayPalClient()
        result = client.capture_order(order_id, deposit_id=str(deposit.id))
        capture_id = client.validate_completed_order(result, deposit=deposit)
        approve_deposit(deposit.id, transaction_id=capture_id, notes="Confirmado por PayPal Orders v2 capture")
        messages.success(request, "Pago confirmado por PayPal. Tu saldo fue actualizado.")
    except PaymentGatewayError as exc:
        # Si el capture respondió ambiguo, consultar la orden antes de decidir.
        try:
            current = PayPalClient().get_order(order_id)
            capture_id = PayPalClient.validate_completed_order(current, deposit=deposit)
            approve_deposit(deposit.id, transaction_id=capture_id, notes="Confirmado por consulta directa PayPal")
            messages.success(request, "Pago confirmado por PayPal. Tu saldo fue actualizado.")
        except (PaymentGatewayError, HBLError):
            deposit.notes = f"PayPal pendiente/no confirmado: {exc}"
            deposit.save(update_fields=["notes"])
            messages.warning(request, "PayPal todavía no pudo confirmar el pago. No se acreditó saldo.")
    except HBLError as exc:
        messages.error(request, str(exc))
    return redirect("hbl_wallet")


@login_required
@require_GET
def paypal_cancel(request):
    deposit_id = request.GET.get("deposit")
    if deposit_id:
        deposit = Deposit.objects.filter(pk=deposit_id, user=request.user, status=Deposit.Status.PROCESSING).first()
        if deposit:
            deposit.status = Deposit.Status.REJECTED
            deposit.notes = "Checkout PayPal cancelado por el usuario."
            deposit.processed_at = timezone.now()
            deposit.save(update_fields=["status", "notes", "processed_at"])
    messages.info(request, "Pago PayPal cancelado. No se acreditó saldo.")
    return redirect("hbl_wallet")


@csrf_exempt
@require_POST
def paypal_webhook(request):
    try:
        event = json.loads(request.body.decode("utf-8"))
        client = PayPalClient()
        client.verify_webhook(headers=request.headers, event=event)
        event_type = str(event.get("event_type") or "")
        if event_type != "PAYMENT.CAPTURE.COMPLETED":
            return JsonResponse({"ok": True})
        resource = event.get("resource") or {}
        order_id = (((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id") or "")
        if not order_id:
            return JsonResponse({"ok": False, "error": "order_id missing"}, status=400)
        deposit = Deposit.objects.filter(reference=order_id, payment_method__network__iexact="PAYPAL").first()
        if not deposit:
            return JsonResponse({"ok": False, "error": "deposit not found"}, status=404)
        order = client.get_order(order_id)
        capture_id = client.validate_completed_order(order, deposit=deposit)
        approve_deposit(deposit.id, transaction_id=capture_id, notes="Confirmado por webhook PayPal verificado + consulta Orders v2")
        return JsonResponse({"ok": True})
    except (json.JSONDecodeError, PaymentGatewayError, HBLError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)[:180]}, status=400)


@login_required
@require_POST
def verify_crypto(request, deposit_id):
    deposit = get_object_or_404(
        Deposit.objects.select_related("payment_method"),
        pk=deposit_id,
        user=request.user,
    )
    if deposit.status == Deposit.Status.APPROVED:
        messages.info(request, "Esta recarga ya estaba acreditada.")
        return redirect("hbl_wallet")
    if deposit.status not in {Deposit.Status.PENDING, Deposit.Status.PROCESSING}:
        messages.error(request, "Esta recarga ya no puede verificarse.")
        return redirect("hbl_wallet")
    try:
        verified = verify_crypto_deposit(deposit)
        approve_deposit(
            deposit.id,
            transaction_id=deposit.txid,
            notes=f"Confirmado automáticamente en blockchain: {json.dumps(verified, ensure_ascii=False)}",
        )
        messages.success(request, "Blockchain confirmada. Saldo acreditado.")
    except (PaymentGatewayError, HBLError) as exc:
        deposit.notes = f"Verificación automática pendiente: {exc}"
        deposit.save(update_fields=["notes"])
        messages.warning(request, str(exc))
    return redirect("hbl_wallet")
