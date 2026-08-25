from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .control_forms import (
    AdminUserCreateForm,
    BalanceAdjustmentForm,
    CurrencyRateForm,
    ManualMembershipForm,
    MembershipPlanForm,
    PaymentMethodForm,
    PlatformConfigForm,
    ReferralTierForm,
    TrackForm,
    WithdrawalMethodForm,
    WheelConfigForm,
    WheelPrizeForm,
    GiftCodeForm,
    UserBlockForm,
)
from .models import (
    AdminAuditLog,
    CurrencyRate,
    DailyAssignment,
    Deposit,
    Membership,
    MembershipPlan,
    PaymentMethod,
    PlatformConfig,
    ReferralEarning,
    ReferralPayroll,
    ReferralTier,
    RewardLedger,
    Track,
    Withdrawal,
    WithdrawalMethod,
    WheelConfig,
    WheelPrize,
    WheelSpin,
    GiftCode,
    GiftRedemption,
)
from .payment_policies import CRYPTO_DEPOSIT_KINDS, CRYPTO_WITHDRAWAL_SLUGS
from .services import (
    HBLError,
    activate_membership_admin,
    adjust_balance_admin,
    approve_deposit,
    mark_withdrawal_paid,
    reject_deposit,
    reject_withdrawal,
)

User = get_user_model()


def _audit(request, action, target=None, detail=None):
    AdminAuditLog.objects.create(
        actor=request.user,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        detail=detail or {},
    )


def _paged(request, queryset, per_page=30):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


@staff_member_required(login_url="hbl_login")
def dashboard(request):
    now = timezone.now()
    today = timezone.localdate()
    active_memberships_qs = Membership.objects.select_related("plan", "user").filter(
        status=Membership.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now
    )
    active_memberships = list(active_memberships_qs)
    daily_liability = sum((Decimal(m.daily_reward_snapshot) for m in active_memberships), Decimal("0"))
    remaining_liability = Decimal("0")
    for m in active_memberships:
        remaining_days = max(0, (m.ends_at.date() - today).days)
        remaining_liability += Decimal(m.daily_reward_snapshot) * Decimal(remaining_days)

    rewards_today = RewardLedger.objects.filter(
        kind__in=[RewardLedger.Kind.LISTEN, RewardLedger.Kind.MEMBERSHIP_REWARD],
        created_at__date=today,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    completed_today = DailyAssignment.objects.filter(assignment_date=today, completed_at__isnull=False).count()
    total_today = DailyAssignment.objects.filter(assignment_date=today).count()
    wallet_total = User.objects.aggregate(total=Sum("saldo"))["total"] or Decimal("0")
    config = PlatformConfig.get_solo()

    context = {
        "config": config,
        "kpis": {
            "users": User.objects.count(),
            "active_memberships": len(active_memberships),
            "pending_deposits": Deposit.objects.filter(status__in=[Deposit.Status.PENDING, Deposit.Status.PROCESSING]).count(),
            "pending_withdrawals": Withdrawal.objects.filter(status__in=[Withdrawal.Status.PENDING, Withdrawal.Status.PROCESSING]).count(),
            "rewards_today": rewards_today,
            "completed_today": completed_today,
            "total_today": total_today,
            "daily_liability": daily_liability,
            "remaining_liability": remaining_liability,
            "wallet_total": wallet_total,
            "wheel_spins_today": WheelSpin.objects.filter(created_at__date=today).count(),
            "gift_redemptions_today": GiftRedemption.objects.filter(created_at__date=today).count(),
        },
        "recent_memberships": active_memberships_qs[:8],
        "recent_deposits": Deposit.objects.select_related("user", "payment_method")[:8],
        "recent_withdrawals": Withdrawal.objects.select_related("user")[:8],
        "recent_audit": AdminAuditLog.objects.select_related("actor")[:10],
    }
    return render(request, "hbl/control/dashboard.html", context)


@staff_member_required(login_url="hbl_login")
def users(request):
    q = request.GET.get("q", "").strip()
    qs = User.objects.all().order_by("-date_joined")
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(telefono__icontains=q)
            | Q(codigo_invitacion__icontains=q)
        )
    return render(request, "hbl/control/users.html", {"page_obj": _paged(request, qs), "q": q})


@staff_member_required(login_url="hbl_login")
def user_create(request):
    form = AdminUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        sponsor = User.objects.filter(codigo_invitacion=data.get("referral_code")).first() if data.get("referral_code") else None
        member = User.objects.create_user(
            username=User.generate_username(), email=data.get("email"), password=data["password1"],
            first_name=data.get("first_name", ""), last_name=data.get("last_name", ""),
            telefono=data.get("telefono"), country=data.get("country") or "NI", referido_por=sponsor,
            is_staff=data.get("is_staff", False),
        )
        _audit(request, "user_created", member, {"email": member.email, "referred_by": sponsor.id if sponsor else None})
        messages.success(request, "Cuenta creada correctamente.")
        return redirect("hbl_control_user_detail", user_id=member.id)
    return render(request, "hbl/control/user_create.html", {"form": form})


@staff_member_required(login_url="hbl_login")
def user_detail(request, user_id):
    member = get_object_or_404(User, pk=user_id)
    balance_form = BalanceAdjustmentForm(prefix="balance")
    membership_form = ManualMembershipForm(prefix="membership")
    block_form = UserBlockForm(prefix="block")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "balance":
            balance_form = BalanceAdjustmentForm(request.POST, prefix="balance")
            if balance_form.is_valid():
                data = balance_form.cleaned_data
                try:
                    adjust_balance_admin(
                        member.id,
                        data["amount"],
                        data["direction"],
                        reference=f"admin:{request.user.id}:{timezone.now():%Y%m%d%H%M%S}",
                        metadata={"reason": data["reason"], "actor": request.user.id},
                    )
                    _audit(request, "balance_adjustment", member, {"direction": data["direction"], "amount": str(data["amount"]), "reason": data["reason"]})
                    messages.success(request, "Saldo actualizado y auditado.")
                    return redirect("hbl_control_user_detail", user_id=member.id)
                except HBLError as exc:
                    balance_form.add_error(None, str(exc))
        elif action == "membership":
            membership_form = ManualMembershipForm(request.POST, prefix="membership")
            if membership_form.is_valid():
                data = membership_form.cleaned_data
                membership = activate_membership_admin(member.id, data["plan"].id, request.user.id, days=data.get("days"))
                _audit(request, "membership_manual_activation", membership, {"user": member.id, "plan": membership.plan_id, "ends_at": membership.ends_at.isoformat()})
                messages.success(request, "Membresía activada manualmente.")
                return redirect("hbl_control_user_detail", user_id=member.id)
        elif action == "toggle_active":
            block_form = UserBlockForm(request.POST, prefix="block")
            if member.id == request.user.id and member.is_active:
                messages.error(request, "No puedes bloquear tu propia cuenta desde aquí.")
            elif member.is_active:
                if block_form.is_valid():
                    member.block(actor=request.user, reason=block_form.cleaned_data.get("reason"))
                    _audit(request, "user_blocked", member, {"reason": member.blocked_reason})
                    messages.success(request, "Usuario bloqueado.")
            else:
                member.unblock()
                _audit(request, "user_unblocked", member)
                messages.success(request, "Usuario desbloqueado.")
            return redirect("hbl_control_user_detail", user_id=member.id)

    active_membership = Membership.objects.filter(user=member, status=Membership.Status.ACTIVE, ends_at__gt=timezone.now()).select_related("plan").first()
    return render(request, "hbl/control/user_detail.html", {
        "member": member,
        "balance_form": balance_form,
        "membership_form": membership_form,
        "block_form": block_form,
        "active_membership": active_membership,
        "memberships": Membership.objects.filter(user=member).select_related("plan")[:12],
        "ledger": RewardLedger.objects.filter(user=member)[:20],
        "deposits": Deposit.objects.filter(user=member).select_related("payment_method")[:10],
        "withdrawals": Withdrawal.objects.filter(user=member)[:10],
    })


@staff_member_required(login_url="hbl_login")
def plans(request, plan_id=None):
    instance = get_object_or_404(MembershipPlan, pk=plan_id) if plan_id else None
    form = MembershipPlanForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "plan_saved", obj, {"name": obj.name, "price_usd": str(obj.price_usd), "daily_reward_nio": str(obj.daily_reward_nio)})
        messages.success(request, "Plan guardado.")
        return redirect("hbl_control_plans")
    items = MembershipPlan.objects.annotate(member_count=Count("memberships")).all()
    config = PlatformConfig.get_solo()
    return render(request, "hbl/control/plans.html", {"form": form, "editing": instance, "items": items, "config": config})


@staff_member_required(login_url="hbl_login")
def tracks(request, track_id=None):
    instance = get_object_or_404(Track, pk=track_id) if track_id else None
    form = TrackForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "track_saved", obj, {"title": obj.title, "active": obj.active})
        messages.success(request, "Canción guardada.")
        return redirect("hbl_control_tracks")
    items = Track.objects.prefetch_related("allowed_plans").all()
    return render(request, "hbl/control/tracks.html", {"form": form, "editing": instance, "items": items})


@staff_member_required(login_url="hbl_login")
def memberships(request):
    status = request.GET.get("status", "")
    qs = Membership.objects.select_related("user", "plan", "activated_by")
    if status:
        qs = qs.filter(status=status)
    return render(request, "hbl/control/memberships.html", {"page_obj": _paged(request, qs), "status": status, "status_choices": Membership.Status.choices})


@staff_member_required(login_url="hbl_login")
@require_POST
def membership_cancel(request, membership_id):
    membership = get_object_or_404(Membership, pk=membership_id)
    membership.status = Membership.Status.CANCELED
    membership.save(update_fields=["status"])
    _audit(request, "membership_canceled", membership)
    messages.success(request, "Membresía cancelada.")
    return redirect("hbl_control_memberships")


@staff_member_required(login_url="hbl_login")
def deposits(request):
    status = request.GET.get("status", "")
    qs = Deposit.objects.select_related("user", "payment_method")
    if status:
        qs = qs.filter(status=status)
    return render(request, "hbl/control/deposits.html", {"page_obj": _paged(request, qs), "status": status, "status_choices": Deposit.Status.choices})


@staff_member_required(login_url="hbl_login")
@require_POST
def deposit_action(request, deposit_id, action):
    deposit = get_object_or_404(Deposit, pk=deposit_id)
    try:
        note = (request.POST.get("note") or "").strip()[:240]
        if action == "approve":
            obj, changed = approve_deposit(deposit.id, notes=note or f"Aprobado desde HBL Control por {request.user.id}")
        elif action == "reject":
            if len(note) < 5:
                raise HBLError("Escribe un motivo de rechazo de al menos 5 caracteres.")
            obj, changed = reject_deposit(deposit.id, notes=note)
        else:
            raise HBLError("Acción inválida.")
        if changed:
            _audit(request, f"deposit_{action}", obj)
        messages.success(request, "Operación aplicada.")
    except HBLError as exc:
        messages.error(request, str(exc))
    return redirect("hbl_control_deposits")


@staff_member_required(login_url="hbl_login")
def withdrawals(request):
    status = request.GET.get("status", "")
    qs = Withdrawal.objects.select_related("user", "payout_account")
    if status:
        qs = qs.filter(status=status)
    return render(request, "hbl/control/withdrawals.html", {"page_obj": _paged(request, qs), "status": status, "status_choices": Withdrawal.Status.choices})


@staff_member_required(login_url="hbl_login")
@require_POST
def withdrawal_action(request, withdrawal_id, action):
    withdrawal = get_object_or_404(Withdrawal, pk=withdrawal_id)
    try:
        if action == "paid":
            reference = (request.POST.get("admin_reference") or "").strip()[:180]
            if len(reference) < 4:
                raise HBLError("Escribe la referencia/ID del pago antes de marcar el retiro como pagado.")
            obj, changed = mark_withdrawal_paid(withdrawal.id, admin_reference=reference)
        elif action == "reject":
            reason = (request.POST.get("reason") or "").strip()[:240]
            if len(reason) < 5:
                raise HBLError("Escribe un motivo de rechazo de al menos 5 caracteres.")
            obj, changed = reject_withdrawal(withdrawal.id, notes=reason)
        else:
            raise HBLError("Acción inválida.")
        if changed:
            _audit(request, f"withdrawal_{action}", obj)
        messages.success(request, "Operación aplicada.")
    except HBLError as exc:
        messages.error(request, str(exc))
    return redirect("hbl_control_withdrawals")


@staff_member_required(login_url="hbl_login")
def payment_methods(request, method_id=None):
    instance = get_object_or_404(
        PaymentMethod, pk=method_id, kind__in=CRYPTO_DEPOSIT_KINDS,
    ) if method_id else None
    form = PaymentMethodForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "payment_method_saved", obj, {"kind": obj.kind, "currency": obj.currency})
        messages.success(request, "Método de pago guardado.")
        return redirect("hbl_control_payment_methods")
    return render(request, "hbl/control/payment_methods.html", {
        "form": form,
        "editing": instance,
        "items": PaymentMethod.objects.filter(kind__in=CRYPTO_DEPOSIT_KINDS),
    })


@staff_member_required(login_url="hbl_login")
def referrals(request, tier_id=None):
    instance = get_object_or_404(ReferralTier, pk=tier_id) if tier_id else None
    form = ReferralTierForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "referral_tier_saved", obj, {"weekly_salary": str(obj.weekly_salary)})
        messages.success(request, "Nivel de referidos guardado.")
        return redirect("hbl_control_referrals")
    return render(request, "hbl/control/referrals.html", {
        "form": form,
        "editing": instance,
        "tiers": ReferralTier.objects.all(),
        "payrolls": ReferralPayroll.objects.select_related("user", "tier")[:30],
    })


@staff_member_required(login_url="hbl_login")
def currency_rates(request, rate_id=None):
    instance = get_object_or_404(CurrencyRate, pk=rate_id) if rate_id else None
    form = CurrencyRateForm(request.POST or None, instance=instance)
    config_obj = PlatformConfig.get_solo()
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.code = obj.code.upper()
        if obj.code == config_obj.base_currency_code.upper():
            obj.rate_to_base = Decimal("1")
        obj.save()
        _audit(request, "currency_rate_saved", obj, {"rate_to_base": str(obj.rate_to_base)})
        messages.success(request, "Tasa de moneda actualizada.")
        return redirect("hbl_control_currency_rates")
    return render(request, "hbl/control/currencies.html", {
        "form": form, "editing": instance, "items": CurrencyRate.objects.all(), "config": config_obj,
    })


def _has_financial_activity_for_base_change():
    """La moneda base no se reinterpreta después de empezar a operar dinero real."""
    if User.objects.exclude(saldo=Decimal("0.00")).exists():
        return True
    return any(model.objects.exists() for model in (
        RewardLedger, Deposit, Withdrawal, Membership, ReferralEarning, ReferralPayroll, WheelSpin, GiftRedemption,
    ))


def _rebase_catalog_amounts(denominator):
    """Convierte importes de configuración/catálogo de la base anterior a la nueva.

    Solo se invoca antes de que exista actividad financiera. `denominator` es
    cuántas unidades de la base anterior equivalen a 1 unidad de la base nueva.
    """
    denominator = Decimal(denominator)
    if denominator <= 0:
        raise ValueError("La tasa de rebase debe ser mayor que cero.")

    def q2(value):
        return (Decimal(value or 0) / denominator).quantize(Decimal("0.01"))

    def q8(value):
        return (Decimal(value or 0) / denominator).quantize(Decimal("0.00000001"))

    for plan in MembershipPlan.objects.select_for_update().all():
        plan.daily_reward_nio = q2(plan.daily_reward_nio)
        plan.save(update_fields=["daily_reward_nio", "updated_at"])
    for track in Track.objects.select_for_update().all():
        track.reward_amount = q2(track.reward_amount)
        track.save(update_fields=["reward_amount"])
    for method in PaymentMethod.objects.select_for_update().all():
        method.balance_rate = q8(method.balance_rate)
        method.save(update_fields=["balance_rate"])
    for method in WithdrawalMethod.objects.select_for_update().all():
        method.min_amount_nio = q2(method.min_amount_nio)
        method.max_amount_nio = q2(method.max_amount_nio)
        method.fee_fixed_nio = q2(method.fee_fixed_nio)
        method.save(update_fields=["min_amount_nio", "max_amount_nio", "fee_fixed_nio"])
    for tier in ReferralTier.objects.select_for_update().all():
        tier.weekly_salary = q2(tier.weekly_salary)
        tier.save(update_fields=["weekly_salary"])
    for prize in WheelPrize.objects.select_for_update().filter(reward_type=WheelPrize.RewardType.BALANCE):
        prize.value = q2(prize.value)
        prize.save(update_fields=["value"])
    for gift in GiftCode.objects.select_for_update().filter(reward_type=GiftCode.RewardType.BALANCE):
        gift.value = q2(gift.value)
        gift.save(update_fields=["value"])


@staff_member_required(login_url="hbl_login")
def config(request):
    obj = PlatformConfig.get_solo()
    old_base = (obj.base_currency_code or "NIO").upper()
    form = PlatformConfigForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        new_base = (form.cleaned_data.get("base_currency_code") or old_base).upper()
        target_rate = CurrencyRate.objects.filter(code=new_base, active=True).first()
        changing_base = new_base != old_base
        if changing_base and (not target_rate or Decimal(target_rate.rate_to_base or 0) <= 0):
            form.add_error("base_currency_code", "Antes de cambiar la moneda base, configura y activa su tasa en Monedas y tasas.")
        elif changing_base and _has_financial_activity_for_base_change():
            form.add_error(
                "base_currency_code",
                "La moneda base queda bloqueada cuando ya existe actividad financiera. Cambiarla después alteraría el significado histórico de saldos, recargas, retiros y recompensas. Mantén la base actual y usa Monedas y tasas para mostrar/pagar equivalencias.",
            )
        else:
            with transaction.atomic():
                denominator = Decimal(target_rate.rate_to_base) if changing_base else Decimal("1")
                # Si el administrador solo cambió la base, conserva el valor económico
                # de importes de configuración convirtiéndolos a la nueva base. Si editó
                # expresamente un importe en el mismo formulario, se respeta como valor nuevo.
                old_values = {
                    "withdrawal_min": Decimal(obj.withdrawal_min or 0),
                    "daily_listen_reward_cap": Decimal(obj.daily_listen_reward_cap or 0),
                    "signup_bonus": Decimal(obj.signup_bonus or 0),
                }
                saved = form.save(commit=False)
                if changing_base:
                    if "base_currency_symbol" not in form.changed_data:
                        saved.base_currency_symbol = (target_rate.symbol or new_base)[:8]
                    for field_name, old_value in old_values.items():
                        if field_name not in form.changed_data:
                            setattr(saved, field_name, (old_value / denominator).quantize(Decimal("0.01")))
                    _rebase_catalog_amounts(denominator)
                saved.save()
                if changing_base:
                    for row in CurrencyRate.objects.select_for_update().filter(active=True):
                        row.rate_to_base = (Decimal(row.rate_to_base) / denominator).quantize(Decimal("0.0000000001"))
                        row.save(update_fields=["rate_to_base", "updated_at"])
                    CurrencyRate.objects.update_or_create(
                        code=new_base,
                        defaults={"name": target_rate.name or new_base, "symbol": saved.base_currency_symbol, "rate_to_base": Decimal("1"), "active": True},
                    )
                usd = CurrencyRate.objects.filter(code="USD", active=True).first()
                if usd:
                    saved.exchange_rate_usd_nio = Decimal(usd.rate_to_base)
                    saved.save(update_fields=["exchange_rate_usd_nio", "updated_at"])
                _audit(request, "platform_config_saved", saved, {
                    "old_base": old_base, "new_base": new_base, "usd_to_base": str(saved.exchange_rate_usd_nio),
                    "base_changed": changing_base,
                })
            messages.success(request, "Configuración actualizada.")
            return redirect("hbl_control_config")
    return render(request, "hbl/control/config.html", {"form": form, "config": obj})


@staff_member_required(login_url="hbl_login")
def audit(request):
    qs = AdminAuditLog.objects.select_related("actor")
    return render(request, "hbl/control/audit.html", {"page_obj": _paged(request, qs, 50)})


@staff_member_required(login_url="hbl_login")
def ledger_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="hbl_ledger.csv"'
    response.write("id,fecha,usuario,tipo,monto,saldo_despues,referencia\n")
    for item in RewardLedger.objects.select_related("user").order_by("-created_at")[:50000]:
        values = [item.id, item.created_at.isoformat(), item.user.username, item.kind, item.amount, item.balance_after, item.reference]
        response.write(",".join('"' + str(v).replace('"', '""') + '"' for v in values) + "\n")
    _audit(request, "ledger_export")
    return response


@staff_member_required(login_url="hbl_login")
def withdrawal_methods(request, method_id=None):
    instance = get_object_or_404(
        WithdrawalMethod, pk=method_id, slug__in=CRYPTO_WITHDRAWAL_SLUGS,
    ) if method_id else None
    form = WithdrawalMethodForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "withdrawal_method_saved", obj, {
            "min": str(obj.min_amount_nio), "max": str(obj.max_amount_nio),
            "fee_percent": str(obj.fee_percent), "fee_fixed": str(obj.fee_fixed_nio),
        })
        messages.success(request, "Método de retiro guardado.")
        return redirect("hbl_control_withdrawal_methods")
    return render(request, "hbl/control/withdrawal_methods.html", {
        "form": form, "editing": instance,
        "items": WithdrawalMethod.objects.filter(slug__in=CRYPTO_WITHDRAWAL_SLUGS),
        "config": PlatformConfig.get_solo(),
    })


@staff_member_required(login_url="hbl_login")
def wheel(request, prize_id=None):
    config_obj = WheelConfig.get_solo()
    prize = get_object_or_404(WheelPrize, pk=prize_id) if prize_id else None
    config_form = WheelConfigForm(prefix="config", instance=config_obj)
    prize_form = WheelPrizeForm(prefix="prize", instance=prize)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "config":
            config_form = WheelConfigForm(request.POST, prefix="config", instance=config_obj)
            if config_form.is_valid():
                obj = config_form.save()
                _audit(request, "wheel_config_saved", obj, {"enabled": obj.enabled, "spins_per_day": obj.spins_per_day})
                messages.success(request, "Configuración de ruleta actualizada.")
                return redirect("hbl_control_wheel")
        elif action == "prize":
            prize_form = WheelPrizeForm(request.POST, prefix="prize", instance=prize)
            if prize_form.is_valid():
                obj = prize_form.save()
                _audit(request, "wheel_prize_saved", obj, {"type": obj.reward_type, "value": str(obj.value), "weight": obj.weight})
                messages.success(request, "Premio de ruleta guardado.")
                return redirect("hbl_control_wheel")
    today = timezone.localdate()
    return render(request, "hbl/control/wheel.html", {
        "config_form": config_form, "prize_form": prize_form, "editing": prize,
        "items": WheelPrize.objects.annotate(spin_count=Count("spins")).all(),
        "recent_spins": WheelSpin.objects.select_related("user", "prize")[:30],
        "spins_today": WheelSpin.objects.filter(created_at__date=today).count(),
    })


@staff_member_required(login_url="hbl_login")
def gift_codes(request, gift_id=None):
    instance = get_object_or_404(GiftCode, pk=gift_id) if gift_id else None
    form = GiftCodeForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _audit(request, "gift_code_saved", obj, {
            "code": obj.code, "type": obj.reward_type, "value": str(obj.value),
            "max_redemptions": obj.max_redemptions,
        })
        messages.success(request, "Código de regalo guardado.")
        return redirect("hbl_control_gifts")
    return render(request, "hbl/control/gifts.html", {
        "form": form, "editing": instance,
        "items": GiftCode.objects.annotate(redemption_count=Count("redemptions")).all(),
        "recent_redemptions": GiftRedemption.objects.select_related("gift", "user")[:40],
    })
