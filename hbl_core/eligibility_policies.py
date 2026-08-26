from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Deposit, Membership, ReferralEarning, RewardLedger

User = get_user_model()
_INSTALLED = False


def _has_active_plan(user_id):
    if not user_id:
        return False
    now = timezone.now()
    return Membership.objects.filter(
        user_id=user_id,
        status=Membership.Status.ACTIVE,
        starts_at__lte=now,
        ends_at__gt=now,
    ).exists()


def install_eligibility_policies():
    """Aplica las reglas comerciales de elegibilidad de HBL.

    - Para recibir comisión/sueldo por referidos se requiere un plan activo.
    - Para solicitar un retiro se requiere un plan activo.

    Se instala en AppConfig.ready() para que cualquier vista o comando que
    importe estas funciones desde services reciba la versión protegida.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from . import services

    original_approve_deposit = services.approve_deposit
    original_request_withdrawal = services.request_withdrawal
    original_create_referral_payroll = services.create_referral_payroll

    @transaction.atomic
    def approve_deposit_with_active_plan(deposit_id, *, transaction_id="", notes=""):
        deposit_before = Deposit.objects.select_related("user").get(pk=deposit_id)
        sponsor_id = getattr(deposit_before.user, "referido_por_id", None)
        sponsor_had_active_plan = _has_active_plan(sponsor_id)

        deposit, changed = original_approve_deposit(
            deposit_id,
            transaction_id=transaction_id,
            notes=notes,
        )

        # La lógica heredada acredita la comisión al aprobar la primera recarga.
        # Si el patrocinador no tenía un plan activo en ese momento, deshacemos
        # esa acreditación dentro de la misma transacción y eliminamos el earning.
        if changed and sponsor_id and not sponsor_had_active_plan:
            reference = f"first-deposit-commission:{deposit.user_id}"
            ledger = (
                RewardLedger.objects.select_for_update()
                .filter(
                    user_id=sponsor_id,
                    kind=RewardLedger.Kind.REFERRAL,
                    reference=reference,
                )
                .first()
            )
            if ledger:
                sponsor = User.objects.select_for_update().get(pk=sponsor_id)
                amount = Decimal(ledger.amount or 0)
                sponsor.saldo = services.money(Decimal(sponsor.saldo or 0) - amount)
                sponsor.save(update_fields=["saldo"])
                ledger.delete()

            ReferralEarning.objects.filter(
                sponsor_id=sponsor_id,
                reference=reference,
            ).delete()

        return deposit, changed

    @transaction.atomic
    def request_withdrawal_with_active_plan(user_id, payout_account, requested_amount, requested_currency=None):
        if not _has_active_plan(user_id):
            raise services.HBLError(
                "Necesitas tener un plan activo para solicitar retiros. Activa o renueva un plan y vuelve a intentarlo."
            )
        return original_request_withdrawal(
            user_id,
            payout_account,
            requested_amount,
            requested_currency=requested_currency,
        )

    @transaction.atomic
    def create_referral_payroll_with_active_plan(user, week_start=None, pay=False):
        if pay and not _has_active_plan(user.id):
            raise services.HBLError(
                "Necesitas tener un plan activo para recibir recompensas de referidos."
            )
        return original_create_referral_payroll(user, week_start=week_start, pay=pay)

    services.approve_deposit = approve_deposit_with_active_plan
    services.request_withdrawal = request_withdrawal_with_active_plan
    services.create_referral_payroll = create_referral_payroll_with_active_plan
    _INSTALLED = True
