from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from hbl_core.models import CurrencyRate, Deposit, PaymentMethod, PlatformConfig
from hbl_core.nowpayments import (
    NOWPAYMENTS_PROVIDER,
    NowPaymentsClient,
    apply_payment_status,
    create_payment_for_deposit,
    order_id_for,
)


User = get_user_model()


@override_settings(
    NOWPAYMENTS_API_KEY="test-api-key",
    NOWPAYMENTS_IPN_SECRET="test-ipn-secret",
    NOWPAYMENTS_IPN_CALLBACK_URL="https://example.test/api/pagos/nowpayments/ipn/",
    NOWPAYMENTS_FEE_PAID_BY_USER=False,
    NOWPAYMENTS_TEST_MODE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class NowPaymentsDepositTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="now-user", password="Testpass123!")
        self.client.force_login(self.user)
        config = PlatformConfig.get_solo()
        config.minimum_deposit_usd = Decimal("1.00")
        config.save(update_fields=["minimum_deposit_usd"])
        CurrencyRate.objects.update_or_create(
            code="USD",
            defaults={"name": "US Dollar", "symbol": "$", "rate_to_base": Decimal("36.6200"), "active": True},
        )
        CurrencyRate.objects.update_or_create(
            code="USDT",
            defaults={"name": "Tether", "symbol": "USDT", "rate_to_base": Decimal("36.6200"), "active": True},
        )
        self.trc20 = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.USDT_TRC20,
            label="USDT TRC20",
            currency="USDT",
            network="TRON (TRC20)",
            min_amount=Decimal("1.00"),
            balance_rate=Decimal("36.62"),
            require_txid=False,
            sender_network_fee_estimate=Decimal("0"),
            active=True,
        )
        self.bank = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.BANK,
            label="Banco manual",
            currency="NIO",
            min_amount=Decimal("1.00"),
            active=True,
        )

    def _remote_created(self, payment_id="700001"):
        return {
            "payment_id": payment_id,
            "payment_status": "waiting",
            "pay_address": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
            "pay_amount": Decimal("101.00000000"),
            "pay_currency": "usdttrc20",
            "price_amount": Decimal("101.00000000"),
            "fee_amount": Decimal("1.00000000"),
        }

    def _deposit(self, payment_id="700002"):
        return Deposit.objects.create(
            user=self.user,
            payment_method=self.trc20,
            amount=Decimal("3662.00"),
            currency="NIO",
            payment_amount=Decimal("101.00000000"),
            payment_currency="USDT",
            balance_rate=Decimal("36.62"),
            status=Deposit.Status.PROCESSING,
            provider=NOWPAYMENTS_PROVIDER,
            provider_payment_id=payment_id,
            provider_status="waiting",
            provider_price_amount=Decimal("100.00000000"),
            provider_fee_amount=Decimal("1.00000000"),
            sender_network_fee_estimate=Decimal("0"),
            pay_address="TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
        )

    def _provider_status(self, deposit, status, *, legacy=False):
        price = "100.00000000" if legacy else "101.00000000"
        return {
            "payment_id": deposit.provider_payment_id,
            "payment_status": status,
            "order_id": order_id_for(deposit.id),
            "price_amount": price,
            "price_currency": "usd",
            "pay_amount": price,
            "pay_currency": "usdttrc20",
            "actually_paid": price,
        }

    @patch.object(NowPaymentsClient, "_request")
    def test_create_payment_can_disable_provider_fee_passthrough(self, request):
        request.return_value = {}
        client = NowPaymentsClient(api_key="test-key")

        client.create_payment(
            price_amount=Decimal("11.00"),
            pay_currency="usdtbsc",
            order_id="hbl-deposit:test",
            callback_url="https://example.test/ipn/",
            fee_paid_by_user=False,
        )

        payload = request.call_args.args[2]
        self.assertFalse(payload["is_fee_paid_by_user"])
        self.assertEqual(payload["price_amount"], "11.00")

    def test_provider_order_adds_exactly_one_usdt_to_requested_credit(self):
        deposit = self._deposit()
        client = MagicMock()
        client.create_payment.return_value = {
            "payment_id": "700010",
            "payment_status": "waiting",
            "pay_address": "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
            "pay_amount": "101.00000000",
            "pay_currency": "usdttrc20",
            "price_amount": "101.00000000",
        }

        remote = create_payment_for_deposit(deposit, "https://example.test/ipn/", client=client)

        kwargs = client.create_payment.call_args.kwargs
        self.assertEqual(kwargs["price_amount"], Decimal("101.00000000"))
        self.assertFalse(kwargs["fee_paid_by_user"])
        self.assertEqual(remote["pay_amount"], Decimal("101.00000000"))
        self.assertEqual(remote["fee_amount"], Decimal("1.00000000"))

    @patch("hbl_core.payment_views.create_payment_for_deposit")
    def test_wallet_creates_nowpayments_order_without_txid_or_proof(self, create_payment):
        create_payment.return_value = self._remote_created()
        response = self.client.post(reverse("hbl_wallet"), {
            "payment_method": self.trc20.id,
            "payment_amount": "100.00",
        })
        self.assertEqual(response.status_code, 302)
        deposit = Deposit.objects.get(user=self.user)
        self.assertEqual(deposit.status, Deposit.Status.PROCESSING)
        self.assertEqual(deposit.provider, NOWPAYMENTS_PROVIDER)
        self.assertEqual(deposit.provider_payment_id, "700001")
        self.assertEqual(deposit.txid, "")
        self.assertEqual(deposit.payment_amount, Decimal("101.00000000"))
        self.assertEqual(deposit.provider_price_amount, Decimal("100.00000000"))
        self.assertEqual(deposit.provider_fee_amount, Decimal("1.00000000"))
        self.assertEqual(deposit.sender_network_fee_estimate, Decimal("0E-8"))
        self.assertEqual(deposit.wallet_balance_required, Decimal("101.00000000"))
        self.user.refresh_from_db()
        self.assertEqual(Decimal(self.user.saldo), Decimal("0.00"))

        response = self.client.get(reverse("hbl_wallet"))
        self.assertContains(response, "Total exacto a enviar: 101.00000000 USDT")
        self.assertContains(response, "Cargo fijo HBL")
        self.assertNotContains(response, "Revisión manual requerida")
        self.assertNotContains(response, "partially_paid")

    def test_only_trc20_and_bep20_are_visible_and_accepted(self):
        response = self.client.get(reverse("hbl_wallet"))
        self.assertContains(response, self.trc20.label)
        self.assertNotContains(response, self.bank.label)
        response = self.client.post(reverse("hbl_wallet"), {
            "payment_method": self.bank.id,
            "payment_amount": "100.00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Deposit.objects.filter(payment_method=self.bank).exists())

    @override_settings(NOWPAYMENTS_TEST_MODE=True, NOWPAYMENTS_TEST_MIN_USDT=Decimal("1"))
    @patch("hbl_core.payment_views.create_payment_for_deposit")
    def test_test_mode_allows_one_usdt_credit_and_two_usdt_total(self, create_payment):
        self.trc20.min_amount = Decimal("100.00")
        self.trc20.save(update_fields=["min_amount"])
        config = PlatformConfig.get_solo()
        config.minimum_deposit_usd = Decimal("100.00")
        config.save(update_fields=["minimum_deposit_usd"])
        remote = self._remote_created("700099")
        remote["pay_amount"] = Decimal("2.00000000")
        remote["price_amount"] = Decimal("2.00000000")
        remote["fee_amount"] = Decimal("1.00000000")
        create_payment.return_value = remote

        response = self.client.post(reverse("hbl_wallet"), {
            "payment_method": self.trc20.id,
            "payment_amount": "1.00",
        })
        self.assertEqual(response.status_code, 302)
        deposit = Deposit.objects.get(provider_payment_id="700099")
        self.assertEqual(deposit.provider_price_amount, Decimal("1.00000000"))
        self.assertEqual(deposit.payment_amount, Decimal("2.00000000"))
        self.assertEqual(deposit.provider_fee_amount, Decimal("1.00000000"))

    def test_confirmed_does_not_credit_until_finished(self):
        deposit = self._deposit()
        checked, changed = apply_payment_status(deposit.id, self._provider_status(deposit, "confirmed"))
        self.assertFalse(changed)
        self.assertEqual(checked.status, Deposit.Status.PROCESSING)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("0.00"))

    def test_finished_credits_exactly_once(self):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "finished")
        first, first_changed = apply_payment_status(deposit.id, payload)
        second, second_changed = apply_payment_status(deposit.id, payload)
        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(first.status, Deposit.Status.APPROVED)
        self.assertEqual(second.status, Deposit.Status.APPROVED)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("3662.00"))

    def test_legacy_order_created_before_fixed_fee_can_still_finish(self):
        deposit = self._deposit("700050")
        payload = self._provider_status(deposit, "finished", legacy=True)
        checked, changed = apply_payment_status(deposit.id, payload)
        self.assertTrue(changed)
        self.assertEqual(checked.status, Deposit.Status.APPROVED)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("3662.00"))

    def test_partial_payment_stays_active_until_user_completes_it(self):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "partially_paid")
        payload["actually_paid"] = "99.50000000"
        checked, changed = apply_payment_status(deposit.id, payload)
        self.assertFalse(changed)
        self.assertEqual(checked.status, Deposit.Status.PROCESSING)
        self.assertEqual(checked.provider_actual_paid, Decimal("99.50000000"))
        self.assertIn("sigue activa", checked.notes)
        self.assertNotIn("Revisión manual", checked.notes)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("0.00"))

        response = self.client.get(reverse("hbl_wallet"))
        self.assertContains(response, "Pago parcial recibido")
        self.assertContains(response, "1.50000000 USDT")
        self.assertNotContains(response, "partially_paid")

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.get(reverse("hbl_control_deposits"))
        self.assertContains(response, "99.50000000 USDT")
        self.assertContains(response, "Pago parcial")
        self.assertContains(response, "Actualizar")

    @patch("hbl_core.nowpayments.NowPaymentsClient.get_payment")
    def test_staff_can_refresh_partial_amount_from_control(self, get_payment):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "partially_paid")
        payload["actually_paid"] = "98.75000000"
        get_payment.return_value = payload
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.post(
            reverse("hbl_control_deposit_action", args=[deposit.id, "refresh"]),
        )

        self.assertRedirects(response, reverse("hbl_control_deposits"))
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, Deposit.Status.PROCESSING)
        self.assertEqual(deposit.provider_actual_paid, Decimal("98.75000000"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("0.00"))

    def test_mismatched_order_never_credits(self):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "finished")
        payload["order_id"] = "hbl-deposit:otra"
        checked, changed = apply_payment_status(deposit.id, payload)
        self.assertFalse(changed)
        self.assertEqual(checked.status, Deposit.Status.PENDING)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("0.00"))

    def test_ipn_rejects_invalid_signature(self):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "finished")
        response = self.client.post(
            reverse("hbl_nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG="invalid",
        )
        self.assertEqual(response.status_code, 401)
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, Deposit.Status.PROCESSING)

    @patch("hbl_core.nowpayments.urlopen")
    def test_api_request_identifies_hbl_client(self, mocked_urlopen):
        response = MagicMock()
        response.read.return_value = b'{"status":"OK"}'
        mocked_urlopen.return_value.__enter__.return_value = response
        client = NowPaymentsClient(api_key="test-key")
        client._request("GET", "status")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"),
            "HBL-Payments/1.0 (+https://hbl-e8cw.onrender.com)",
        )

    @patch("hbl_core.nowpayments.NowPaymentsClient.get_payment")
    def test_valid_ipn_reconfirms_with_api_and_credits(self, get_payment):
        deposit = self._deposit()
        payload = self._provider_status(deposit, "finished")
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        signature = hmac.new(b"test-ipn-secret", canonical.encode(), hashlib.sha512).hexdigest()
        get_payment.return_value = payload
        response = self.client.post(
            reverse("hbl_nowpayments_ipn"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["credited"])
        get_payment.assert_called_once_with(deposit.provider_payment_id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("3662.00"))

    @override_settings(NOWPAYMENTS_API_KEY="key", NOWPAYMENTS_IPN_SECRET="secret")
    def test_deploy_seed_leaves_exactly_two_crypto_networks_active(self):
        call_command("seed_payment_gateways", verbosity=0)
        active_kinds = set(PaymentMethod.objects.filter(active=True).values_list("kind", flat=True))
        self.assertEqual(active_kinds, {
            PaymentMethod.Kind.USDT_TRC20,
            PaymentMethod.Kind.USDT_BEP20,
        })
        for method in PaymentMethod.objects.filter(active=True):
            self.assertEqual(method.sender_network_fee_estimate, Decimal("0E-8"))
