"""Vistas de recarga manuales.

HBL no usa pasarelas automáticas en este flujo. El usuario registra la
transferencia, adjunta un comprobante y la recarga queda PENDING hasta que
administración la aprueba o rechaza desde HBL Control.
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import redirect, render

from .forms import DepositForm
from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig, RewardLedger
from .services import HBLError, display_money


AUTOMATIC_METHODS = (
    Q(kind=PaymentMethod.Kind.BINANCE_PAY)
    | Q(network__iexact="PAYPAL")
    | Q(network__istartswith="TILOPAY")
)


def _manual_methods():
    """Métodos visibles en la billetera: únicamente recargas manuales."""
    return (
        PaymentMethod.objects
        .filter(active=True)
        .exclude(AUTOMATIC_METHODS)
        .order_by("sort_order", "label")
    )


def _rate_for(method):
    config = PlatformConfig.get_solo()
    code = (method.currency or config.base_currency_code).upper()
    if code == config.base_currency_code.upper():
        return Decimal("1")
    row = CurrencyRate.objects.filter(code=code, active=True).first()
    return Decimal(row.rate_to_base) if row else Decimal(method.balance_rate or 0)


@login_required
def wallet(request):
    form = DepositForm(request.POST or None, request.FILES or None)
    manual_methods = _manual_methods()
    form.fields["payment_method"].queryset = manual_methods

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        payment_amount = form.cleaned_data["payment_amount"]
        proof = form.cleaned_data.get("proof")
        rate = _rate_for(method)
        config = PlatformConfig.get_solo()

        if not proof:
            form.add_error(
                "proof",
                "Debes subir un comprobante para que administración pueda validar la transferencia.",
            )
        elif rate <= 0:
            form.add_error("payment_method", "Este método no tiene una tasa de conversión válida.")
        else:
            credit_amount = (Decimal(payment_amount) * rate).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                form.add_error("payment_amount", "El monto convertido debe ser mayor que cero.")
            else:
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
                        txid=form.cleaned_data.get("txid", ""),
                        reference=form.cleaned_data.get("reference", ""),
                        proof=proof,
                        notes="Recarga manual pendiente de validación administrativa.",
                    )
                except IntegrityError:
                    form.add_error("txid", "Ese TXID o referencia ya fue registrado anteriormente.")
                else:
                    messages.success(
                        request,
                        "Recarga enviada. Administración revisará el comprobante antes de acreditar el saldo.",
                    )
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
        "methods": manual_methods,
        "deposits": deposits,
        "ledger": ledger,
        "config": config,
        "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
    })
