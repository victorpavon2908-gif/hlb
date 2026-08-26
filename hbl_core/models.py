import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PlatformConfig(models.Model):
    """Configuración de negocio editable desde Django Admin."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    exchange_rate_usd_nio = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("36.6200"),
        help_text="Unidades de la moneda base equivalentes a US$1. Se conserva por compatibilidad; las tasas activas se administran en Monedas.",
    )
    legal_notice = models.TextField(
        blank=True,
        default="HBL ofrece membresías de recompensas por tareas de escucha. Las recompensas, condiciones y vigencia deben mostrarse de forma transparente al usuario.",
    )
    minimum_deposit_usd = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("100.00"),
        help_text="Recarga mínima global expresada en USD. Se convierte a la moneda base usando la tasa USD activa.",
    )
    withdrawal_min = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("500.00"))
    withdrawal_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    referral_first_deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))
    daily_listen_reward_cap = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="0 = sin tope diario global por usuario.",
    )
    referral_activity_days = models.PositiveSmallIntegerField(default=7)
    signup_bonus = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    base_currency_code = models.CharField(max_length=12, default="NIO")
    base_currency_symbol = models.CharField(max_length=8, default="C$")
    free_upgrade_referrals_required = models.PositiveSmallIntegerField(default=5)
    wheel_requires_qualified_referral = models.BooleanField(default=True)
    wheel_min_qualified_referrals = models.PositiveSmallIntegerField(default=1)
    maintenance_mode = models.BooleanField(default=False)
    listen_verification_seconds = models.PositiveSmallIntegerField(default=10, help_text="Segundos efectivos requeridos por canción para validar la tarea.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración HBL"
        verbose_name_plural = "Configuración HBL"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        for field in ("minimum_deposit_usd", "withdrawal_min", "withdrawal_fee_percent", "referral_first_deposit_percent", "daily_listen_reward_cap", "signup_bonus", "exchange_rate_usd_nio"):
            if getattr(self, field) < 0:
                raise ValidationError({field: "No puede ser negativo."})
        if self.exchange_rate_usd_nio <= 0:
            raise ValidationError({"exchange_rate_usd_nio": "La tasa USD → moneda base debe ser mayor que cero."})
        if self.withdrawal_fee_percent > 100 or self.referral_first_deposit_percent > 100:
            raise ValidationError("Los porcentajes no pueden superar 100%.")
        if self.listen_verification_seconds < 5 or self.listen_verification_seconds > 120:
            raise ValidationError({"listen_verification_seconds": "Debe estar entre 5 y 120 segundos."})


class CurrencyRate(models.Model):
    """Tasa administrable: 1 unidad de esta moneda equivale a rate_to_base unidades de la moneda base."""
    code = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=12, blank=True)
    rate_to_base = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("1.0000000000"))
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.rate_to_base}"

    def clean(self):
        self.code = (self.code or "").upper().strip()
        if self.rate_to_base <= 0:
            raise ValidationError({"rate_to_base": "La tasa debe ser mayor que cero."})


class MembershipPlan(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    price_usd = models.DecimalField(max_digits=12, decimal_places=2)
    daily_reward_nio = models.DecimalField(max_digits=12, decimal_places=2)
    daily_tracks = models.PositiveSmallIntegerField(default=3)
    duration_days = models.PositiveSmallIntegerField(default=30)
    badge = models.CharField(max_length=40, blank=True)
    icon = models.CharField(max_length=16, blank=True, default="🎧")
    accent_from = models.CharField(max_length=7, blank=True, default="#7C5CFC")
    accent_to = models.CharField(max_length=7, blank=True, default="#25D9A6")
    active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_usd"]

    def __str__(self):
        return f"{self.name} · US${self.price_usd}"

    def clean(self):
        if self.price_usd <= 0:
            raise ValidationError({"price_usd": "El precio debe ser mayor que cero."})
        if self.daily_reward_nio < 0:
            raise ValidationError({"daily_reward_nio": "La recompensa no puede ser negativa."})
        if self.daily_tracks < 1 or self.daily_tracks > 20:
            raise ValidationError({"daily_tracks": "Debe estar entre 1 y 20 canciones por día."})
        if self.duration_days < 1 or self.duration_days > 366:
            raise ValidationError({"duration_days": "La vigencia debe estar entre 1 y 366 días."})

    @property
    def projected_cycle_reward_nio(self):
        return (Decimal(self.daily_reward_nio) * Decimal(self.duration_days)).quantize(Decimal("0.01"))


class Track(models.Model):
    title = models.CharField(max_length=160)
    artist = models.CharField(max_length=160, blank=True)
    slug = models.SlugField(max_length=180, unique=True)
    allowed_plans = models.ManyToManyField(MembershipPlan, blank=True, related_name="tracks", help_text="Vacío = disponible para todos los planes.")
    cover = models.ImageField(upload_to="hbl/covers/", blank=True, null=True)
    cover_url = models.URLField(blank=True)
    audio = models.FileField(upload_to="hbl/audio/", blank=True, null=True)
    audio_url = models.URLField(blank=True)
    duration_seconds = models.PositiveIntegerField(default=180)
    min_listen_seconds = models.PositiveIntegerField(default=10)
    reward_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    daily_user_limit = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-featured", "title"]
        indexes = [models.Index(fields=["active", "featured"])]

    def __str__(self):
        return f"{self.title} — {self.artist}" if self.artist else self.title

    @property
    def playable_url(self):
        if self.audio:
            return self.audio.url
        return self.audio_url

    @property
    def cover_src(self):
        if self.cover:
            return self.cover.url
        return self.cover_url

    def clean(self):
        if not self.audio and not self.audio_url:
            raise ValidationError("Debes cargar un audio o indicar una URL de audio.")
        if self.min_listen_seconds > self.duration_seconds:
            raise ValidationError({"min_listen_seconds": "No puede superar la duración de la pista."})
        if self.reward_amount < 0:
            raise ValidationError({"reward_amount": "La recompensa no puede ser negativa."})


class Membership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        EXPIRED = "expired", "Vencida"
        CANCELED = "canceled", "Cancelada"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_memberships")
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    price_usd_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    exchange_rate_snapshot = models.DecimalField(max_digits=10, decimal_places=4)
    daily_reward_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    daily_tracks_snapshot = models.PositiveSmallIntegerField(default=3)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="hbl_memberships_activated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [models.Index(fields=["user", "status", "ends_at"], name="hbl_member_user_status_end")]

    def __str__(self):
        return f"{self.user} · {self.plan.name}"

    @property
    def is_current(self):
        now = timezone.now()
        return self.status == self.Status.ACTIVE and self.starts_at <= now < self.ends_at


class DailyAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_daily_assignments")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="daily_assignments")
    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name="daily_assignments")
    assignment_date = models.DateField()
    position = models.PositiveSmallIntegerField()
    reward_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["assignment_date", "position"]
        constraints = [
            models.UniqueConstraint(fields=["user", "assignment_date", "position"], name="uniq_hbl_daily_assignment_position"),
            models.UniqueConstraint(fields=["user", "assignment_date", "track"], name="uniq_hbl_daily_assignment_track"),
        ]
        indexes = [models.Index(fields=["user", "assignment_date", "completed_at"], name="hbl_daily_user_date_done")]

    def __str__(self):
        return f"{self.user} · {self.assignment_date} · {self.position}"


class ListeningSession(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Iniciada"
        REWARDED = "rewarded", "Recompensada"
        EXPIRED = "expired", "Expirada"
        REJECTED = "rejected", "Rechazada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_listening_sessions")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="listening_sessions")
    assignment = models.ForeignKey(DailyAssignment, on_delete=models.SET_NULL, blank=True, null=True, related_name="listening_sessions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    started_at = models.DateTimeField(auto_now_add=True)
    rewarded_at = models.DateTimeField(blank=True, null=True)
    reward_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    verified_seconds = models.PositiveIntegerField(default=0)
    last_ping_at = models.DateTimeField(blank=True, null=True)
    client_nonce = models.CharField(max_length=64, blank=True, db_index=True)
    ip_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "status", "started_at"]),
            models.Index(fields=["user", "track", "status"]),
        ]


class RewardLedger(models.Model):
    class Kind(models.TextChoices):
        LISTEN = "listen", "Escucha"
        MEMBERSHIP_REWARD = "membership_reward", "Recompensa de membresía"
        PLAN_PURCHASE = "plan_purchase", "Compra de plan"
        REFERRAL = "referral", "Referido"
        REFERRAL_SALARY = "referral_salary", "Sueldo por referidos"
        DEPOSIT = "deposit", "Recarga"
        WITHDRAWAL = "withdrawal", "Retiro"
        WITHDRAWAL_REFUND = "withdrawal_refund", "Reembolso de retiro"
        WHEEL = "wheel", "Premio de ruleta"
        GIFT_CODE = "gift_code", "Código de regalo"
        SIGNUP = "signup", "Registro"
        ADMIN = "admin", "Ajuste administrativo"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_ledger")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "kind", "created_at"])]


class PaymentMethod(models.Model):
    class Kind(models.TextChoices):
        BANK = "bank", "Transferencia bancaria"
        BINANCE_PAY = "binance_pay", "Binance Pay"
        BINANCE_ID = "binance_id", "Binance Pay ID / Binance ID"
        USDT_TRC20 = "usdt_trc20", "USDT TRC20"
        USDT_BEP20 = "usdt_bep20", "USDT BEP20"
        CRYPTO_OTHER = "crypto_other", "Otra criptomoneda/red"
        REMITTANCE = "remittance", "Giro / remesa"
        MOBILE_WALLET = "mobile_wallet", "Billetera móvil"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    label = models.CharField(max_length=100)
    currency = models.CharField(max_length=12, default="NIO")
    network = models.CharField(max_length=40, blank=True)
    destination = models.CharField(max_length=255, blank=True)
    instructions = models.TextField(blank=True)
    min_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("1.00000000"))
    max_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"), help_text="0 = sin máximo por operación")
    require_proof = models.BooleanField(default=False)
    require_txid = models.BooleanField(default=False)
    balance_rate = models.DecimalField(
        max_digits=18, decimal_places=8, default=Decimal("1.00000000"),
        help_text="Cuántas unidades de moneda base se acreditan por 1 unidad de la moneda de pago.",
    )
    sender_network_fee_estimate = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        default=Decimal("1.00000000"),
        help_text="Reserva estimada que la billetera del usuario puede cobrar por enviar. No se transfiere a HBL.",
    )
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=10)

    class Meta:
        ordering = ["sort_order", "label"]

    def __str__(self):
        return self.label

    def clean(self):
        for field in ("min_amount", "max_amount", "balance_rate", "sender_network_fee_estimate"):
            if getattr(self, field) < 0:
                raise ValidationError({field: "No puede ser negativo."})
        if self.balance_rate <= 0:
            raise ValidationError({"balance_rate": "La tasa de acreditación debe ser mayor que cero."})
        if self.max_amount and self.max_amount > 0 and self.max_amount < self.min_amount:
            raise ValidationError({"max_amount": "El máximo no puede ser menor que el mínimo."})


class Deposit(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"
        EXPIRED = "expired", "Expirada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_deposits")
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="deposits")
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Saldo HBL a acreditar expresado en la moneda base vigente.")
    currency = models.CharField(max_length=12, default="NIO")
    payment_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    payment_currency = models.CharField(max_length=12, default="NIO")
    balance_rate = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("1.00000000"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    txid = models.CharField(max_length=180, blank=True, db_index=True)
    reference = models.CharField(max_length=180, blank=True)
    proof = models.ImageField(upload_to="hbl/deposit_proofs/%Y/%m/", blank=True, null=True)
    merchant_trade_no = models.CharField(max_length=32, unique=True, blank=True, null=True)
    prepay_id = models.CharField(max_length=64, blank=True)
    checkout_url = models.URLField(max_length=600, blank=True)
    transaction_id = models.CharField(max_length=80, blank=True)
    provider = models.CharField(max_length=32, blank=True, db_index=True)
    provider_payment_id = models.CharField(max_length=80, blank=True, db_index=True)
    provider_status = models.CharField(max_length=32, blank=True)
    provider_price_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    provider_fee_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    sender_network_fee_estimate = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    provider_actual_paid = models.DecimalField(max_digits=18, decimal_places=8, blank=True, null=True)
    pay_address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [models.Index(fields=["status", "submitted_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["txid"],
                condition=~models.Q(txid=""),
                name="uniq_hbl_nonempty_txid",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=~models.Q(provider_payment_id=""),
                name="uniq_hbl_provider_payment_id",
            ),
        ]

    @property
    def wallet_balance_required(self):
        return (
            Decimal(self.payment_amount or 0) + Decimal(self.sender_network_fee_estimate or 0)
        ).quantize(Decimal("0.00000001"))


class PayoutAccount(models.Model):
    class Kind(models.TextChoices):
        BANK = "bank", "Cuenta bancaria"
        BINANCE_ID = "binance_id", "Binance Pay ID / Binance ID"
        USDT_TRC20 = "usdt_trc20", "USDT TRC20"
        USDT_BEP20 = "usdt_bep20", "USDT BEP20"
        CRYPTO_OTHER = "crypto_other", "Otra wallet"
        REMITTANCE = "remittance", "Giro / remesa"
        MOBILE_WALLET = "mobile_wallet", "Billetera móvil"
        CUSTOM = "custom", "Método administrable"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_payout_accounts")
    withdrawal_method = models.ForeignKey("WithdrawalMethod", on_delete=models.PROTECT, blank=True, null=True, related_name="payout_accounts")
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.CUSTOM)
    label = models.CharField(max_length=100)
    holder_name = models.CharField(max_length=140, blank=True)
    identifier = models.CharField(max_length=255)
    network = models.CharField(max_length=40, blank=True)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "label"]

    @property
    def masked_identifier(self):
        value = (self.identifier or "").strip()
        if len(value) <= 6:
            return "••••" + value[-2:] if value else "—"
        return f"{value[:3]}••••{value[-4:]}"


class Withdrawal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        PAID = "paid", "Pagado"
        REJECTED = "rejected", "Rechazado"
        CANCELED = "canceled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_withdrawals")
    payout_account = models.ForeignKey(PayoutAccount, on_delete=models.PROTECT, related_name="withdrawals")
    payout_kind = models.CharField(max_length=24, blank=True)
    payout_label = models.CharField(max_length=100, blank=True)
    payout_identifier = models.CharField(max_length=255, blank=True)
    payout_network = models.CharField(max_length=40, blank=True)
    # amount/fee/net_amount siempre se guardan en la moneda base del sistema para contabilidad.
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    fee = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=14, decimal_places=2)
    base_currency = models.CharField(max_length=12, default="NIO")
    requested_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    requested_currency = models.CharField(max_length=12, default="NIO")
    payout_amount = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal("0.00000000"))
    payout_currency = models.CharField(max_length=12, default="NIO")
    requested_rate_to_base = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("1.0000000000"))
    payout_rate_to_base = models.DecimalField(max_digits=24, decimal_places=10, default=Decimal("1.0000000000"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    admin_reference = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]


class AdminAuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="hbl_admin_actions")
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=100, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["action", "created_at"], name="hbl_audit_action_date")]

class ReferralTier(models.Model):
    name = models.CharField(max_length=80)
    min_active_referrals = models.PositiveIntegerField(unique=True)
    weekly_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["min_active_referrals"]

    def __str__(self):
        return f"{self.name} · {self.min_active_referrals}+ activos"


class ReferralEarning(models.Model):
    class Kind(models.TextChoices):
        FIRST_DEPOSIT = "first_deposit", "Primera recarga"
        DEPOSIT_COMMISSION = "deposit_commission", "Comisión primera recarga"
        MANUAL = "manual", "Manual"

    sponsor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_referral_earnings")
    referred = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_generated_referral_earnings")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ReferralPayroll(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PAID = "paid", "Pagado"
        CANCELED = "canceled", "Cancelado"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_referral_payrolls")
    week_start = models.DateField()
    active_referrals = models.PositiveIntegerField(default=0)
    tier = models.ForeignKey(ReferralTier, on_delete=models.SET_NULL, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-week_start", "-amount"]
        constraints = [
            models.UniqueConstraint(fields=["user", "week_start"], name="uniq_hbl_referral_payroll_week")
        ]


class ReferralUpgradeClaim(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_referral_upgrade_claims")
    from_plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="upgrade_claims_from")
    to_plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="upgrade_claims_to")
    qualified_referrals = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "to_plan"], name="uniq_hbl_referral_upgrade_user_toplan")
        ]



class WithdrawalMethod(models.Model):
    """Catálogo administrable de destinos de retiro."""

    class CurrencyMode(models.TextChoices):
        FIXED = "fixed", "Moneda fija del método"
        USER_LOCAL = "user_local", "Moneda local del usuario"

    class IdentifierType(models.TextChoices):
        BANK = "bank", "Cuenta bancaria / IBAN"
        BINANCE_ID = "binance_id", "Binance Pay ID"
        TRC20 = "trc20", "Wallet TRC20"
        BEP20 = "bep20", "Wallet BEP20 / EVM"
        EMAIL = "email", "Correo electrónico"
        PHONE = "phone", "Teléfono internacional"
        CUSTOM = "custom", "Texto libre"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    currency_mode = models.CharField(max_length=16, choices=CurrencyMode.choices, default=CurrencyMode.FIXED)
    currency = models.CharField(max_length=12, default="NIO")
    country = models.CharField(max_length=2, blank=True, default="", help_text="Vacío = disponible en todos los países.")
    network = models.CharField(max_length=40, blank=True)
    icon = models.CharField(max_length=16, blank=True, default="💸")
    instructions = models.TextField(blank=True)
    account_label = models.CharField(max_length=80, default="Cuenta / dirección")
    identifier_type = models.CharField(max_length=20, choices=IdentifierType.choices, default=IdentifierType.CUSTOM)
    identifier_placeholder = models.CharField(max_length=120, blank=True, default="")
    identifier_help = models.CharField(max_length=220, blank=True, default="")
    holder_required = models.BooleanField(default=True)
    min_amount_nio = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), help_text="0 = usar mínimo global")
    max_amount_nio = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), help_text="0 = sin máximo")
    fee_percent = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    fee_fixed_nio = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def payout_currency_for(self, user):
        if self.currency_mode == self.CurrencyMode.USER_LOCAL:
            return (getattr(user, "country_currency", "") or self.currency or PlatformConfig.get_solo().base_currency_code).upper()
        return (self.currency or PlatformConfig.get_solo().base_currency_code).upper()

    def clean(self):
        for field in ("min_amount_nio", "max_amount_nio", "fee_percent", "fee_fixed_nio"):
            if getattr(self, field) < 0:
                raise ValidationError({field: "No puede ser negativo."})
        if self.fee_percent > 100:
            raise ValidationError({"fee_percent": "No puede superar 100%."})
        if self.max_amount_nio and self.max_amount_nio < self.min_amount_nio:
            raise ValidationError({"max_amount_nio": "El máximo no puede ser menor que el mínimo."})


class WheelConfig(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=True)
    title = models.CharField(max_length=120, default="Ruleta HBL")
    subtitle = models.CharField(max_length=220, blank=True, default="Giro promocional gratuito")
    spins_per_day = models.PositiveSmallIntegerField(default=1)
    cooldown_minutes = models.PositiveIntegerField(default=0)
    require_active_membership = models.BooleanField(default=True)
    terms = models.TextField(blank=True, default="Participación promocional gratuita. No requiere apuesta ni pago por giro.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de ruleta"
        verbose_name_plural = "Configuración de ruleta"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WheelPrize(models.Model):
    class RewardType(models.TextChoices):
        BALANCE = "balance", "Saldo (moneda base)"
        MEMBERSHIP_DAYS = "membership_days", "Días extra de membresía"
        NONE = "none", "Sin premio"

    name = models.CharField(max_length=100)
    reward_type = models.CharField(max_length=24, choices=RewardType.choices, default=RewardType.BALANCE)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    weight = models.PositiveIntegerField(default=10, help_text="Peso relativo. Mayor peso = más frecuente.")
    icon = models.CharField(max_length=16, blank=True, default="🎁")
    color = models.CharField(max_length=7, default="#7C5CFC")
    daily_global_limit = models.PositiveIntegerField(default=0, help_text="0 = sin límite diario global")
    total_stock = models.PositiveIntegerField(default=0, help_text="0 = ilimitado")
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=10)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.weight < 1:
            raise ValidationError({"weight": "El peso debe ser al menos 1."})
        if self.value < 0:
            raise ValidationError({"value": "El valor no puede ser negativo."})
        if self.reward_type != self.RewardType.NONE and self.value <= 0:
            raise ValidationError({"value": "Un premio con recompensa necesita un valor mayor que cero."})


class WheelSpin(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_wheel_spins")
    prize = models.ForeignKey(WheelPrize, on_delete=models.PROTECT, related_name="spins")
    reward_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"], name="hbl_wheel_user_date")]


class GiftCode(models.Model):
    class RewardType(models.TextChoices):
        BALANCE = "balance", "Saldo (moneda base)"
        MEMBERSHIP_DAYS = "membership_days", "Días extra de membresía"

    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    reward_type = models.CharField(max_length=24, choices=RewardType.choices, default=RewardType.BALANCE)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    max_redemptions = models.PositiveIntegerField(default=1, help_text="Cantidad total de personas/usos permitidos. 0 = ilimitado")
    per_user_limit = models.PositiveSmallIntegerField(default=1)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)
    require_active_membership = models.BooleanField(default=False)
    required_plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, blank=True, null=True, related_name="gift_codes")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def used_count(self):
        return self.redemptions.count()

    def clean(self):
        self.code = (self.code or "").strip().upper()
        if self.value <= 0:
            raise ValidationError({"value": "El valor debe ser mayor que cero."})
        if self.per_user_limit < 1:
            raise ValidationError({"per_user_limit": "Cada usuario debe poder usarlo al menos una vez."})
        if self.max_redemptions and self.per_user_limit > self.max_redemptions:
            raise ValidationError({"per_user_limit": "El límite por usuario no puede superar el límite total."})
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValidationError({"valid_until": "La fecha final debe ser posterior a la inicial."})


class GiftRedemption(models.Model):
    gift = models.ForeignKey(GiftCode, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hbl_gift_redemptions")
    reward_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["gift", "user", "created_at"], name="hbl_gift_user_date")]
