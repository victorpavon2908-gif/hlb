import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .crypto_payments import verify_and_credit_deposit
from .models import Deposit, PaymentMethod, PlatformConfig
from .payment_policies import CRYPTO_DEPOSIT_KINDS, GLOBAL_MIN_DEPOSIT_USDT

logger = logging.getLogger(__name__)

# Compatibilidad con código/entornos antiguos que todavía consultan esta
# variable: incluso en modo de prueba el mínimo global sigue siendo 10 USDT.
settings.NOWPAYMENTS_TEST_MIN_USDT = GLOBAL_MIN_DEPOSIT_USDT

AUTO_KINDS = {
    PaymentMethod.Kind.USDT_TRC20,
    PaymentMethod.Kind.USDT_BEP20,
}


def _verify_safely(deposit_id):
    try:
        verify_and_credit_deposit(deposit_id)
    except Exception:
        logger.exception("No se pudo completar la validación automática del depósito %s", deposit_id)


@receiver(pre_save, sender=PlatformConfig, dispatch_uid="hbl_lock_global_deposit_minimum")
def lock_global_deposit_minimum(sender, instance, **kwargs):
    """El mínimo de recarga de HBL es fijo para todos: 10 USDT."""
    instance.minimum_deposit_usd = GLOBAL_MIN_DEPOSIT_USDT


@receiver(pre_save, sender=PaymentMethod, dispatch_uid="hbl_lock_crypto_method_minimum")
def lock_crypto_method_minimum(sender, instance, **kwargs):
    """Evita que un método individual contradiga el mínimo global de 10 USDT."""
    if instance.kind in CRYPTO_DEPOSIT_KINDS:
        instance.min_amount = GLOBAL_MIN_DEPOSIT_USDT


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
