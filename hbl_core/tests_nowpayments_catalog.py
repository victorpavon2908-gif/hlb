from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig
from .nowpayments import NOWPAYMENTS_PROVIDER, create_payment_for_deposit
from .nowpayments_catalog import describe_provider_code, sync_nowpayments_methods

User = get_user_model()


@override_settings(
    DEBUG=True,
    NOWPAYMENTS_API_KEY="test-key",
    NOWPAYMENTS_IPN_SECRET="test-secret",
    NOWPAYMENTS_TEST_MODE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class NowPaymentsCatalogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="catalog-user", password="StrongPass123!")
        config = PlatformConfig.get_solo()
        config.minimum_deposit_usd = Decimal("1.00")
        config.exchange_rate_usd_nio = Decimal("36.6200")
        config.save(update_fields=["minimum_deposit_usd", "exchange_rate_usd_nio"])
        CurrencyRate.objects.update_or_create(
            code="USDT",
            defaults={"name": "Tether", "symbol": "USDT", "rate_to_base": Decimal("36.62"), "active": True},
        )

    def test_describe_common_network_codes(self):
        trc = describe_provider_code("usdttrc20")
        self.assertEqual(trc["symbol"], "USDT")
        self.assertEqual(trc["network"], "TRON (TRC20)")
        self.assertEqual(trc["icon"], "₮")
        arb = describe_provider_code("etharb")
        self.assertEqual(arb["symbol"], "ETH")
        self.assertEqual(arb["network"], "Arbitrum")

    def test_sync_creates_every_provider_currency(self):
        client = MagicMock()
        client.get_merchant_currencies.return_value = {
            "selectedCurrencies": ["btc", "eth", "usdttrc20", "usdtbsc"]
        }
        count = sync_nowpayments_methods(force=True, client=client)
        self.assertEqual(count, 4)
        self.assertTrue(PaymentMethod.objects.filter(destination="btc", kind=PaymentMethod.Kind.CRYPTO_OTHER, active=True).exists())
        self.assertTrue(PaymentMethod.objects.filter(destination="eth", kind=PaymentMethod.Kind.CRYPTO_OTHER, active=True).exists())
        self.assertTrue(PaymentMethod.objects.filter(destination="usdttrc20", active=True).exists())
        self.assertTrue(PaymentMethod.objects.filter(destination="usdtbsc", active=True).exists())

    def test_non_usdt_payment_uses_provider_crypto_quote(self):
        method = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.CRYPTO_OTHER,
            label="Bitcoin",
            currency="BTC",
            network="Red principal",
            destination="btc",
            min_amount=Decimal("1"),
            balance_rate=Decimal("36.62"),
            active=True,
        )
        deposit = Deposit(
            user=self.user,
            payment_method=method,
            amount=Decimal("366.20"),
            currency="NIO",
            payment_amount=Decimal("10"),
            payment_currency="BTC",
            provider=NOWPAYMENTS_PROVIDER,
            provider_price_amount=Decimal("10"),
        )
        client = MagicMock()
        client.create_payment.return_value = {
            "payment_id": "800001",
            "payment_status": "waiting",
            "pay_address": "bc1qexample",
            "price_amount": "11.00000000",
            "pay_amount": "0.00025000",
            "pay_currency": "btc",
            "expiration_estimate_date": "2026-08-26T16:00:00Z",
        }
        remote = create_payment_for_deposit(deposit, "https://example.test/ipn/", client=client)
        kwargs = client.create_payment.call_args.kwargs
        self.assertEqual(kwargs["price_amount"], Decimal("11.00000000"))
        self.assertIsNone(kwargs["pay_amount"])
        self.assertEqual(remote["pay_amount"], Decimal("0.00025000"))
        self.assertEqual(remote["fee_amount"], Decimal("1.00000000"))

    def test_usdt_still_forces_exact_total(self):
        method = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.USDT_TRC20,
            label="Tether TRC20",
            currency="USDT",
            network="TRON (TRC20)",
            destination="usdttrc20",
            min_amount=Decimal("1"),
            balance_rate=Decimal("36.62"),
            active=True,
        )
        deposit = Deposit(
            user=self.user,
            payment_method=method,
            amount=Decimal("366.20"),
            currency="NIO",
            payment_amount=Decimal("10"),
            payment_currency="USDT",
            provider=NOWPAYMENTS_PROVIDER,
            provider_price_amount=Decimal("10"),
        )
        client = MagicMock()
        client.create_payment.return_value = {
            "payment_id": "800002",
            "payment_status": "waiting",
            "pay_address": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
            "price_amount": "11.00000000",
            "pay_amount": "11.00000000",
            "pay_currency": "usdttrc20",
        }
        create_payment_for_deposit(deposit, "https://example.test/ipn/", client=client)
        self.assertEqual(client.create_payment.call_args.kwargs["pay_amount"], Decimal("11.00000000"))

    def test_wallet_renders_saved_provider_expiry_timer(self):
        method = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.USDT_TRC20,
            label="Tether TRC20",
            currency="USDT",
            network="TRON (TRC20)",
            destination="usdttrc20",
            min_amount=Decimal("1"),
            balance_rate=Decimal("36.62"),
            active=True,
        )
        Deposit.objects.create(
            user=self.user,
            payment_method=method,
            amount=Decimal("366.20"),
            currency="NIO",
            payment_amount=Decimal("11"),
            payment_currency="USDT",
            balance_rate=Decimal("36.62"),
            status=Deposit.Status.PROCESSING,
            provider=NOWPAYMENTS_PROVIDER,
            provider_payment_id="800003",
            provider_status="waiting",
            provider_price_amount=Decimal("10"),
            provider_fee_amount=Decimal("1"),
            pay_address="TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
            prepay_id="2026-08-26T16:00:00Z",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("hbl_wallet"))
        self.assertContains(response, "data-order-timer")
        self.assertContains(response, "Tiempo restante de la orden")
        self.assertContains(response, "Buscar BTC, ETH, USDT")
