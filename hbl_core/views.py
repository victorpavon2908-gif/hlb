import hashlib
import json
import secrets
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .binance_pay import BinancePayClient, BinancePayError
from .forms import DepositForm, GiftRedeemForm, LoginForm, PayoutAccountForm, ProfileForm, RegistrationForm, WithdrawalForm
from .models import CurrencyRate, DailyAssignment, Deposit, GiftRedemption, ListeningSession, MembershipPlan, PaymentMethod, PlatformConfig, ReferralPayroll, RewardLedger, Track, WheelConfig, WheelPrize, WheelSpin, Withdrawal, WithdrawalMethod
from .services import HBLError, active_referral_count, approve_deposit, claim_referral_upgrade, complete_listening, current_membership, currency_rate, display_money, eligible_referral_upgrade, ensure_daily_assignments, listening_heartbeat, plan_price_nio, purchase_plan, qualified_referral_count, redeem_gift_code, referral_tier_for_count, request_withdrawal, spin_wheel, start_listening, user_day_bounds, user_localdate

logger = logging.getLogger(__name__)
User = get_user_model()


def _client_ip_hash(request):
    raw = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    salt = getattr(settings, "SECRET_KEY", "hbl")[:32]
    return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest() if raw else ""


def _merchant_trade_no():
    # Solo letras/dígitos y <=32, requisito de Binance Pay.
    return f"HBL{timezone.now():%y%m%d%H%M%S}{secrets.token_hex(6)}"[:32]


def login_view(request):
    if request.user.is_authenticated:
        return redirect("hbl_home")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        identity = form.cleaned_data["identity"].strip()
        ip_token = _client_ip_hash(request)[:24] or "unknown"
        identity_token = hashlib.sha256(identity.lower().encode()).hexdigest()[:20]
        throttle_key = f"hbl-login:{ip_token}:{identity_token}"
        attempts = int(cache.get(throttle_key, 0) or 0)
        if attempts >= 8:
            form.add_error(None, "Demasiados intentos. Espera 15 minutos antes de volver a probar.")
            return render(request, "hbl/login.html", {"form": form}, status=429)

        phone_identity = User.normalize_phone(identity)
        found = User.objects.filter(
            Q(username__iexact=identity) | Q(email__iexact=identity) | Q(telefono=phone_identity)
        ).only("username").first()
        # Si escribió un teléfono local sin +código, lo aceptamos únicamente cuando identifica a una sola cuenta.
        if not found and "@" not in identity and not identity.startswith("+"):
            local_digits = "".join(ch for ch in identity if ch.isdigit()).lstrip("0")
            if len(local_digits) >= 7:
                matches = list(User.objects.filter(telefono__endswith=local_digits).only("username")[:2])
                if len(matches) == 1:
                    found = matches[0]
        username = found.username if found else identity
        user = authenticate(request, username=username, password=form.cleaned_data["password"])
        if user is None:
            cache.set(throttle_key, attempts + 1, timeout=900)
            form.add_error(None, "Credenciales incorrectas.")
        elif not user.is_active:
            cache.set(throttle_key, attempts + 1, timeout=900)
            form.add_error(None, "Tu cuenta está desactivada.")
        else:
            cache.delete(throttle_key)
            login(request, user)
            next_url = request.GET.get("next", "")
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect("hbl_home")
    return render(request, "hbl/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("hbl_login")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("hbl_home")
    initial_ref = request.GET.get("ref", "").strip()
    form = RegistrationForm(request.POST or None, initial={"referral_code": initial_ref})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        sponsor = None
        code = data.get("referral_code", "").strip().upper()
        if code:
            sponsor = User.objects.filter(codigo_invitacion=code).first()
            if not sponsor:
                form.add_error("referral_code", "Código de referido no válido.")
                return render(request, "hbl/register.html", {"form": form})
        with transaction.atomic():
            user = User.objects.create_user(
                username=User.generate_username(),
                email=data.get("email"),
                telefono=data.get("phone"),
                country=data.get("country") or "NI",
                timezone_name=data.get("timezone_name") or "UTC",
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                referido_por=sponsor,
                password=data["password1"],
            )
            config = PlatformConfig.get_solo()
            if config.signup_bonus > 0 and hasattr(user, "saldo"):
                from .services import credit_balance
                credit_balance(user.id, config.signup_bonus, RewardLedger.Kind.SIGNUP, reference=f"signup:{user.id}")
        login(request, user)
        messages.success(request, "¡Bienvenido a HBL!")
        return redirect("hbl_home")
    return render(request, "hbl/register.html", {"form": form})


@login_required
@require_GET
def home(request):
    config = PlatformConfig.get_solo()
    today = user_localdate(request.user)
    day_start, day_end = user_day_bounds(request.user, today)
    assignment_error = ""
    try:
        membership, assignments = ensure_daily_assignments(request.user)
    except HBLError as exc:
        membership, assignments = current_membership(request.user), []
        assignment_error = str(exc)
    earned_today = RewardLedger.objects.filter(
        user=request.user,
        kind__in=[RewardLedger.Kind.LISTEN, RewardLedger.Kind.MEMBERSHIP_REWARD],
        created_at__gte=day_start, created_at__lt=day_end,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    completed_count = sum(1 for item in assignments if item.completed_at)
    for item in assignments:
        item.required_listen_seconds = max(
            int(config.listen_verification_seconds or 10),
            int(getattr(item.track, "min_listen_seconds", 0) or 0),
        )
    recent = RewardLedger.objects.filter(user=request.user)[:8]
    try:
        usd_balance = display_money(request.user.saldo or 0, "USD")
    except HBLError:
        usd_balance = Decimal("0")
    preferred_currency = getattr(request.user, "preferred_currency", "") or "USD"
    try:
        preferred_balance = display_money(request.user.saldo or 0, preferred_currency)
        preferred_daily_reward = display_money(membership.daily_reward_snapshot, preferred_currency) if membership else Decimal("0")
        daily_reward_usd = display_money(membership.daily_reward_snapshot, "USD") if membership else Decimal("0")
    except HBLError:
        preferred_balance = usd_balance
        preferred_daily_reward = daily_reward_usd = Decimal("0")
    wheel_config = WheelConfig.get_solo()
    wheel_spins_today = WheelSpin.objects.filter(user=request.user, created_at__gte=day_start, created_at__lt=day_end).count()
    qualified_referrals = qualified_referral_count(request.user)
    return render(request, "hbl/home.html", {
        "assignments": assignments, "membership": membership, "earned_today": earned_today,
        "completed_count": completed_count, "recent": recent, "config": config,
        "usd_balance": usd_balance, "daily_reward_usd": daily_reward_usd, "assignment_error": assignment_error,
        "wheel_config": wheel_config, "wheel_spins_today": wheel_spins_today,
        "qualified_referrals": qualified_referrals, "preferred_currency": preferred_currency,
        "preferred_balance": preferred_balance, "preferred_daily_reward": preferred_daily_reward,
    })


@login_required
def plans(request):
    config = PlatformConfig.get_solo()
    active = current_membership(request.user)
    plan_items = []
    for plan in MembershipPlan.objects.filter(active=True):
        cost_nio = plan_price_nio(plan)
        try:
            cycle_usd = display_money(plan.projected_cycle_reward_nio, "USD")
        except HBLError:
            cycle_usd = Decimal("0")
        plan_items.append({"plan": plan, "cost_nio": cost_nio, "cycle_usd": cycle_usd})
    upgrade_option = eligible_referral_upgrade(request.user)
    if request.method == "POST":
        action = request.POST.get("action", "buy")
        if action == "claim_upgrade":
            try:
                membership = claim_referral_upgrade(request.user.id)
                messages.success(request, f"Subiste gratis a {membership.plan.name} gracias a tus referidos calificados.")
                return redirect("hbl_home")
            except HBLError as exc:
                messages.error(request, str(exc))
                return redirect("hbl_plans")
        if active:
            messages.warning(request, "Ya tienes un plan activo.")
            return redirect("hbl_plans")
        plan = get_object_or_404(MembershipPlan, pk=request.POST.get("plan_id"), active=True)
        try:
            purchase_plan(request.user.id, plan.id)
            messages.success(request, f"Plan {plan.name} activado correctamente.")
            return redirect("hbl_home")
        except HBLError as exc:
            messages.error(request, str(exc))
    return render(request, "hbl/plans.html", {"plan_items": plan_items, "active_membership": active, "config": config, "upgrade_option": upgrade_option})


@login_required
@require_POST
def listen_start(request, assignment_id):
    try:
        assignment = get_object_or_404(
            DailyAssignment.objects.select_related(
                "track",
                "membership",
            ),
            pk=assignment_id,
            user=request.user,
        )

        session, created = start_listening(
            request.user,
            assignment,
            client_nonce=request.POST.get("nonce", ""),
            ip_hash=_client_ip_hash(request),
        )

        config = PlatformConfig.get_solo()

        required_seconds = max(
            int(config.listen_verification_seconds or 10),
            int(
                getattr(
                    assignment.track,
                    "min_listen_seconds",
                    0,
                )
                or 0
            ),
        )

        return JsonResponse({
            "ok": True,
            "session_id": str(session.id),
            "created": created,
            "min_seconds": required_seconds,
            "reward": str(
                assignment.reward_amount
            ),
            "ping_url": reverse(
                "hbl_listen_ping",
                args=[session.id],
            ),
            "complete_url": reverse(
                "hbl_listen_complete",
                args=[session.id],
            ),
        })

    except HBLError as exc:
        return JsonResponse({
            "ok": False,
            "error": str(exc),
        }, status=409)

    except Exception:
        logger.exception(
            "Error inesperado iniciando escucha. "
            "user=%s assignment=%s",
            request.user.id,
            assignment_id,
        )

        return JsonResponse({
            "ok": False,
            "error": (
                "Ocurrió un error interno al iniciar "
                "la escucha."
            ),
        }, status=500)


@login_required
@require_POST
def listen_ping(request, session_id):
    try:
        session, remaining = listening_heartbeat(
            request.user.id,
            session_id,
        )

        return JsonResponse({
            "ok": True,
            "verified_seconds":
                int(session.verified_seconds or 0),
            "remaining":
                int(remaining or 0),
        })

    except ListeningSession.DoesNotExist:
        return JsonResponse({
            "ok": False,
            "error": "Sesión no encontrada.",
        }, status=404)

    except HBLError as exc:
        return JsonResponse({
            "ok": False,
            "error": str(exc),
        }, status=409)

    except Exception:
        logger.exception(
            "Error inesperado verificando escucha. "
            "user=%s session=%s",
            request.user.id,
            session_id,
        )

        return JsonResponse({
            "ok": False,
            "error": (
                "Ocurrió un error interno verificando "
                "la escucha."
            ),
        }, status=500)


@login_required
@require_POST
def listen_complete(request, session_id):
    try:
        session, credited = complete_listening(
            request.user.id,
            session_id,
        )

        request.user.refresh_from_db(
            fields=["saldo"]
        )

        return JsonResponse({
            "ok": True,
            "credited": bool(credited),
            "reward": str(
                session.reward_amount or 0
            ),
            "balance": str(
                request.user.saldo or 0
            ),
        })

    except ListeningSession.DoesNotExist:
        return JsonResponse({
            "ok": False,
            "error": "Sesión no encontrada.",
        }, status=404)

    except HBLError as exc:
        return JsonResponse({
            "ok": False,
            "error": str(exc),
        }, status=409)

    except Exception:
        logger.exception(
            "ERROR AL COMPLETAR ESCUCHA "
            "user=%s session=%s",
            request.user.id,
            session_id,
        )

        return JsonResponse({
            "ok": False,
            "error": (
                "Ocurrió un error interno al validar "
                "la canción. El error fue registrado "
                "en el servidor."
            ),
        }, status=500)

@login_required
def wallet(request):
    form = DepositForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data["payment_method"]
        payment_amount = form.cleaned_data["payment_amount"]
        rate_row = CurrencyRate.objects.filter(code=method.currency.upper(), active=True).first()
        rate = Decimal("1") if method.currency.upper() == PlatformConfig.get_solo().base_currency_code.upper() else Decimal(rate_row.rate_to_base) if rate_row else Decimal(method.balance_rate or 0)

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
                    deposit = Deposit.objects.create(
                        user=request.user,
                        payment_method=method,
                        amount=credit_amount,
                        currency=PlatformConfig.get_solo().base_currency_code.upper(),
                        payment_amount=payment_amount,
                        payment_currency=method.currency,
                        balance_rate=rate,
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
            else:
                try:
                    Deposit.objects.create(
                        user=request.user,
                        payment_method=method,
                        amount=credit_amount,
                        currency=PlatformConfig.get_solo().base_currency_code.upper(),
                        payment_amount=payment_amount,
                        payment_currency=method.currency,
                        balance_rate=rate,
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
    deposits = Deposit.objects.filter(user=request.user)[:12]
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
        "form": form, "methods": methods, "deposits": deposits, "ledger": ledger,
        "config": config, "minimum_deposit_nio": minimum_deposit_nio,
        "minimum_withdraw_preferred": minimum_withdraw_preferred,
    })


@login_required
@require_GET
def binance_return(request):
    trade_no = request.GET.get("order", "")
    deposit = get_object_or_404(Deposit, user=request.user, merchant_trade_no=trade_no)
    try:
        result = BinancePayClient().query_order(merchant_trade_no=trade_no)
        data = result.get("data") or {}
        status = data.get("status")
        if status == "PAID":
            BinancePayClient.validate_order_data(
                data, merchant_trade_no=deposit.merchant_trade_no,
                expected_amount=deposit.payment_amount, expected_currency=deposit.payment_currency,
                expected_prepay_id=deposit.prepay_id or None, require_paid=True,
            )
            approve_deposit(deposit.id, transaction_id=data.get("transactionId", ""), notes="Confirmado por consulta directa a Binance Pay")
            messages.success(request, "Pago confirmado por Binance. Tu saldo fue actualizado.")
        elif status in {"CANCELED", "EXPIRED", "ERROR"}:
            with transaction.atomic():
                locked = Deposit.objects.select_for_update().get(pk=deposit.pk)
                if locked.status != Deposit.Status.APPROVED:
                    locked.status = Deposit.Status.EXPIRED if status == "EXPIRED" else Deposit.Status.REJECTED
                    locked.notes = f"Estado Binance: {status}"
                    locked.processed_at = timezone.now()
                    locked.save(update_fields=["status", "notes", "processed_at"])
            messages.warning(request, f"Binance reportó el estado {status}.")
        else:
            messages.info(request, "El pago todavía está pendiente de confirmación en Binance.")
    except BinancePayError:
        messages.warning(request, "No pudimos confirmar el pago todavía. El sincronizador lo revisará nuevamente.")
    return redirect("hbl_wallet")


@login_required
def withdrawals(request):
    action = request.POST.get("action") if request.method == "POST" else ""
    form = WithdrawalForm(request.user, request.POST if action == "withdraw" else None)
    account_form = PayoutAccountForm(request.POST if action == "add_account" else None, user=request.user)

    if request.method == "POST" and action == "withdraw" and form.is_valid():
        try:
            request_withdrawal(
                request.user.id, form.cleaned_data["payout_account"], form.cleaned_data["amount"],
                requested_currency=(request.user.country_currency or PlatformConfig.get_solo().base_currency_code),
            )
            messages.success(request, "Retiro solicitado. El saldo quedó reservado y el monto de pago quedó congelado con la tasa actual.")
            return redirect("hbl_withdrawals")
        except HBLError as exc:
            form.add_error(None, str(exc))

    if request.method == "POST" and action == "add_account" and account_form.is_valid():
        account = account_form.save(commit=False)
        account.user = request.user
        if account.is_default:
            request.user.hbl_payout_accounts.update(is_default=False)
        account.save()
        messages.success(request, "Destino de retiro guardado y validado.")
        return redirect("hbl_withdrawals")

    items = Withdrawal.objects.filter(user=request.user)[:12]
    config = PlatformConfig.get_solo()
    withdrawal_methods = WithdrawalMethod.objects.filter(active=True).filter(Q(country="") | Q(country=request.user.country)).order_by("sort_order", "name")
    preferred_currency = (getattr(request.user, "country_currency", "") or config.base_currency_code).upper()
    try:
        preferred_rate = currency_rate(preferred_currency)
        withdrawal_min_preferred = (Decimal(config.withdrawal_min) / preferred_rate).quantize(Decimal("0.01"))
        preferred_balance = (Decimal(request.user.saldo or 0) / preferred_rate).quantize(Decimal("0.01"))
        withdraw_currency_ready = True
    except HBLError:
        preferred_rate = Decimal("0")
        withdrawal_min_preferred = None
        preferred_balance = None
        withdraw_currency_ready = False

    withdrawal_methods_data = []
    for method in withdrawal_methods:
        payout_currency = method.payout_currency_for(request.user)
        try:
            payout_rate = currency_rate(payout_currency)
        except HBLError:
            payout_rate = None
        effective_min = max(Decimal(config.withdrawal_min or 0), Decimal(method.min_amount_nio or 0))
        withdrawal_methods_data.append({
            "id": method.id, "name": method.name, "account_label": method.account_label,
            "identifier_type": method.identifier_type, "identifier_placeholder": method.identifier_placeholder,
            "identifier_help": method.identifier_help, "instructions": method.instructions,
            "holder_required": method.holder_required, "network": method.network,
            "payout_currency": payout_currency, "payout_rate": str(payout_rate or ""),
            "effective_min_base": str(effective_min), "max_base": str(method.max_amount_nio or 0),
            "fee_percent": str(method.fee_percent or 0), "fee_fixed_base": str(method.fee_fixed_nio or 0),
        })

    accounts_data = []
    for account in form.fields["payout_account"].queryset:
        method = account.withdrawal_method
        payout_currency = method.payout_currency_for(request.user)
        try:
            payout_rate = currency_rate(payout_currency)
        except HBLError:
            payout_rate = None
        accounts_data.append({
            "id": account.id, "method": method.name, "payout_currency": payout_currency,
            "payout_rate": str(payout_rate or ""), "fee_percent": str(method.fee_percent or 0),
            "fee_fixed_base": str(method.fee_fixed_nio or 0),
            "effective_min_base": str(max(Decimal(config.withdrawal_min or 0), Decimal(method.min_amount_nio or 0))),
            "max_base": str(method.max_amount_nio or 0),
        })

    return render(request, "hbl/withdraw.html", {
        "form": form, "account_form": account_form, "withdrawals": items, "config": config,
        "withdrawal_methods": withdrawal_methods, "withdrawal_methods_data": withdrawal_methods_data,
        "withdrawal_accounts_data": accounts_data, "preferred_currency": preferred_currency,
        "preferred_rate": preferred_rate, "withdrawal_min_preferred": withdrawal_min_preferred,
        "preferred_balance": preferred_balance, "withdraw_currency_ready": withdraw_currency_ready,
    })



@login_required
def referrals(request):
    count = active_referral_count(request.user)
    qualified = qualified_referral_count(request.user)
    tier = referral_tier_for_count(count)
    code = getattr(request.user, "codigo_invitacion", "")
    referral_url = request.build_absolute_uri(f"{reverse('hbl_register')}?ref={code}") if code else ""
    referred = User.objects.filter(referido_por=request.user).order_by("-date_joined")[:50]
    payrolls = ReferralPayroll.objects.filter(user=request.user)[:10]
    earnings = request.user.hbl_referral_earnings.select_related("referred")[:10]
    upgrade_option = eligible_referral_upgrade(request.user)
    return render(request, "hbl/referrals.html", {
        "active_referrals": count,
        "qualified_referrals": qualified,
        "tier": tier,
        "referral_url": referral_url,
        "referred": referred,
        "payrolls": payrolls,
        "earnings": earnings,
        "upgrade_option": upgrade_option,
    })


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Perfil actualizado.")
        return redirect("hbl_profile")
    config = PlatformConfig.get_solo()
    membership = current_membership(request.user)
    preferred_currency = getattr(request.user, "preferred_currency", "") or "USD"
    try:
        usd_balance = display_money(request.user.saldo or 0, "USD")
        preferred_balance = display_money(request.user.saldo or 0, preferred_currency)
    except HBLError:
        usd_balance = preferred_balance = Decimal("0")
    return render(request, "hbl/profile.html", {"form": form, "membership": membership, "config": config, "usd_balance": usd_balance, "preferred_currency": preferred_currency, "preferred_balance": preferred_balance})


@login_required
def wheel(request):
    config = WheelConfig.get_solo()
    today = user_localdate(request.user)
    day_start, day_end = user_day_bounds(request.user, today)
    prizes = WheelPrize.objects.filter(active=True).order_by("sort_order", "id")
    spins_today = WheelSpin.objects.filter(user=request.user, created_at__gte=day_start, created_at__lt=day_end).count()
    recent = WheelSpin.objects.filter(user=request.user).select_related("prize")[:12]
    membership = current_membership(request.user)
    qualified = qualified_referral_count(request.user)
    platform = PlatformConfig.get_solo()
    eligible_by_referrals = (not platform.wheel_requires_qualified_referral) or qualified >= int(platform.wheel_min_qualified_referrals or 1)
    can_spin = config.enabled and prizes.exists() and spins_today < config.spins_per_day and (membership is not None or not config.require_active_membership) and eligible_by_referrals
    return render(request, "hbl/wheel.html", {
        "config": config, "prizes": prizes, "spins_today": spins_today, "recent": recent,
        "membership": membership, "can_spin": can_spin, "qualified_referrals": qualified,
        "wheel_referrals_required": int(platform.wheel_min_qualified_referrals or 1), "platform": platform,
    })


@login_required
@require_POST
def wheel_spin(request):
    try:
        spin = spin_wheel(request.user.id)
        request.user.refresh_from_db(fields=["saldo"])
        return JsonResponse({
            "ok": True,
            "prize_id": spin.prize_id,
            "prize": spin.prize.name,
            "icon": spin.prize.icon,
            "reward_type": spin.prize.reward_type,
            "value": str(spin.prize.value),
            "balance": str(request.user.saldo),
        })
    except HBLError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=409)


@login_required
def gifts(request):
    form = GiftRedeemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            redemption = redeem_gift_code(request.user.id, form.cleaned_data["code"])
            request.user.refresh_from_db(fields=["saldo"])
            messages.success(request, f"Código aplicado: {redemption.gift.name}.")
            return redirect("hbl_gifts")
        except HBLError as exc:
            form.add_error("code", str(exc))
    history = GiftRedemption.objects.filter(user=request.user).select_related("gift")[:20]
    return render(request, "hbl/gifts.html", {"form": form, "history": history})


@require_GET
def service_worker(request):
    path = settings.BASE_DIR / "hbl_core" / "static" / "hbl" / "js" / "service-worker.js"
    if not path.exists():
        raise Http404
    response = FileResponse(path.open("rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@csrf_exempt
@require_POST
def binance_webhook(request):
    """Webhook oficial Binance Pay: valida firma RSA y acredita solo PAY_SUCCESS idempotente."""
    raw = request.body.decode("utf-8")
    try:
        client = BinancePayClient()
        client.verify_webhook(
            body=raw,
            timestamp=request.headers.get("BinancePay-Timestamp", ""),
            nonce=request.headers.get("BinancePay-Nonce", ""),
            signature=request.headers.get("BinancePay-Signature", ""),
            certificate_sn=request.headers.get("BinancePay-Certificate-SN", ""),
        )
        payload = json.loads(raw)
        if payload.get("bizType") != "PAY":
            return JsonResponse({"returnCode": "SUCCESS", "returnMessage": None})
        data = payload.get("data") or {}
        if isinstance(data, str):
            data = json.loads(data)
        trade_no = data.get("merchantTradeNo", "")
        if not trade_no:
            return JsonResponse({"returnCode": "FAIL", "returnMessage": "merchantTradeNo missing"}, status=400)
        deposit = Deposit.objects.filter(merchant_trade_no=trade_no).first()
        if not deposit:
            return JsonResponse({"returnCode": "FAIL", "returnMessage": "order not found"}, status=404)
        if payload.get("bizStatus") == "PAY_SUCCESS":
            # Defensa adicional: consulta directa a Binance antes de acreditar.
            query = client.query_order(merchant_trade_no=trade_no)
            qdata = query.get("data") or {}
            BinancePayClient.validate_order_data(
                qdata, merchant_trade_no=deposit.merchant_trade_no,
                expected_amount=deposit.payment_amount, expected_currency=deposit.payment_currency,
                expected_prepay_id=deposit.prepay_id or None, require_paid=True,
            )
            approve_deposit(deposit.id, transaction_id=qdata.get("transactionId", ""), notes="Confirmado por webhook firmado + Query Order Binance")
        elif payload.get("bizStatus") == "PAY_CLOSED":
            with transaction.atomic():
                locked = Deposit.objects.select_for_update().get(pk=deposit.pk)
                if locked.status != Deposit.Status.APPROVED:
                    locked.status = Deposit.Status.REJECTED
                    locked.notes = "Orden cerrada por Binance Pay"
                    locked.processed_at = timezone.now()
                    locked.save(update_fields=["status", "notes", "processed_at"])
        return JsonResponse({"returnCode": "SUCCESS", "returnMessage": None})
    except (BinancePayError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"returnCode": "FAIL", "returnMessage": str(exc)[:180]}, status=400)


@login_required
@require_POST
def update_timezone(request):
    name = (request.POST.get("timezone") or "").strip()[:64]
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return JsonResponse({"ok": False, "error": "Zona horaria inválida."}, status=400)

    current = (request.user.timezone_name or "UTC").strip() or "UTC"
    if current == name:
        return JsonResponse({"ok": True, "timezone": current, "locked": current != "UTC"})

    # La zona horaria define el corte de la recompensa diaria. Para evitar que
    # alguien cambie de huso repetidamente y fuerce varios "días" en 24 horas,
    # el autosync del navegador solo puede sustituir el valor inicial UTC antes
    # de que exista una tarea completada/recompensa diaria. Cambios posteriores
    # requieren intervención administrativa documentada.
    if current != "UTC":
        return JsonResponse({"ok": True, "timezone": current, "locked": True})

    has_completed = DailyAssignment.objects.filter(user=request.user, completed_at__isnull=False).exists()
    has_daily_reward = RewardLedger.objects.filter(
        user=request.user, kind=RewardLedger.Kind.MEMBERSHIP_REWARD
    ).exists()
    if has_completed or has_daily_reward:
        return JsonResponse({"ok": True, "timezone": current, "locked": True})

    with transaction.atomic():
        # El primer render puede haber creado tareas UTC aún no iniciadas. Se
        # eliminan de forma segura para regenerarlas inmediatamente con la fecha
        # local detectada. Una sesión ya iniciada impide el cambio automático.
        if ListeningSession.objects.filter(user=request.user, status=ListeningSession.Status.STARTED).exists():
            return JsonResponse({"ok": True, "timezone": current, "locked": True})
        DailyAssignment.objects.filter(user=request.user, completed_at__isnull=True).delete()
        request.user.timezone_name = name
        request.user.save(update_fields=["timezone_name"])
    return JsonResponse({"ok": True, "timezone": name, "locked": True, "changed": True})


def terms(request):
    return render(request, "hbl/terms.html", {"config": PlatformConfig.get_solo()})


def offline(request):
    return render(request, "hbl/offline.html")


@require_GET
def healthz(request):
    return JsonResponse({"ok": True, "service": "HBL"})
