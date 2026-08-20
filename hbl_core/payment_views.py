"""Vistas de recarga: TRC20/BEP20 automáticos y transferencia bancaria manual."""
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
ALLOWED_KINDS = CRYPTO_KINDS + [PaymentMethod.Kind.BANK]


def _payment_methods():
    """Solo los tres métodos permitidos pueden aparecer en la app."""
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


def _deposit_message(request, deposit):
    if deposit.status == Deposit.Status.APPROVED:
        messages.success(
            request,
            "Pago confirmado automáticamente en blockchain. Tu saldo HBL ya fue acreditado.",
        )
    elif deposit.status == Deposit.Status.PROCESSING:
        messages.info(
            request,
            "TXID recibido. HBL está esperando confirmaciones/finalidad de la blockchain.",
        )
    else:
        messages.warning(
            request,
            "El TXID no pudo aprobarse automáticamente. La recarga quedó para revisión y el saldo no fue acreditado.",
        )


@login_required
def wallet(request):
    form = DepositForm(request.POST or None, request.FILES or None)
    methods = _payment_methods()
    form.fields["payment_method"].queryset = methods
    form.fields["txid"].label = "TXID (obligatorio para TRC20/BEP20)"
    form.fields["proof"].label = "Comprobante (obligatorio para transferencia bancaria)"

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        payment_amount = form.cleaned_data["payment_amount"]
        rate = _rate_for(method)
        config = PlatformConfig.get_solo()

        if method.kind not in ALLOWED_KINDS:
            form.add_error("payment_method", "Este método de pago no está permitido.")
        elif method.kind in CRYPTO_KINDS and not method.destination:
            form.add_error("payment_method", "La dirección receptora de esta red no está configurada.")
        elif method.kind == PaymentMethod.Kind.BANK and not method.destination:
            form.add_error(
                "payment_method",
                "La cuenta bancaria todavía no está configurada. Administración debe agregar el destino antes de recibir transferencias.",
            )
        elif rate <= 0:
            form.add_error("payment_method", "Este método no tiene una tasa de conversión válida.")
        else:
            credit_amount = (Decimal(payment_amount) * rate).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                form.add_error("payment_amount", "El monto convertido debe ser mayor que cero.")
            elif method.kind == PaymentMethod.Kind.BANK:
                try:
                    Deposit.objects.create(
                        user=request.user,
                        payment_method=method,
                        amount=credit_amount,
                        currency=config.base_currency_code.upper(),
                        payment_amount=payment_amount,
                        payment_currency=(method.currency or config.base_currency_code).upper(),
                        balance_rate=rate,
                        status=Deposit.Status.PENDING,
                        reference=form.cleaned_data.get("reference", ""),
                        proof=form.cleaned_data.get("proof"),
                        notes="Transferencia bancaria pendiente de revisión administrativa.",
                    )
                except IntegrityError:
                    form.add_error(None, "No fue posible registrar la transferencia. Intenta nuevamente.")
                else:
                    messages.success(
                        request,
                        "Transferencia bancaria registrada. Administración revisará el comprobante antes de acreditar el saldo.",
                    )
                    return redirect("hbl_wallet")
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
        "methods": methods,
        "deposits": deposits,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
    })


@login_required
@require_POST
def recheck_crypto_deposits(request):
    """Reintenta únicamente recargas cripto que aún esperan confirmaciones."""
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
