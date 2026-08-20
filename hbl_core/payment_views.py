"""Vistas de recarga USDT con validación automática en blockchain."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .crypto_payments import verify_and_credit_deposit
from .forms import DepositForm
from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig, RewardLedger
from .services import HBLError, display_money


CRYPTO_KINDS = [
    PaymentMethod.Kind.USDT_TRC20,
    PaymentMethod.Kind.USDT_BEP20,
]


def _crypto_methods():
    """Únicamente USDT TRC20 y BEP20 pueden aparecer como recarga."""
    return (
        PaymentMethod.objects
        .filter(active=True, kind__in=CRYPTO_KINDS)
        .exclude(destination="")
        .order_by("sort_order", "label")
    )


def _rate_for(method):
    config = PlatformConfig.get_solo()
    code = (method.currency or config.base_currency_code).upper()
    if code == config.base_currency_code.upper():
        return Decimal("1")
    row = CurrencyRate.objects.filter(code=code, active=True).first()
    return Decimal(row.rate_to_base) if row else Decimal(method.balance_rate or 0)


def _deposit_message(request, deposit):
    if deposit.status == Deposit.Status.APPROVED:
        messages.success(
            request,
            "Pago confirmado automáticamente en blockchain. Tu saldo HBL ya fue acreditado.",
        )
    elif deposit.status == Deposit.Status.PROCESSING:
        messages.info(
            request,
            "TXID recibido. HBL está esperando confirmaciones/finalidad de la blockchain; esta pantalla lo volverá a comprobar automáticamente.",
        )
    else:
        messages.warning(
            request,
            "El TXID no pudo aprobarse automáticamente. La recarga quedó para revisión y el saldo no fue acreditado.",
        )


@login_required
def wallet(request):
    form = DepositForm(request.POST or None, request.FILES or None)
    crypto_methods = _crypto_methods()
    form.fields["payment_method"].queryset = crypto_methods

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        payment_amount = form.cleaned_data["payment_amount"]
        rate = _rate_for(method)
        config = PlatformConfig.get_solo()

        if method.kind not in CRYPTO_KINDS:
            form.add_error("payment_method", "Solo se permiten depósitos USDT por TRC20 o BEP20.")
        elif not method.destination:
            form.add_error("payment_method", "La dirección receptora de esta red no está configurada.")
        elif rate <= 0:
            form.add_error("payment_method", "Este método no tiene una tasa de conversión válida.")
        else:
            credit_amount = (Decimal(payment_amount) * rate).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                form.add_error("payment_amount", "El monto convertido debe ser mayor que cero.")
            else:
                try:
                    deposit = Deposit.objects.create(
                        user=request.user,
                        payment_method=method,
                        amount=credit_amount,
                        currency=config.base_currency_code.upper(),
                        payment_amount=payment_amount,
                        payment_currency="USDT",
                        balance_rate=rate,
                        status=Deposit.Status.PROCESSING,
                        txid=form.cleaned_data.get("txid", ""),
                        reference=form.cleaned_data.get("reference", ""),
                        proof=form.cleaned_data.get("proof"),
                        notes="TXID recibido. Validación automática de blockchain iniciada.",
                    )
                except IntegrityError:
                    form.add_error("txid", "Ese TXID ya fue registrado anteriormente.")
                else:
                    # El signal post_save inicia la validación al crear la fila. Refrescamos
                    # el resultado para informar si ya aprobó o si aún espera confirmaciones.
                    deposit.refresh_from_db()
                    _deposit_message(request, deposit)
                    return redirect("hbl_wallet")

    deposits = Deposit.objects.filter(user=request.user).select_related("payment_method")[:12]
    ledger = RewardLedger.objects.filter(user=request.user)[:15]
    config = PlatformConfig.get_solo()
    usd_rate_row = CurrencyRate.objects.filter(code="USD", active=True).first()
    usd_rate = Decimal(usd_rate_row.rate_to_base) if usd_rate_row else Decimal(config.exchange_rate_usd_nio or 0)
    minimum_deposit_nio = (Decimal(config.minimum_deposit_usd) * usd_rate).quantize(Decimal("0.01"))
    try:
        minimum_withdraw_preferred = display_money(
            config.withdrawal_min,
            getattr(request.user, "preferred_currency", "USD") or "USD",
        )
    except HBLError:
        minimum_withdraw_preferred = Decimal("0")

    return render(request, "hbl/wallet.html", {
        "form": form,
        "methods": crypto_methods,
        "deposits": deposits,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
    })


@login_required
@require_POST
def recheck_crypto_deposits(request):
    """Reintenta las recargas del usuario que aún esperan confirmaciones."""
    pending_ids = list(
        Deposit.objects.filter(
            user=request.user,
            status=Deposit.Status.PROCESSING,
            payment_method__kind__in=CRYPTO_KINDS,
        )
        .exclude(txid="")
        .order_by("submitted_at")
        .values_list("id", flat=True)[:5]
    )

    approved = 0
    for deposit_id in pending_ids:
        try:
            obj, changed = verify_and_credit_deposit(deposit_id)
        except Exception:
            continue
        if obj.status == Deposit.Status.APPROVED and changed:
            approved += 1

    processing = Deposit.objects.filter(
        user=request.user,
        status=Deposit.Status.PROCESSING,
        payment_method__kind__in=CRYPTO_KINDS,
    ).count()

    return JsonResponse({
        "ok": True,
        "checked": len(pending_ids),
        "approved": approved,
        "processing": processing,
    })
