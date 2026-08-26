from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import PlatformConfig, Withdrawal, WithdrawalMethod
from .payment_policies import CRYPTO_WITHDRAWAL_SLUGS
from .services import HBLError, currency_rate, request_withdrawal
from .withdrawal_forms import PayoutAccountNetworkForm, WithdrawalUSDTForm


@login_required
def withdrawals(request):
    action = request.POST.get("action") if request.method == "POST" else ""
    form = WithdrawalUSDTForm(request.user, request.POST if action == "withdraw" else None)
    account_form = PayoutAccountNetworkForm(
        request.POST if action == "add_account" else None,
        user=request.user,
    )

    if request.method == "POST" and action == "withdraw" and form.is_valid():
        try:
            request_withdrawal(
                request.user.id,
                form.cleaned_data["payout_account"],
                form.cleaned_data["amount"],
                requested_currency=(
                    request.user.country_currency
                    or PlatformConfig.get_solo().base_currency_code
                ),
            )
            messages.success(
                request,
                "Retiro solicitado correctamente. Verifica siempre que la red de destino coincida con la wallet guardada.",
            )
            return redirect("hbl_withdrawals")
        except HBLError as exc:
            form.add_error(None, str(exc))

    if request.method == "POST" and action == "add_account" and account_form.is_valid():
        account = account_form.save(commit=False)
        account.user = request.user
        if account.is_default:
            request.user.hbl_payout_accounts.update(is_default=False)
        account.save()
        short_network = "TRC20" if account.withdrawal_method.slug == "usdt-trc20" else "BEP20"
        messages.success(
            request,
            f"Wallet {short_network} guardada correctamente. La red quedó registrada junto con la dirección.",
        )
        return redirect("hbl_withdrawals")

    items = Withdrawal.objects.filter(user=request.user)[:12]
    config = PlatformConfig.get_solo()
    withdrawal_methods = WithdrawalMethod.objects.filter(
        active=True,
        slug__in=CRYPTO_WITHDRAWAL_SLUGS,
    ).order_by("sort_order", "name")

    preferred_currency = (
        getattr(request.user, "country_currency", "")
        or config.base_currency_code
    ).upper()

    try:
        preferred_rate = currency_rate(preferred_currency)
        withdrawal_min_preferred = (
            Decimal(config.withdrawal_min) / preferred_rate
        ).quantize(Decimal("0.01"))
        preferred_balance = (
            Decimal(request.user.saldo or 0) / preferred_rate
        ).quantize(Decimal("0.01"))
        withdraw_currency_ready = True
    except HBLError:
        preferred_rate = Decimal("0")
        withdrawal_min_preferred = None
        preferred_balance = None
        withdraw_currency_ready = False

    accounts_data = []
    saved_wallets = list(form.fields["payout_account"].queryset)
    for account in saved_wallets:
        method = account.withdrawal_method
        payout_currency = method.payout_currency_for(request.user)
        try:
            payout_rate = currency_rate(payout_currency)
        except HBLError:
            payout_rate = None
        short_network = "TRC20" if method.slug == "usdt-trc20" else "BEP20"
        accounts_data.append({
            "id": account.id,
            "method": method.name,
            "network": short_network,
            "masked": account.masked_identifier,
            "payout_currency": payout_currency,
            "payout_rate": str(payout_rate or ""),
            "fee_percent": str(method.fee_percent or 0),
            "fee_fixed_base": str(method.fee_fixed_nio or 0),
            "effective_min_base": str(
                max(
                    Decimal(config.withdrawal_min or 0),
                    Decimal(method.min_amount_nio or 0),
                )
            ),
            "max_base": str(method.max_amount_nio or 0),
        })

    return render(
        request,
        "hbl/withdraw_v2.html",
        {
            "form": form,
            "account_form": account_form,
            "withdrawals": items,
            "config": config,
            "withdrawal_methods": withdrawal_methods,
            "withdrawal_accounts_data": accounts_data,
            "saved_wallets": saved_wallets,
            "preferred_currency": preferred_currency,
            "preferred_rate": preferred_rate,
            "withdrawal_min_preferred": withdrawal_min_preferred,
            "preferred_balance": preferred_balance,
            "withdraw_currency_ready": withdraw_currency_ready,
        },
    )
