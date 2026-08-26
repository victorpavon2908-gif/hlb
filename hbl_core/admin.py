from django.contrib import admin, messages

from .control_forms import PaymentMethodForm, WithdrawalMethodForm
from .models import (
    AdminAuditLog,
    CurrencyRate,
    DailyAssignment,
    Deposit,
    Membership,
    MembershipPlan,
    ListeningSession,
    PaymentMethod,
    PlatformConfig,
    PayoutAccount,
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
from .services import HBLError, approve_deposit, mark_withdrawal_paid, reject_deposit, reject_withdrawal
from .payment_policies import CRYPTO_DEPOSIT_KINDS, CRYPTO_WITHDRAWAL_SLUGS


@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not PlatformConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False




@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "symbol", "rate_to_base", "active", "updated_at")
    list_editable = ("rate_to_base", "active")
    search_fields = ("code", "name")
    list_filter = ("active",)

@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price_usd", "daily_reward_nio", "daily_tracks", "duration_days", "active", "featured")
    list_filter = ("active", "featured")
    list_editable = ("active", "featured")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "starts_at", "ends_at", "daily_reward_snapshot", "daily_tracks_snapshot")
    list_filter = ("status", "plan")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at",)


@admin.register(DailyAssignment)
class DailyAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "assignment_date", "position", "track", "reward_amount", "completed_at")
    list_filter = ("assignment_date", "track")
    search_fields = ("user__username", "track__title")
    readonly_fields = ("created_at",)


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "reward_amount", "min_listen_seconds", "daily_user_limit", "active", "featured")
    list_filter = ("active", "featured")
    search_fields = ("title", "artist")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("allowed_plans",)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    form = PaymentMethodForm
    list_display = ("label", "kind", "currency", "network", "min_amount", "max_amount", "balance_rate", "active", "sort_order")
    list_filter = ("kind", "active")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(kind__in=CRYPTO_DEPOSIT_KINDS)


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "payment_method", "provider_status", "amount", "currency", "status", "submitted_at")
    list_filter = ("status", "payment_method__kind")
    search_fields = ("user__username", "user__email", "txid", "provider_payment_id", "merchant_trade_no", "transaction_id")
    readonly_fields = (
        "id", "user", "payment_method", "amount", "currency", "payment_amount",
        "payment_currency", "balance_rate", "status", "txid", "reference", "proof",
        "submitted_at", "processed_at", "merchant_trade_no", "prepay_id",
        "checkout_url", "transaction_id", "provider", "provider_payment_id",
        "provider_status", "provider_price_amount", "provider_actual_paid", "pay_address",
    )
    actions = ("approve_selected", "reject_selected")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Aprobar recargas seleccionadas (atómico)")
    def approve_selected(self, request, queryset):
        ok = 0
        for obj in queryset:
            try:
                _, changed = approve_deposit(obj.pk, notes=f"Aprobado por admin {request.user.pk}")
                ok += int(changed)
            except HBLError as exc:
                self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
        self.message_user(request, f"{ok} recarga(s) aprobada(s).")

    @admin.action(description="Rechazar recargas seleccionadas")
    def reject_selected(self, request, queryset):
        ok = 0
        for obj in queryset:
            try:
                _, changed = reject_deposit(obj.pk, notes=f"Rechazado por admin {request.user.pk}")
                ok += int(changed)
            except HBLError as exc:
                self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
        self.message_user(request, f"{ok} recarga(s) rechazada(s).")


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "fee", "net_amount", "status", "created_at")
    list_filter = ("status", "payout_account__kind")
    search_fields = ("user__username", "user__email", "admin_reference", "payout_account__identifier")
    readonly_fields = (
        "id", "user", "payout_account", "payout_kind", "payout_label",
        "payout_identifier", "payout_network", "amount", "fee", "net_amount",
        "status", "created_at", "processed_at",
    )
    actions = ("mark_paid_selected", "reject_selected")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Marcar retiros como pagados")
    def mark_paid_selected(self, request, queryset):
        ok = 0
        for obj in queryset:
            try:
                _, changed = mark_withdrawal_paid(obj.pk, admin_reference=f"admin:{request.user.pk}")
                ok += int(changed)
            except HBLError as exc:
                self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
        self.message_user(request, f"{ok} retiro(s) marcado(s) pagado(s).")

    @admin.action(description="Rechazar y reembolsar retiros seleccionados")
    def reject_selected(self, request, queryset):
        ok = 0
        for obj in queryset:
            try:
                _, changed = reject_withdrawal(obj.pk, notes=f"Rechazado por admin {request.user.pk}")
                ok += int(changed)
            except HBLError as exc:
                self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
        self.message_user(request, f"{ok} retiro(s) rechazado(s) y reembolsado(s).")


@admin.register(ReferralTier)
class ReferralTierAdmin(admin.ModelAdmin):
    list_display = ("name", "min_active_referrals", "weekly_salary", "active")
    list_editable = ("weekly_salary", "active")


@admin.register(PayoutAccount)
class PayoutAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "withdrawal_method", "identifier", "network", "is_default", "active")
    search_fields = ("user__username", "user__email", "identifier", "label")
    list_filter = ("kind", "active")


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(ReferralEarning)
class ReferralEarningAdmin(ReadOnlyAdmin):
    list_display = ("sponsor", "referred", "kind", "amount", "created_at")
    search_fields = ("sponsor__username", "referred__username", "reference")


@admin.register(ReferralPayroll)
class ReferralPayrollAdmin(ReadOnlyAdmin):
    list_display = ("user", "week_start", "active_referrals", "tier", "amount", "status")
    list_filter = ("status", "week_start")


@admin.register(RewardLedger)
class RewardLedgerAdmin(ReadOnlyAdmin):
    list_display = ("user", "kind", "amount", "balance_after", "reference", "created_at")
    list_filter = ("kind",)
    search_fields = ("user__username", "user__email", "reference")


@admin.register(ListeningSession)
class ListeningSessionAdmin(ReadOnlyAdmin):
    list_display = ("user", "track", "status", "verified_seconds", "reward_amount", "started_at")
    list_filter = ("status", "track")
    search_fields = ("user__username", "track__title")
@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("actor__username", "action", "target_id")


admin.site.site_header = "HBL · Administración"
admin.site.site_title = "HBL Admin"
admin.site.index_title = "Operación de música, recompensas y pagos"


@admin.register(WithdrawalMethod)
class WithdrawalMethodAdmin(admin.ModelAdmin):
    form = WithdrawalMethodForm
    list_display = ("name", "currency", "network", "min_amount_nio", "max_amount_nio", "fee_percent", "fee_fixed_nio", "active", "sort_order")
    list_editable = ("active", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "network")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(slug__in=CRYPTO_WITHDRAWAL_SLUGS)


@admin.register(WheelConfig)
class WheelConfigAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not WheelConfig.objects.exists()
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WheelPrize)
class WheelPrizeAdmin(admin.ModelAdmin):
    list_display = ("name", "reward_type", "value", "weight", "daily_global_limit", "total_stock", "active", "sort_order")
    list_editable = ("active", "sort_order")
    list_filter = ("reward_type", "active")


@admin.register(GiftCode)
class GiftCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "reward_type", "value", "max_redemptions", "used_count", "active", "valid_until")
    list_filter = ("reward_type", "active")
    search_fields = ("code", "name")
    readonly_fields = ("used_count", "created_at")


@admin.register(WheelSpin)
class WheelSpinAdmin(ReadOnlyAdmin):
    list_display = ("user", "prize", "reward_amount", "created_at")
    search_fields = ("user__username", "user__email", "user__telefono", "prize__name")


@admin.register(GiftRedemption)
class GiftRedemptionAdmin(ReadOnlyAdmin):
    list_display = ("gift", "user", "reward_amount", "created_at")
    search_fields = ("gift__code", "user__username", "user__email", "user__telefono")
