from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from hbl_core.models import Deposit, PaymentMethod, RewardLedger
from hbl_core.services import approve_deposit


User = get_user_model()


class DepositIdempotencyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="payment-test-user", password="test-pass-123")
        self.method = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.MOBILE_WALLET,
            label="Gateway test",
            currency="USD",
            network="TEST",
            min_amount=Decimal("1"),
            balance_rate=Decimal("1"),
            active=True,
        )
        self.deposit = Deposit.objects.create(
            user=self.user,
            payment_method=self.method,
            amount=Decimal("100.00"),
            currency="NIO",
            payment_amount=Decimal("100.00"),
            payment_currency="USD",
            balance_rate=Decimal("1"),
            status=Deposit.Status.PROCESSING,
        )

    def test_approve_deposit_twice_credits_only_once(self):
        _, first_changed = approve_deposit(self.deposit.id, transaction_id="TX-ONE")
        _, second_changed = approve_deposit(self.deposit.id, transaction_id="TX-ONE")

        self.user.refresh_from_db()
        self.deposit.refresh_from_db()

        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(self.user.saldo, Decimal("100.00"))
        self.assertEqual(self.deposit.status, Deposit.Status.APPROVED)
        self.assertEqual(
            RewardLedger.objects.filter(user=self.user, kind=RewardLedger.Kind.DEPOSIT).count(),
            1,
        )
