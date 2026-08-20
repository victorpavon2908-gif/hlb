import base64
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from hbl_core.models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig


User = get_user_model()


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


class ManualDepositTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="manual-user", password="Testpass123!")
        self.client.force_login(self.user)

        config = PlatformConfig.get_solo()
        config.minimum_deposit_usd = Decimal("1.00")
        config.save(update_fields=["minimum_deposit_usd"])

        CurrencyRate.objects.update_or_create(
            code="USD",
            defaults={
                "name": "US Dollar",
                "symbol": "$",
                "rate_to_base": Decimal("36.6200"),
                "active": True,
            },
        )

        self.bank = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.BANK,
            label="Transferencia bancaria manual",
            currency="NIO",
            destination="Cuenta de prueba",
            min_amount=Decimal("1.00"),
            balance_rate=Decimal("1.00"),
            require_proof=True,
            active=True,
        )

    def _proof(self):
        return SimpleUploadedFile("comprobante.png", PNG_1X1, content_type="image/png")

    def test_manual_deposit_stays_pending_and_does_not_credit_balance(self):
        response = self.client.post(
            reverse("hbl_wallet"),
            {
                "payment_method": self.bank.id,
                "payment_amount": "100.00",
                "reference": "REF-12345",
                "proof": self._proof(),
            },
        )

        self.assertEqual(response.status_code, 302)
        deposit = Deposit.objects.get(user=self.user)
        self.assertEqual(deposit.status, Deposit.Status.PENDING)
        self.assertTrue(bool(deposit.proof))

        self.user.refresh_from_db()
        self.assertEqual(Decimal(self.user.saldo), Decimal("0.00"))

    def test_proof_is_mandatory(self):
        response = self.client.post(
            reverse("hbl_wallet"),
            {
                "payment_method": self.bank.id,
                "payment_amount": "100.00",
                "reference": "REF-54321",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Deposit.objects.filter(user=self.user).exists())
        self.assertContains(response, "Debes subir un comprobante")

    def test_paypal_and_tilopay_are_not_available(self):
        paypal = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.MOBILE_WALLET,
            label="PayPal",
            currency="USD",
            network="PAYPAL",
            min_amount=Decimal("1.00"),
            balance_rate=Decimal("36.62"),
            active=True,
        )
        tilopay = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.MOBILE_WALLET,
            label="Tilopay",
            currency="USD",
            network="TILOPAY",
            min_amount=Decimal("1.00"),
            balance_rate=Decimal("36.62"),
            active=True,
        )

        response = self.client.get(reverse("hbl_wallet"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, paypal.label)
        self.assertNotContains(response, tilopay.label)

        response = self.client.post(
            reverse("hbl_wallet"),
            {
                "payment_method": paypal.id,
                "payment_amount": "10.00",
                "proof": self._proof(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Deposit.objects.filter(payment_method=paypal).exists())
