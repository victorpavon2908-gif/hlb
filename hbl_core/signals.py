import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .crypto_payments import verify_and_credit_deposit
from .models import Deposit, PaymentMethod

logger = logging.getLogger(__name__)

AUTO_KINDS = {
    PaymentMethod.Kind.USDT_TRC20,
    PaymentMethod.Kind.USDT_BEP20,
}


def _verify_safely(deposit_id):
    try:
        verify_and_credit_deposit(deposit_id)
    except Exception:
        logger.exception("No se pudo completar la validación automática del depósito %s", deposit_id)


@receiver(post_save, sender=Deposit, dispatch_uid="hbl_auto_verify_crypto_deposit")
def auto_verify_crypto_deposit(sender, instance, created, **kwargs):
    """Al registrar un TXID nuevo, validarlo después del commit de la fila."""
    if not created or not instance.txid or not instance.payment_method_id:
        return

    kind = (
        PaymentMethod.objects.filter(pk=instance.payment_method_id)
        .values_list("kind", flat=True)
        .first()
    )
    if kind not in AUTO_KINDS:
        return

    transaction.on_commit(lambda: _verify_safely(instance.pk))
