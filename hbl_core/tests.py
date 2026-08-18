from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .forms import DepositForm, RegistrationForm
from .models import (
    CurrencyRate,
    Deposit,
    GiftCode,
    ListeningSession,
    MembershipPlan,
    PaymentMethod,
    PayoutAccount,
    PlatformConfig,
    Track,
    WheelConfig,
    WheelPrize,
    WheelSpin,
    WithdrawalMethod,
)
from .services import (
    HBLError,
    approve_deposit,
    complete_listening,
    ensure_daily_assignments,
    eligible_referral_upgrade,
    display_money,
    purchase_plan,
    redeem_gift_code,
    request_withdrawal,
    spin_wheel,
    start_listening,
)

User = get_user_model()


class HBLCoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="listener", email="listener@example.com", country="NI", password="StrongPass123!"
        )
        self.user.saldo = Decimal("5000.00")
        self.user.save(update_fields=["saldo"])
        cfg = PlatformConfig.get_solo()
        cfg.exchange_rate_usd_nio = Decimal("36.6200")
        cfg.minimum_deposit_usd = Decimal("100.00")
        cfg.withdrawal_min = Decimal("10.00")
        cfg.listen_verification_seconds = 10
        cfg.wheel_requires_qualified_referral = False
        cfg.save()
        CurrencyRate.objects.update_or_create(code="NIO", defaults={"name":"Córdoba","symbol":"C$","rate_to_base":Decimal("1"),"active":True})
        CurrencyRate.objects.update_or_create(code="USD", defaults={"name":"US Dollar","symbol":"$","rate_to_base":Decimal("36.62"),"active":True})
        CurrencyRate.objects.update_or_create(code="USDT", defaults={"name":"Tether USD","symbol":"USDT","rate_to_base":Decimal("36.62"),"active":True})
        self.plan = MembershipPlan.objects.create(
            name="HBL 100", slug="hbl-100-test", price_usd=Decimal("100"),
            daily_reward_nio=Decimal("122"), daily_tracks=3, duration_days=30,
        )
        self.tracks = []
        for idx in range(3):
            self.tracks.append(Track.objects.create(
                title=f"Demo {idx+1}", slug=f"demo-{idx+1}", audio_url="https://example.invalid/demo.mp3",
                duration_seconds=40, min_listen_seconds=10, reward_amount=Decimal("0"), daily_user_limit=1,
            ))

    def _activate_and_assign(self):
        membership = purchase_plan(self.user.id, self.plan.id)
        membership, assignments = ensure_daily_assignments(self.user)
        return membership, assignments

    def test_plan_purchase_uses_exchange_rate(self):
        self._activate_and_assign()
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("1338.00"))

    def test_daily_assignments_are_three_and_sum_exact_reward(self):
        _, assignments = self._activate_and_assign()
        self.assertEqual(len(assignments), 3)
        self.assertEqual(sum(a.reward_amount for a in assignments), Decimal("122.00"))

    def test_cannot_reward_too_early(self):
        _, assignments = self._activate_and_assign()
        session, _ = start_listening(self.user, assignments[0])
        with self.assertRaises(HBLError):
            complete_listening(self.user.id, session.id)

    def test_reward_only_after_all_three_and_is_idempotent(self):
        _, assignments = self._activate_and_assign()
        for index, assignment in enumerate(assignments):
            session, _ = start_listening(self.user, assignment)
            ListeningSession.objects.filter(pk=session.pk).update(
                verified_seconds=31, started_at=timezone.now() - timedelta(seconds=12)
            )
            session, credited = complete_listening(self.user.id, session.id)
            self.assertEqual(credited, index == 2)
            if index == 2:
                _, credited_again = complete_listening(self.user.id, session.id)
                self.assertFalse(credited_again)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("1460.00"))

    def test_withdrawal_method_controls_minimum_and_fee(self):
        method = WithdrawalMethod.objects.create(
            name="Binance", slug="binance-test", currency="USDT", network="Binance",
            min_amount_nio=Decimal("50"), fee_percent=Decimal("10"), active=True,
        )
        account = PayoutAccount.objects.create(
            user=self.user, withdrawal_method=method, kind=PayoutAccount.Kind.CUSTOM,
            label="Binance", identifier="123456",
        )
        with self.assertRaises(HBLError):
            request_withdrawal(self.user.id, account, Decimal("49"))
        wd = request_withdrawal(self.user.id, account, Decimal("50"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("4950.00"))
        self.assertEqual(wd.fee, Decimal("5.00"))
        self.assertEqual(wd.net_amount, Decimal("45.00"))


    def test_withdrawal_uses_country_currency_not_display_preference(self):
        cfg = PlatformConfig.get_solo()
        cfg.withdrawal_min = Decimal("500.00")
        cfg.save(update_fields=["withdrawal_min"])
        # El usuario puede visualizar USD, pero Nicaragua retira localmente en NIO.
        self.user.preferred_currency = "USD"
        self.user.save(update_fields=["preferred_currency"])
        self.assertEqual(self.user.country_currency, "NIO")
        method = WithdrawalMethod.objects.create(
            name="Banco local", slug="bank-local-test",
            currency_mode=WithdrawalMethod.CurrencyMode.USER_LOCAL, currency="NIO",
            country="NI", identifier_type=WithdrawalMethod.IdentifierType.BANK,
            min_amount_nio=Decimal("0"), fee_percent=Decimal("5"), active=True,
        )
        account = PayoutAccount.objects.create(
            user=self.user, withdrawal_method=method, kind=PayoutAccount.Kind.CUSTOM,
            label="Mi banco", identifier="123456789", holder_name="Usuario Prueba",
        )
        with self.assertRaises(HBLError):
            request_withdrawal(self.user.id, account, Decimal("499"), requested_currency=self.user.country_currency)
        wd = request_withdrawal(self.user.id, account, Decimal("600"), requested_currency=self.user.country_currency)
        self.assertEqual(wd.requested_currency, "NIO")
        self.assertEqual(wd.payout_currency, "NIO")
        self.assertEqual(wd.amount, Decimal("600.00"))
        self.assertEqual(wd.fee, Decimal("30.00"))
        self.assertEqual(wd.payout_amount, Decimal("570.00000000"))

    def test_fixed_withdrawal_method_pays_in_method_currency(self):
        cfg = PlatformConfig.get_solo()
        cfg.withdrawal_min = Decimal("500.00")
        cfg.save(update_fields=["withdrawal_min"])
        method = WithdrawalMethod.objects.create(
            name="USDT TRC20", slug="usdt-trc20-test",
            currency_mode=WithdrawalMethod.CurrencyMode.FIXED, currency="USDT", network="TRC20",
            identifier_type=WithdrawalMethod.IdentifierType.TRC20, fee_percent=Decimal("0"), active=True,
        )
        account = PayoutAccount.objects.create(
            user=self.user, withdrawal_method=method, kind=PayoutAccount.Kind.CUSTOM,
            label="USDT", identifier="TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE", holder_name="Usuario Prueba",
        )
        wd = request_withdrawal(self.user.id, account, Decimal("732.40"), requested_currency="NIO")
        self.assertEqual(wd.requested_currency, "NIO")
        self.assertEqual(wd.payout_currency, "USDT")
        self.assertEqual(wd.payout_amount, Decimal("20.00000000"))

    def test_global_deposit_minimum_is_usd_100_equivalent(self):
        method = PaymentMethod.objects.create(
            kind=PaymentMethod.Kind.BANK, label="Bank", currency="NIO",
            min_amount=Decimal("1"), balance_rate=Decimal("1"), active=True,
        )
        low = DepositForm(data={"payment_method": method.id, "payment_amount": "3000"})
        self.assertFalse(low.is_valid())
        ok = DepositForm(data={"payment_method": method.id, "payment_amount": "3662"})
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_manual_deposit_approval_only_credits_once(self):
        method = PaymentMethod.objects.create(kind=PaymentMethod.Kind.BANK, label="Bank 2", currency="NIO")
        dep = Deposit.objects.create(user=self.user, payment_method=method, amount=Decimal("25"), currency="NIO")
        approve_deposit(dep.id)
        approve_deposit(dep.id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("5025.00"))

    def test_free_wheel_respects_daily_limit_and_credits_server_side(self):
        self._activate_and_assign()
        config = WheelConfig.get_solo()
        config.enabled = True
        config.spins_per_day = 1
        config.require_active_membership = True
        config.save()
        prize = WheelPrize.objects.create(
            name="C$10", reward_type=WheelPrize.RewardType.BALANCE,
            value=Decimal("10"), weight=100, active=True,
        )
        before = User.objects.get(pk=self.user.pk).saldo
        spin = spin_wheel(self.user.id)
        self.assertEqual(spin.prize_id, prize.id)
        self.assertEqual(WheelSpin.objects.filter(user=self.user).count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, before + Decimal("10"))
        with self.assertRaises(HBLError):
            spin_wheel(self.user.id)

    def test_gift_code_total_and_user_limits(self):
        gift = GiftCode.objects.create(
            code="HBL10", name="Regalo 10", reward_type=GiftCode.RewardType.BALANCE,
            value=Decimal("10"), max_redemptions=1, per_user_limit=1,
        )
        redeem_gift_code(self.user.id, "hbl10")
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, Decimal("5010.00"))
        other = User.objects.create_user(username="other", telefono="+50588887777", password="StrongPass123!")
        with self.assertRaises(HBLError):
            redeem_gift_code(other.id, gift.code)

    def test_referral_commission_is_ten_percent_only_on_first_approved_deposit(self):
        cfg = PlatformConfig.get_solo()
        cfg.referral_first_deposit_percent = Decimal("10.00")
        cfg.save(update_fields=["referral_first_deposit_percent"])
        referred = User.objects.create_user(
            username="ref1", email="ref1@example.com", referido_por=self.user, password="StrongPass123!"
        )
        method = PaymentMethod.objects.create(kind=PaymentMethod.Kind.BANK, label="Referral Bank", currency="NIO", balance_rate=1)
        before = User.objects.get(pk=self.user.pk).saldo
        for idx in range(2):
            dep = Deposit.objects.create(user=referred, payment_method=method, amount=Decimal("1000"), currency="NIO", reference=f"r{idx}")
            approve_deposit(dep.id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.saldo, before + Decimal("100.00"))

    def test_five_qualified_referrals_unlock_one_free_upgrade(self):
        cfg = PlatformConfig.get_solo()
        cfg.free_upgrade_referrals_required = 5
        cfg.save(update_fields=["free_upgrade_referrals_required"])
        self._activate_and_assign()
        MembershipPlan.objects.create(
            name="HBL 200", slug="hbl-200-test", price_usd=Decimal("200"),
            daily_reward_nio=Decimal("200"), daily_tracks=3, duration_days=30, sort_order=20,
        )
        method = PaymentMethod.objects.create(kind=PaymentMethod.Kind.BANK, label="Qualify Bank", currency="NIO", balance_rate=1)
        for idx in range(5):
            ref = User.objects.create_user(username=f"qref{idx}", email=f"qref{idx}@example.com", referido_por=self.user, password="StrongPass123!")
            dep = Deposit.objects.create(user=ref, payment_method=method, amount=Decimal("100"), currency="NIO", reference=f"q{idx}")
            approve_deposit(dep.id)
        option = eligible_referral_upgrade(self.user)
        self.assertIsNotNone(option)
        self.assertEqual(option["required"], 5)
        self.assertEqual(option["next_plan"].slug, "hbl-200-test")

    def test_withdrawal_minimum_can_be_displayed_in_usd(self):
        cfg = PlatformConfig.get_solo()
        cfg.withdrawal_min = Decimal("500.00")
        cfg.save(update_fields=["withdrawal_min"])
        self.assertEqual(display_money(cfg.withdrawal_min, "USD"), Decimal("13.65"))


class RegistrationTests(TestCase):
    def test_phone_only_registration_is_valid(self):
        form = RegistrationForm(data={
            "first_name": "Mario", "last_name": "Luna", "country": "NI",
            "email": "", "phone": "88888888", "password1": "StrongPass123!",
            "password2": "StrongPass123!", "referral_code": "", "accept_terms": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone"], "+50588888888")

    def test_email_only_registration_is_valid(self):
        form = RegistrationForm(data={
            "first_name": "Ana", "last_name": "", "country": "CR",
            "email": "ana@example.com", "phone": "", "password1": "StrongPass123!",
            "password2": "StrongPass123!", "referral_code": "", "accept_terms": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_registration_requires_one_contact(self):
        form = RegistrationForm(data={
            "first_name": "No Contact", "last_name": "", "country": "NI",
            "email": "", "phone": "", "password1": "StrongPass123!",
            "password2": "StrongPass123!", "referral_code": "", "accept_terms": "on",
        })
        self.assertFalse(form.is_valid())
