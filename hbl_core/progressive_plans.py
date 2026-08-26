from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Membership, MembershipPlan, PlatformConfig, RewardLedger
from .services import (
    HBLError,
    claim_referral_upgrade,
    currency_rate,
    display_money,
    eligible_referral_upgrade,
    money,
    plan_price_nio,
)

User = get_user_model()


def _active_memberships(user):
    """Devuelve las membresías activas del usuario, de menor a mayor nivel."""
    now = timezone.now()
    Membership.objects.filter(
        user=user,
        status=Membership.Status.ACTIVE,
        ends_at__lte=now,
    ).update(status=Membership.Status.EXPIRED)

    return list(
        Membership.objects.select_related("plan")
        .filter(
            user=user,
            status=Membership.Status.ACTIVE,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("plan__price_usd", "plan__sort_order", "plan_id")
    )


@transaction.atomic
def purchase_progressive_plan(user_id, plan_id):
    """
    Regla HLB:
    - Solo una membresía activa por nivel.
    - Si ya existe una membresía activa, la siguiente debe ser de un nivel superior.
    - Los niveles inferiores permanecen activos; no se cancelan al comprar uno superior.
    """
    user = User.objects.select_for_update().get(pk=user_id)
    plan = MembershipPlan.objects.select_for_update().get(pk=plan_id, active=True)
    config = PlatformConfig.get_solo()
    now = timezone.now()

    Membership.objects.select_for_update().filter(
        user_id=user_id,
        status=Membership.Status.ACTIVE,
        ends_at__lte=now,
    ).update(status=Membership.Status.EXPIRED)

    active = list(
        Membership.objects.select_for_update()
        .select_related("plan")
        .filter(
            user_id=user_id,
            status=Membership.Status.ACTIVE,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("plan__price_usd", "plan__sort_order", "plan_id")
    )

    if any(item.plan_id == plan.id for item in active):
        raise HBLError(
            f"Ya tienes una membresía activa del nivel {plan.name}. "
            "Solo puedes tener una membresía activa por nivel."
        )

    if active:
        highest = active[-1]
        if Decimal(plan.price_usd) <= Decimal(highest.plan.price_usd):
            raise HBLError(
                f"Tu nivel activo más alto es {highest.plan.name}. "
                "La siguiente membresía debe ser de un nivel superior."
            )

    cost = plan_price_nio(plan)
    current_balance = money(Decimal(user.saldo or 0))
    if current_balance < cost:
        raise HBLError("Saldo insuficiente.")

    user.saldo = money(current_balance - cost)
    user.save(update_fields=["saldo"])

    rate = currency_rate("USD")
    RewardLedger.objects.create(
        user=user,
        kind=RewardLedger.Kind.PLAN_PURCHASE,
        amount=-cost,
        balance_after=user.saldo,
        reference=f"plan:{plan.id}:{now:%Y%m%d%H%M%S%f}",
        metadata={
            "plan": plan.name,
            "price_usd": str(plan.price_usd),
            "rate": str(rate),
            "base_currency": config.base_currency_code,
            "purchase_rule": "one_active_per_level_higher_only",
        },
    )

    return Membership.objects.create(
        user=user,
        plan=plan,
        status=Membership.Status.ACTIVE,
        starts_at=now,
        ends_at=now + timezone.timedelta(days=plan.duration_days),
        price_usd_snapshot=plan.price_usd,
        exchange_rate_snapshot=rate,
        daily_reward_snapshot=plan.daily_reward_nio,
        daily_tracks_snapshot=plan.daily_tracks,
    )


@login_required
def plans(request):
    config = PlatformConfig.get_solo()
    active_memberships = _active_memberships(request.user)
    active_plan_ids = {item.plan_id for item in active_memberships}
    highest_active = active_memberships[-1] if active_memberships else None
    highest_price = Decimal(highest_active.plan.price_usd) if highest_active else None

    if request.method == "POST":
        action = request.POST.get("action", "buy")

        if action == "claim_upgrade":
            try:
                membership = claim_referral_upgrade(request.user.id)
                messages.success(
                    request,
                    f"Subiste gratis a {membership.plan.name} gracias a tus referidos calificados.",
                )
                return redirect("hbl_plans")
            except HBLError as exc:
                messages.error(request, str(exc))
                return redirect("hbl_plans")

        plan = get_object_or_404(
            MembershipPlan,
            pk=request.POST.get("plan_id"),
            active=True,
        )
        try:
            membership = purchase_progressive_plan(request.user.id, plan.id)
            messages.success(
                request,
                f"Plan {membership.plan.name} activado. Tus planes anteriores continúan activos.",
            )
            return redirect("hbl_plans")
        except HBLError as exc:
            messages.error(request, str(exc))
            return redirect("hbl_plans")

    plan_items = []
    for plan in MembershipPlan.objects.filter(active=True).order_by(
        "price_usd", "sort_order", "id"
    ):
        cost_nio = plan_price_nio(plan)
        try:
            cycle_usd = display_money(plan.projected_cycle_reward_nio, "USD")
        except HBLError:
            cycle_usd = Decimal("0")

        is_active = plan.id in active_plan_ids
        is_higher = highest_price is None or Decimal(plan.price_usd) > highest_price
        can_buy = (not is_active) and is_higher

        if is_active:
            block_reason = "Ya tienes este nivel activo."
        elif not is_higher:
            block_reason = "Solo puedes añadir un nivel superior al que ya tienes."
        else:
            block_reason = ""

        plan_items.append(
            {
                "plan": plan,
                "cost_nio": cost_nio,
                "cycle_usd": cycle_usd,
                "is_active": is_active,
                "can_buy": can_buy,
                "block_reason": block_reason,
            }
        )

    upgrade_option = eligible_referral_upgrade(request.user)

    return render(
        request,
        "hbl/plans_progressive.html",
        {
            "plan_items": plan_items,
            "active_memberships": active_memberships,
            "highest_active": highest_active,
            "config": config,
            "upgrade_option": upgrade_option,
        },
    )
