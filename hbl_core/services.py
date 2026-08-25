from datetime import datetime, time, timedelta, timezone as dt_timezone
import secrets
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    DailyAssignment,
    Deposit,
    ListeningSession,
    Membership,
    MembershipPlan,
    PlatformConfig,
    CurrencyRate,
    ReferralEarning,
    ReferralPayroll,
    ReferralTier,
    RewardLedger,
    Track,
    Withdrawal,
    GiftCode,
    ReferralUpgradeClaim,
    GiftRedemption,
    WheelConfig,
    WheelPrize,
    WheelSpin,
)
from .payment_policies import CRYPTO_WITHDRAWAL_SLUGS, detect_usdt_withdrawal_network

User = get_user_model()
MONEY = Decimal("0.01")


class HBLError(Exception):
    pass


def money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)




def currency_rate(code):
    code = (code or "").upper()
    config = PlatformConfig.get_solo()
    if code == config.base_currency_code.upper():
        return Decimal("1")
    row = CurrencyRate.objects.filter(code=code, active=True).first()
    if not row:
        raise HBLError(f"No hay una tasa activa para {code}.")
    return Decimal(row.rate_to_base)


def convert_currency(amount, from_code, to_code):
    """Convierte mediante la moneda base. rate_to_base = base por 1 unidad de moneda."""
    amount = Decimal(amount)
    from_code = (from_code or "").upper()
    to_code = (to_code or "").upper()
    if from_code == to_code:
        return amount
    base_amount = amount * currency_rate(from_code)
    return base_amount / currency_rate(to_code)


def display_money(amount, currency_code):
    return convert_currency(amount, PlatformConfig.get_solo().base_currency_code, currency_code).quantize(MONEY, rounding=ROUND_HALF_UP)




def user_timezone(user):
    name = (getattr(user, "timezone_name", "") or "UTC").strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def user_localdate(user, at=None):
    at = at or timezone.now()
    return at.astimezone(user_timezone(user)).date()


def user_day_bounds(user, day=None):
    tz = user_timezone(user)
    day = day or user_localdate(user)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(dt_timezone.utc), end_local.astimezone(dt_timezone.utc)

def _locked_user(user_id):
    return User.objects.select_for_update().get(pk=user_id)


def _credit_locked(user, amount, kind, reference="", metadata=None):
    amount = money(amount)
    if amount <= 0:
        raise HBLError("El crédito debe ser mayor que cero.")
    user.saldo = money(Decimal(user.saldo or 0) + amount)
    user.save(update_fields=["saldo"])
    RewardLedger.objects.create(
        user=user,
        kind=kind,
        amount=amount,
        balance_after=user.saldo,
        reference=reference,
        metadata=metadata or {},
    )
    return user


def _debit_locked(user, amount, kind, reference="", metadata=None):
    amount = money(amount)
    if amount <= 0:
        raise HBLError("El débito debe ser mayor que cero.")
    current = Decimal(user.saldo or 0)
    if current < amount:
        raise HBLError("Saldo insuficiente.")
    user.saldo = money(current - amount)
    user.save(update_fields=["saldo"])
    RewardLedger.objects.create(
        user=user,
        kind=kind,
        amount=-amount,
        balance_after=user.saldo,
        reference=reference,
        metadata=metadata or {},
    )
    return user


@transaction.atomic
def credit_balance(user_id, amount, kind, reference="", metadata=None):
    return _credit_locked(_locked_user(user_id), amount, kind, reference, metadata)


@transaction.atomic
def adjust_balance_admin(user_id, amount, direction, reference="", metadata=None):
    user = _locked_user(user_id)
    if direction == "credit":
        return _credit_locked(user, amount, RewardLedger.Kind.ADMIN, reference, metadata)
    if direction == "debit":
        return _debit_locked(user, amount, RewardLedger.Kind.ADMIN, reference, metadata)
    raise HBLError("Dirección de ajuste inválida.")


def current_membership(user):
    now = timezone.now()
    Membership.objects.filter(
        user=user, status=Membership.Status.ACTIVE, ends_at__lte=now
    ).update(status=Membership.Status.EXPIRED)
    return (
        Membership.objects.select_related("plan")
        .filter(user=user, status=Membership.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .order_by("-ends_at")
        .first()
    )


def plan_price_nio(plan, rate=None):
    rate = Decimal(rate) if rate is not None else currency_rate("USD")
    return money(Decimal(plan.price_usd) * rate)


@transaction.atomic
def activate_membership_admin(user_id, plan_id, actor_id=None, *, days=None):
    user = _locked_user(user_id)
    plan = MembershipPlan.objects.get(pk=plan_id, active=True)
    config = PlatformConfig.get_solo()
    now = timezone.now()
    Membership.objects.select_for_update().filter(
        user_id=user_id, status=Membership.Status.ACTIVE, ends_at__gt=now
    ).update(status=Membership.Status.CANCELED)
    membership = Membership.objects.create(
        user=user, plan=plan, status=Membership.Status.ACTIVE,
        starts_at=now, ends_at=now + timedelta(days=int(days or plan.duration_days)),
        price_usd_snapshot=plan.price_usd, exchange_rate_snapshot=currency_rate("USD"),
        daily_reward_snapshot=plan.daily_reward_nio, daily_tracks_snapshot=plan.daily_tracks,
        activated_by_id=actor_id if actor_id else None,
    )
    return membership


@transaction.atomic
def purchase_plan(user_id, plan_id, actor_id=None):
    user = _locked_user(user_id)
    plan = MembershipPlan.objects.select_for_update().get(pk=plan_id, active=True)
    config = PlatformConfig.get_solo()
    now = timezone.now()
    active = Membership.objects.select_for_update().filter(
        user_id=user_id, status=Membership.Status.ACTIVE, ends_at__gt=now
    ).first()
    if active:
        raise HBLError("Ya tienes una membresía activa. Espera a que termine o pide al administrador que la gestione.")
    cost = plan_price_nio(plan)
    _debit_locked(
        user, cost, RewardLedger.Kind.PLAN_PURCHASE,
        reference=f"plan:{plan.id}:{now:%Y%m%d%H%M%S}",
        metadata={"plan": plan.name, "price_usd": str(plan.price_usd), "rate": str(currency_rate("USD")), "base_currency": config.base_currency_code},
    )
    membership = Membership.objects.create(
        user=user, plan=plan, status=Membership.Status.ACTIVE,
        starts_at=now, ends_at=now + timedelta(days=plan.duration_days),
        price_usd_snapshot=plan.price_usd,
        exchange_rate_snapshot=currency_rate("USD"),
        daily_reward_snapshot=plan.daily_reward_nio,
        daily_tracks_snapshot=plan.daily_tracks,
        activated_by_id=actor_id if actor_id else None,
    )
    return membership


def _reward_split(total, count):
    total = money(total)
    count = int(count)
    cents = int(total * 100)
    base, remainder = divmod(cents, count)
    return [Decimal(base + (1 if i < remainder else 0)) / Decimal(100) for i in range(count)]


@transaction.atomic
def ensure_daily_assignments(user):
    user = _locked_user(user.id)
    membership = current_membership(user)
    if not membership:
        return None, []
    today = user_localdate(user)
    existing = list(
        DailyAssignment.objects.select_related("track")
        .filter(user=user, assignment_date=today)
        .order_by("position")
    )
    if existing:
        if all(item.membership_id == membership.id for item in existing):
            return membership, existing
        if any(item.completed_at for item in existing):
            raise HBLError("Tu plan cambió después de iniciar las tareas de hoy. El nuevo nivel comenzará sus tareas mañana.")
        DailyAssignment.objects.filter(user=user, assignment_date=today).delete()

    count = int(membership.daily_tracks_snapshot or 3)
    eligible = list(
        membership.plan.tracks.filter(active=True).distinct().order_by("id")
    )
    if len(eligible) < count:
        extra = list(
            Track.objects.filter(active=True)
            .filter(Q(allowed_plans=membership.plan) | Q(allowed_plans__isnull=True))
            .distinct().order_by("id")
        )
        seen = {t.id for t in eligible}
        eligible.extend(t for t in extra if t.id not in seen)
    if len(eligible) < count:
        raise HBLError(f"No hay suficientes canciones activas para tu plan. Se necesitan {count}.")

    # Selección determinista por usuario/fecha para que la lista no cambie al recargar.
    seed = (user.id * 131 + today.toordinal()) % len(eligible)
    ordered = eligible[seed:] + eligible[:seed]
    rewards = _reward_split(membership.daily_reward_snapshot, count)
    assignments = []
    for idx, track in enumerate(ordered[:count], start=1):
        assignments.append(DailyAssignment.objects.create(
            user=user, membership=membership, track=track, assignment_date=today,
            position=idx, reward_amount=rewards[idx-1],
        ))
    return membership, assignments


@transaction.atomic
def start_listening(user, assignment, client_nonce="", ip_hash=""):
    user = _locked_user(user.id)
    assignment = DailyAssignment.objects.select_for_update().select_related("track", "membership").get(
        pk=assignment.pk, user=user
    )
    if assignment.assignment_date != user_localdate(user):
        raise HBLError("Esta canción pertenece a otro día. Actualiza tu panel.")
    if assignment.completed_at:
        raise HBLError("Esta canción ya fue completada hoy.")
    if not assignment.membership.is_current:
        raise HBLError("Tu membresía no está activa.")

    now = timezone.now()
    timeout = now - timedelta(hours=2)
    today = user_localdate(user)
    ListeningSession.objects.filter(user=user, status=ListeningSession.Status.STARTED).filter(
        Q(started_at__lt=timeout) | ~Q(assignment__assignment_date=today)
    ).update(status=ListeningSession.Status.EXPIRED)
    existing = ListeningSession.objects.filter(
        user=user, status=ListeningSession.Status.STARTED, started_at__gte=timeout,
        assignment__assignment_date=today,
    ).first()
    if existing:
        if existing.assignment_id == assignment.id:
            return existing, False
        raise HBLError("Ya tienes otra escucha activa. Termínala antes de iniciar una nueva.")

    session = ListeningSession.objects.create(
        user=user, track=assignment.track, assignment=assignment,
        client_nonce=(client_nonce or "")[:64], ip_hash=(ip_hash or "")[:64], last_ping_at=now,
    )
    return session, True


@transaction.atomic
def listening_heartbeat(user_id, session_id):
    session = ListeningSession.objects.select_for_update().select_related("track").get(pk=session_id, user_id=user_id)
    if session.status != ListeningSession.Status.STARTED:
        raise HBLError("Esta sesión ya no está activa.")
    now = timezone.now()
    if session.last_ping_at:
        delta = (now - session.last_ping_at).total_seconds()
        if 2 <= delta <= 10:
            session.verified_seconds += max(1, min(6, int(delta)))
    session.last_ping_at = now
    session.save(update_fields=["verified_seconds", "last_ping_at"])
    global_required = int(PlatformConfig.get_solo().listen_verification_seconds or 10)
    track_required = int(getattr(session.track, "min_listen_seconds", 0) or 0)
    required = max(global_required, track_required)
    return session, max(0, required - session.verified_seconds)


@transaction.atomic
def complete_listening(user_id, session_id):
    """
    Completa una sesión de escucha de forma segura.

    IMPORTANTE:
    No usamos select_related() junto con select_for_update()
    sobre ListeningSession.assignment porque assignment es nullable
    y PostgreSQL puede rechazar FOR UPDATE sobre un OUTER JOIN.
    """

    # ---------------------------------------------------------
    # 1. Bloquear únicamente la fila de ListeningSession
    # ---------------------------------------------------------
    session = (
        ListeningSession.objects
        .select_for_update()
        .get(
            pk=session_id,
            user_id=user_id,
        )
    )

    # ---------------------------------------------------------
    # 2. Si ya fue recompensada, no volver a procesarla
    # ---------------------------------------------------------
    if session.status == ListeningSession.Status.REWARDED:
        return session, False

    # ---------------------------------------------------------
    # 3. Validar estado
    # ---------------------------------------------------------
    if session.status != ListeningSession.Status.STARTED:
        raise HBLError(
            "Esta sesión ya no puede generar recompensa."
        )

    if not session.assignment_id:
        raise HBLError(
            "La sesión no está asociada a una tarea válida."
        )

    # ---------------------------------------------------------
    # 4. Obtener y bloquear la tarea por separado
    # ---------------------------------------------------------
    try:
        assignment = (
            DailyAssignment.objects
            .select_for_update()
            .select_related(
                "track",
                "membership",
                "membership__plan",
            )
            .get(
                pk=session.assignment_id,
                user_id=user_id,
            )
        )

    except DailyAssignment.DoesNotExist:
        raise HBLError(
            "La tarea asociada a esta escucha ya no existe."
        )

    # ---------------------------------------------------------
    # 5. Validar que sesión y tarea tengan la misma canción
    # ---------------------------------------------------------
    if session.track_id != assignment.track_id:
        raise HBLError(
            "La canción de la sesión no coincide con la tarea."
        )

    # ---------------------------------------------------------
    # 6. Si la tarea ya estaba completada
    # ---------------------------------------------------------
    if assignment.completed_at:
        session.status = ListeningSession.Status.REWARDED
        session.reward_amount = Decimal("0.00")
        session.rewarded_at = assignment.completed_at

        session.save(
            update_fields=[
                "status",
                "reward_amount",
                "rewarded_at",
            ]
        )

        return session, False

    # ---------------------------------------------------------
    # 7. Bloquear usuario
    # ---------------------------------------------------------
    user_for_day = _locked_user(user_id)

    # ---------------------------------------------------------
    # 8. Validar fecha local
    # ---------------------------------------------------------
    today = user_localdate(user_for_day)

    if assignment.assignment_date != today:
        raise HBLError(
            "La tarea diaria ya venció. "
            "Las tareas se renuevan automáticamente "
            "al comenzar un nuevo día en tu zona horaria."
        )

    # ---------------------------------------------------------
    # 9. Calcular segundos requeridos
    # ---------------------------------------------------------
    config = PlatformConfig.get_solo()

    global_required = int(
        config.listen_verification_seconds or 10
    )

    track_required = int(
        getattr(
            assignment.track,
            "min_listen_seconds",
            0,
        ) or 0
    )

    required_seconds = max(
        global_required,
        track_required,
    )

    # ---------------------------------------------------------
    # 10. Validar tiempo real desde que inició la sesión
    # ---------------------------------------------------------
    now = timezone.now()

    elapsed_seconds = max(
        0,
        int(
            (
                now - session.started_at
            ).total_seconds()
        ),
    )

    if elapsed_seconds < required_seconds:
        remaining_time = (
            required_seconds - elapsed_seconds
        )

        raise HBLError(
            f"Debes mantener la reproducción activa "
            f"{remaining_time} segundos más."
        )

    # ---------------------------------------------------------
    # 11. Validar segundos confirmados por heartbeat
    # ---------------------------------------------------------
    verified_seconds = int(
        session.verified_seconds or 0
    )

    if verified_seconds < required_seconds:
        remaining_verified = max(
            1,
            required_seconds - verified_seconds,
        )

        raise HBLError(
            f"Faltan {remaining_verified} segundos "
            f"de escucha verificada."
        )

    # ---------------------------------------------------------
    # 12. Marcar esta canción como completada
    # ---------------------------------------------------------
    assignment.completed_at = now

    assignment.save(
        update_fields=[
            "completed_at",
        ]
    )

    # ---------------------------------------------------------
    # 13. Ver cuántas canciones quedan pendientes
    # ---------------------------------------------------------
    remaining = (
        DailyAssignment.objects
        .filter(
            user_id=user_id,
            membership_id=assignment.membership_id,
            assignment_date=assignment.assignment_date,
            completed_at__isnull=True,
        )
        .count()
    )

    # La recompensa NO se acredita canción por canción.
    reward = Decimal("0.00")
    credited = False

    # ---------------------------------------------------------
    # 14. Solamente cuando completa TODA la playlist
    # ---------------------------------------------------------
    if remaining == 0:

        daily_reference = (
            f"daily:"
            f"{assignment.membership_id}:"
            f"{assignment.assignment_date.isoformat()}"
        )

        # -----------------------------------------------------
        # Evitar doble recompensa
        # -----------------------------------------------------
        prior = (
            RewardLedger.objects
            .filter(
                user_id=user_id,
                kind=RewardLedger.Kind.MEMBERSHIP_REWARD,
                reference=daily_reference,
            )
            .first()
        )

        if prior:

            # Ya había sido acreditada.
            reward = money(
                prior.amount
            )

            credited = False

        else:

            reward = money(
                assignment.membership.daily_reward_snapshot
            )

            # -------------------------------------------------
            # Validar límite diario
            # -------------------------------------------------
            if config.daily_listen_reward_cap > 0:

                day_start, day_end = user_day_bounds(
                    user_for_day,
                    assignment.assignment_date,
                )

                earned = (
                    RewardLedger.objects
                    .filter(
                        user_id=user_id,
                        kind__in=[
                            RewardLedger.Kind.LISTEN,
                            RewardLedger.Kind.MEMBERSHIP_REWARD,
                        ],
                        created_at__gte=day_start,
                        created_at__lt=day_end,
                    )
                    .aggregate(
                        total=Sum("amount")
                    )["total"]
                    or Decimal("0")
                )

                if (
                    Decimal(earned)
                    + Decimal(reward)
                    > Decimal(
                        config.daily_listen_reward_cap
                    )
                ):
                    raise HBLError(
                        "La recompensa diaria supera "
                        "el límite configurado por "
                        "la plataforma."
                    )

            # -------------------------------------------------
            # Acreditar saldo
            # -------------------------------------------------
            _credit_locked(
                user_for_day,
                reward,
                RewardLedger.Kind.MEMBERSHIP_REWARD,
                reference=daily_reference,
                metadata={
                    "membership_id":
                        assignment.membership_id,

                    "plan":
                        assignment.membership.plan.name,

                    "assignment_date":
                        assignment
                        .assignment_date
                        .isoformat(),

                    "tracks_required":
                        assignment
                        .membership
                        .daily_tracks_snapshot,
                },
            )

            credited = True

    # ---------------------------------------------------------
    # 15. Cerrar sesión de escucha
    # ---------------------------------------------------------
    session.status = (
        ListeningSession.Status.REWARDED
    )

    session.rewarded_at = now

    # Solo la última canción lleva el monto diario
    # en la sesión que produjo la acreditación.
    session.reward_amount = (
        reward
        if credited
        else Decimal("0.00")
    )

    session.save(
        update_fields=[
            "status",
            "rewarded_at",
            "reward_amount",
        ]
    )

    # ---------------------------------------------------------
    # 16. Retornar
    # ---------------------------------------------------------
    return session, credited

@transaction.atomic
def approve_deposit(deposit_id, *, transaction_id="", notes=""):
    deposit = Deposit.objects.select_for_update().select_related("user").get(pk=deposit_id)
    if deposit.status == Deposit.Status.APPROVED:
        return deposit, False
    if deposit.status not in {Deposit.Status.PENDING, Deposit.Status.PROCESSING}:
        raise HBLError("La recarga no está pendiente de aprobación.")

    user = _locked_user(deposit.user_id)
    _credit_locked(
        user,
        deposit.amount,
        RewardLedger.Kind.DEPOSIT,
        reference=str(deposit.id),
        metadata={"method": deposit.payment_method.kind, "currency": deposit.currency},
    )

    deposit.status = Deposit.Status.APPROVED
    deposit.processed_at = timezone.now()
    if transaction_id:
        deposit.transaction_id = transaction_id[:80]
    if notes:
        deposit.notes = notes
    deposit.save(update_fields=["status", "processed_at", "transaction_id", "notes"])

    config = PlatformConfig.get_solo()
    sponsor_id = getattr(user, "referido_por_id", None)
    pct = Decimal(config.referral_first_deposit_percent or 0)

    # La comisión de referido se paga UNA SOLA VEZ: únicamente sobre la
    # primera recarga aprobada del referido. El bloqueo de la fila de usuario
    # (_locked_user) serializa aprobaciones simultáneas del mismo usuario.
    has_previous_approved_deposit = Deposit.objects.filter(
        user_id=user.id,
        status=Deposit.Status.APPROVED,
    ).exclude(pk=deposit.pk).exists()

    if sponsor_id and pct > 0 and not has_previous_approved_deposit:
        bonus = money(Decimal(deposit.amount) * pct / Decimal("100"))
        if bonus > 0:
            reference = f"first-deposit-commission:{user.id}"
            earning, created = ReferralEarning.objects.get_or_create(
                reference=reference,
                defaults={
                    "sponsor_id": sponsor_id,
                    "referred_id": user.id,
                    "kind": ReferralEarning.Kind.FIRST_DEPOSIT,
                    "base_amount": deposit.amount,
                    "percent": pct,
                    "amount": bonus,
                },
            )
            if created:
                sponsor = _locked_user(sponsor_id)
                _credit_locked(
                    sponsor,
                    bonus,
                    RewardLedger.Kind.REFERRAL,
                    reference=reference,
                    metadata={
                        "referred_id": user.id,
                        "deposit_id": str(deposit.id),
                        "percent": str(pct),
                        "commission_scope": "first_approved_deposit_only",
                    },
                )

    return deposit, True


@transaction.atomic
def reject_deposit(deposit_id, notes=""):
    deposit = Deposit.objects.select_for_update().get(pk=deposit_id)
    if deposit.status == Deposit.Status.APPROVED:
        raise HBLError("Una recarga aprobada no se puede rechazar desde esta acción.")
    if deposit.status == Deposit.Status.REJECTED:
        return deposit, False
    deposit.status = Deposit.Status.REJECTED
    deposit.processed_at = timezone.now()
    deposit.notes = notes or deposit.notes
    deposit.save(update_fields=["status", "processed_at", "notes"])
    return deposit, True


@transaction.atomic
def request_withdrawal(user_id, payout_account, requested_amount, requested_currency=None):
    """Crea un retiro que siempre se paga en USDT por TRC20 o BEP20.

    requested_amount se interpreta en la moneda local asociada al país del cliente.
    amount/fee/net_amount quedan congelados en moneda base para contabilidad y
    payout_amount queda congelado en la moneda real del método de retiro.
    """
    config = PlatformConfig.get_solo()
    user = _locked_user(user_id)
    if payout_account.user_id != user_id or not payout_account.active:
        raise HBLError("Método de retiro inválido.")
    method = getattr(payout_account, "withdrawal_method", None)
    if not method or not method.active:
        raise HBLError("Ese método de retiro ya no está disponible.")
    if method.slug not in CRYPTO_WITHDRAWAL_SLUGS:
        raise HBLError("Solo se permiten retiros USDT por TRC20 o BEP20.")
    detected_slug = detect_usdt_withdrawal_network(payout_account.identifier)
    if detected_slug != method.slug:
        raise HBLError("La dirección no corresponde a la red de retiro guardada.")
    if method.country and method.country != getattr(user, "country", ""):
        raise HBLError("Ese método de retiro no está disponible para tu país.")

    base_code = config.base_currency_code.upper()
    requested_currency = (requested_currency or getattr(user, "preferred_currency", "") or base_code).upper()
    payout_currency = method.payout_currency_for(user)
    if payout_currency != "USDT":
        raise HBLError("Los retiros solo pueden pagarse en USDT.")
    requested_amount = Decimal(requested_amount)
    if requested_amount <= 0:
        raise HBLError("El monto a retirar debe ser mayor que cero.")

    requested_rate = currency_rate(requested_currency)
    payout_rate = currency_rate(payout_currency)
    amount = money(requested_amount * requested_rate)

    effective_min = max(Decimal(config.withdrawal_min or 0), Decimal(method.min_amount_nio or 0))
    if amount < effective_min:
        local_min = (effective_min / requested_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        raise HBLError(
            f"El retiro mínimo para {method.name} es {local_min} {requested_currency} "
            f"(equivale a {config.base_currency_symbol}{money(effective_min)} {base_code})."
        )
    if method.max_amount_nio and amount > Decimal(method.max_amount_nio):
        local_max = (Decimal(method.max_amount_nio) / requested_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        raise HBLError(f"El retiro máximo para {method.name} es {local_max} {requested_currency}.")

    pending = Withdrawal.objects.filter(
        user_id=user_id, status__in=[Withdrawal.Status.PENDING, Withdrawal.Status.PROCESSING],
    ).exists()
    if pending:
        raise HBLError("Ya tienes un retiro pendiente o en proceso.")

    pct = Decimal(method.fee_percent if method.fee_percent is not None else config.withdrawal_fee_percent or 0)
    fixed = Decimal(method.fee_fixed_nio or 0)
    fee = money((amount * pct / Decimal("100")) + fixed)
    net = money(amount - fee)
    if net <= 0:
        raise HBLError("El monto neto del retiro debe ser mayor que cero.")

    payout_amount = (net / payout_rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    withdrawal = Withdrawal.objects.create(
        user_id=user_id, payout_account=payout_account, payout_kind=method.slug,
        payout_label=method.name, payout_identifier=payout_account.identifier, payout_network=method.network,
        amount=amount, fee=fee, net_amount=net, base_currency=base_code,
        requested_amount=requested_amount.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP),
        requested_currency=requested_currency, payout_amount=payout_amount, payout_currency=payout_currency,
        requested_rate_to_base=requested_rate, payout_rate_to_base=payout_rate,
    )
    _debit_locked(
        user, amount, RewardLedger.Kind.WITHDRAWAL, reference=str(withdrawal.id),
        metadata={
            "fee_base": str(fee), "net_base": str(net), "method": method.slug,
            "requested_amount": str(requested_amount), "requested_currency": requested_currency,
            "payout_amount": str(payout_amount), "payout_currency": payout_currency,
            "base_currency": base_code,
        },
    )
    return withdrawal


@transaction.atomic
def reject_withdrawal(withdrawal_id, notes=""):
    withdrawal = Withdrawal.objects.select_for_update().get(pk=withdrawal_id)
    if withdrawal.status == Withdrawal.Status.REJECTED:
        return withdrawal, False
    if withdrawal.status == Withdrawal.Status.PAID:
        raise HBLError("Un retiro pagado no se puede rechazar.")
    if withdrawal.status not in {Withdrawal.Status.PENDING, Withdrawal.Status.PROCESSING}:
        raise HBLError("Este retiro no puede rechazarse.")

    user = _locked_user(withdrawal.user_id)
    _credit_locked(
        user,
        withdrawal.amount,
        RewardLedger.Kind.WITHDRAWAL_REFUND,
        reference=str(withdrawal.id),
        metadata={"reason": notes or "Retiro rechazado"},
    )
    withdrawal.status = Withdrawal.Status.REJECTED
    withdrawal.processed_at = timezone.now()
    withdrawal.notes = notes or withdrawal.notes
    withdrawal.save(update_fields=["status", "processed_at", "notes"])
    return withdrawal, True


@transaction.atomic
def mark_withdrawal_paid(withdrawal_id, admin_reference=""):
    withdrawal = Withdrawal.objects.select_for_update().get(pk=withdrawal_id)
    if withdrawal.status == Withdrawal.Status.PAID:
        return withdrawal, False
    if withdrawal.status not in {Withdrawal.Status.PENDING, Withdrawal.Status.PROCESSING}:
        raise HBLError("Este retiro no está disponible para pago.")
    withdrawal.status = Withdrawal.Status.PAID
    withdrawal.processed_at = timezone.now()
    withdrawal.admin_reference = (admin_reference or "")[:180]
    withdrawal.save(update_fields=["status", "processed_at", "admin_reference"])
    return withdrawal, True


def qualified_referral_count(user):
    return User.objects.filter(
        referido_por=user,
        hbl_deposits__status=Deposit.Status.APPROVED,
    ).distinct().count()


def active_referral_count(user, days=None):
    config = PlatformConfig.get_solo()
    days = days or config.referral_activity_days
    cutoff = timezone.now() - timedelta(days=days)
    return User.objects.filter(
        referido_por=user,
        hbl_listening_sessions__status=ListeningSession.Status.REWARDED,
        hbl_listening_sessions__rewarded_at__gte=cutoff,
    ).distinct().count()


def referral_tier_for_count(count):
    return ReferralTier.objects.filter(
        active=True,
        min_active_referrals__lte=count,
    ).order_by("-min_active_referrals").first()


@transaction.atomic
def create_referral_payroll(user, week_start=None, pay=False):
    today = timezone.localdate()
    week_start = week_start or (today - timedelta(days=today.weekday()))
    count = active_referral_count(user)
    tier = referral_tier_for_count(count)
    amount = money(tier.weekly_salary if tier else Decimal("0"))
    payroll, created = ReferralPayroll.objects.get_or_create(
        user=user,
        week_start=week_start,
        defaults={"active_referrals": count, "tier": tier, "amount": amount},
    )

    # Si la nómina se generó primero sin --pay, una ejecución posterior con --pay
    # puede pagarla exactamente una vez.
    if pay and payroll.status == ReferralPayroll.Status.PENDING and payroll.amount > 0:
        locked = _locked_user(user.id)
        _credit_locked(
            locked,
            payroll.amount,
            RewardLedger.Kind.REFERRAL_SALARY,
            reference=f"payroll:{payroll.id}",
            metadata={
                "week_start": str(week_start),
                "active_referrals": payroll.active_referrals,
                "tier": payroll.tier.name if payroll.tier else None,
            },
        )
        payroll.status = ReferralPayroll.Status.PAID
        payroll.paid_at = timezone.now()
        payroll.save(update_fields=["status", "paid_at"])
    return payroll, created
def _next_plan_for_membership(membership):
    if not membership:
        return None
    plans = list(MembershipPlan.objects.filter(active=True).order_by("price_usd", "sort_order", "id"))
    current_index = None
    for idx, plan in enumerate(plans):
        if plan.id == membership.plan_id:
            current_index = idx
            break
    if current_index is None:
        return None
    return plans[current_index + 1] if current_index + 1 < len(plans) else None


def eligible_referral_upgrade(user):
    config = PlatformConfig.get_solo()
    membership = current_membership(user)
    if not membership:
        return None
    qualified = qualified_referral_count(user)
    block = max(1, int(config.free_upgrade_referrals_required or 5))
    prior_claims = ReferralUpgradeClaim.objects.filter(user=user).count()
    required = block * (prior_claims + 1)
    if qualified < required:
        return None
    next_plan = _next_plan_for_membership(membership)
    if not next_plan:
        return None
    already = ReferralUpgradeClaim.objects.filter(user=user, to_plan=next_plan).exists()
    if already:
        return None
    return {
        "membership": membership,
        "next_plan": next_plan,
        "qualified_referrals": qualified,
        "required": required,
        "block_size": block,
        "prior_claims": prior_claims,
    }


@transaction.atomic
def claim_referral_upgrade(user_id):
    user = _locked_user(user_id)
    data = eligible_referral_upgrade(user)
    if not data:
        raise HBLError("Aún no cumples los requisitos para subir de plan sin inversión.")
    membership = Membership.objects.select_for_update().get(pk=data["membership"].pk)
    if membership.status != Membership.Status.ACTIVE:
        raise HBLError("Tu membresía ya no está activa.")
    next_plan = MembershipPlan.objects.select_for_update().get(pk=data["next_plan"].pk)
    config = PlatformConfig.get_solo()
    now = timezone.now()
    membership.status = Membership.Status.CANCELED
    membership.save(update_fields=["status"])
    new_membership = Membership.objects.create(
        user=user, plan=next_plan, status=Membership.Status.ACTIVE,
        starts_at=now, ends_at=now + timedelta(days=next_plan.duration_days),
        price_usd_snapshot=next_plan.price_usd, exchange_rate_snapshot=currency_rate("USD"),
        daily_reward_snapshot=next_plan.daily_reward_nio, daily_tracks_snapshot=next_plan.daily_tracks,
        activated_by_id=None,
    )
    ReferralUpgradeClaim.objects.create(
        user=user,
        from_plan=membership.plan,
        to_plan=next_plan,
        qualified_referrals=data["qualified_referrals"],
    )
    return new_membership




def _active_membership_locked(user_id):
    now = timezone.now()
    return Membership.objects.select_for_update().filter(
        user_id=user_id,
        status=Membership.Status.ACTIVE,
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("-ends_at").first()


@transaction.atomic
def spin_wheel(user_id):
    """Giro promocional gratuito. El resultado se decide exclusivamente en el servidor."""
    user = _locked_user(user_id)
    config = WheelConfig.objects.select_for_update().get_or_create(pk=1)[0]
    if not config.enabled:
        raise HBLError("La ruleta no está disponible en este momento.")
    membership = _active_membership_locked(user_id)
    if config.require_active_membership and not membership:
        raise HBLError("Necesitas una membresía activa para usar la ruleta.")
    platform = PlatformConfig.get_solo()
    if platform.wheel_requires_qualified_referral:
        qcount = qualified_referral_count(user)
        needed = int(platform.wheel_min_qualified_referrals or 1)
        if qcount < needed:
            raise HBLError(f"La ruleta se habilita con {needed} referido(s) calificado(s) que hayan recargado.")

    today = user_localdate(user)
    day_start, day_end = user_day_bounds(user, today)
    today_spins = WheelSpin.objects.filter(user_id=user_id, created_at__gte=day_start, created_at__lt=day_end).count()
    if today_spins >= config.spins_per_day:
        raise HBLError("Ya utilizaste tus giros gratuitos de hoy.")
    if config.cooldown_minutes:
        last = WheelSpin.objects.filter(user_id=user_id).order_by("-created_at").first()
        if last and timezone.now() < last.created_at + timedelta(minutes=config.cooldown_minutes):
            raise HBLError("Aún debes esperar antes de tu próximo giro.")

    prizes = list(WheelPrize.objects.select_for_update().filter(active=True, weight__gt=0).order_by("sort_order", "id"))
    eligible = []
    for prize in prizes:
        if prize.total_stock and WheelSpin.objects.filter(prize=prize).count() >= prize.total_stock:
            continue
        if prize.daily_global_limit and WheelSpin.objects.filter(prize=prize, created_at__gte=day_start, created_at__lt=day_end).count() >= prize.daily_global_limit:
            continue
        eligible.append(prize)
    if not eligible:
        raise HBLError("No hay premios disponibles en este momento.")

    total_weight = sum(p.weight for p in eligible)
    pick = secrets.randbelow(total_weight)
    cursor = 0
    selected = eligible[-1]
    for prize in eligible:
        cursor += prize.weight
        if pick < cursor:
            selected = prize
            break

    reward_amount = Decimal("0.00")
    if selected.reward_type == WheelPrize.RewardType.BALANCE and selected.value > 0:
        reward_amount = money(selected.value)
        _credit_locked(
            user, reward_amount, RewardLedger.Kind.WHEEL,
            reference=f"wheel:{user_id}:{timezone.now():%Y%m%d%H%M%S%f}",
            metadata={"prize": selected.name, "prize_id": selected.id},
        )
    elif selected.reward_type == WheelPrize.RewardType.MEMBERSHIP_DAYS and selected.value > 0:
        if not membership:
            raise HBLError("Este premio requiere una membresía activa.")
        days = max(1, int(selected.value))
        membership.ends_at += timedelta(days=days)
        membership.save(update_fields=["ends_at"])

    spin = WheelSpin.objects.create(user=user, prize=selected, reward_amount=reward_amount)
    return spin


@transaction.atomic
def redeem_gift_code(user_id, raw_code):
    user = _locked_user(user_id)
    code = (raw_code or "").strip().upper()
    if not code:
        raise HBLError("Escribe un código de regalo.")
    gift = GiftCode.objects.select_for_update().filter(code__iexact=code).first()
    if not gift or not gift.active:
        raise HBLError("Código no válido o inactivo.")
    now = timezone.now()
    if gift.valid_from and now < gift.valid_from:
        raise HBLError("Este código todavía no está disponible.")
    if gift.valid_until and now > gift.valid_until:
        raise HBLError("Este código ya venció.")
    total_used = GiftRedemption.objects.filter(gift=gift).count()
    if gift.max_redemptions and total_used >= gift.max_redemptions:
        raise HBLError("Este código alcanzó su límite de usos.")
    user_used = GiftRedemption.objects.filter(gift=gift, user_id=user_id).count()
    if user_used >= gift.per_user_limit:
        raise HBLError("Ya utilizaste este código el máximo de veces permitido.")

    membership = _active_membership_locked(user_id)
    if gift.require_active_membership and not membership:
        raise HBLError("Este código requiere una membresía activa.")
    if gift.required_plan_id and (not membership or membership.plan_id != gift.required_plan_id):
        raise HBLError("Este código no corresponde a tu nivel actual.")

    reward_amount = Decimal("0.00")
    if gift.reward_type == GiftCode.RewardType.BALANCE:
        if gift.value <= 0:
            raise HBLError("Este código no tiene un valor válido.")
        reward_amount = money(gift.value)
        _credit_locked(
            user, reward_amount, RewardLedger.Kind.GIFT_CODE,
            reference=f"gift:{gift.id}:{user_id}:{user_used + 1}",
            metadata={"gift": gift.code, "gift_id": gift.id},
        )
    elif gift.reward_type == GiftCode.RewardType.MEMBERSHIP_DAYS:
        if not membership:
            raise HBLError("Necesitas una membresía activa para recibir días extra.")
        days = max(1, int(gift.value))
        membership.ends_at += timedelta(days=days)
        membership.save(update_fields=["ends_at"])

    redemption = GiftRedemption.objects.create(gift=gift, user=user, reward_amount=reward_amount)
    return redemption
