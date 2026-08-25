import math
import struct
import wave
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from hbl_core.models import (
    CurrencyRate, MembershipPlan, PaymentMethod, PlatformConfig, ReferralTier, Track,
    WithdrawalMethod, WheelConfig, WheelPrize,
)
from accounts.currencies import CURRENCY_CHOICES, CRYPTO_CURRENCY_CHOICES, COMMON_CURRENCY_SYMBOLS


class Command(BaseCommand):
    help = "Crea la base inicial de HBL Pro: configuración, plan ejemplo, métodos, referidos y audios demo."

    def _make_demo_audio(self, filename, base_freq):
        storage_name = f"hbl/audio/{filename}"
        if default_storage.exists(storage_name):
            return storage_name
        rate = 8000
        seconds = 40
        amplitude = 7000
        buffer = BytesIO()
        with wave.open(buffer, "w") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            frames = bytearray()
            for i in range(rate * seconds):
                t = i / rate
                beat = 1.0 if int(t * 2) % 2 == 0 else 0.72
                sample = (
                    math.sin(2 * math.pi * base_freq * t)
                    + 0.45 * math.sin(2 * math.pi * (base_freq * 1.5) * t)
                    + 0.2 * math.sin(2 * math.pi * (base_freq * 2.0) * t)
                )
                value = int(max(-32767, min(32767, amplitude * beat * sample)))
                frames.extend(struct.pack("<h", value))
            wav.writeframes(frames)
        default_storage.save(storage_name, ContentFile(buffer.getvalue()))
        return storage_name

    def handle(self, *args, **options):
        # El comando es idempotente: una segunda ejecución NO pisa reglas cambiadas
        # posteriormente desde HBL Control. Los defaults del modelo se usan al crear.
        config = PlatformConfig.get_solo()

        # Catálogo completo de monedas fiat. Se crean inactivas hasta que administración configure su tasa.
        # USD y la moneda base se crean después con sus valores iniciales correctos.
        for code, label in CURRENCY_CHOICES:
            if code in {config.base_currency_code.upper(), "USD"}:
                continue
            name = label.split("—", 1)[-1].strip() if "—" in label else label
            CurrencyRate.objects.get_or_create(
                code=code,
                defaults={"name": name, "symbol": COMMON_CURRENCY_SYMBOLS.get(code, code), "rate_to_base": Decimal("1.0"), "active": code == config.base_currency_code},
            )
        CurrencyRate.objects.get_or_create(
            code=config.base_currency_code.upper(),
            defaults={"name": config.base_currency_code.upper(), "symbol": config.base_currency_symbol, "rate_to_base": Decimal("1.0"), "active": True},
        )
        CurrencyRate.objects.get_or_create(
            code="USD",
            defaults={"name": "US Dollar", "symbol": "$", "rate_to_base": Decimal(config.exchange_rate_usd_nio), "active": True},
        )
        CurrencyRate.objects.get_or_create(
            code="USDT",
            defaults={"name": "Tether USD", "symbol": "₮", "rate_to_base": Decimal(config.exchange_rate_usd_nio), "active": True},
        )
        for code, label in CRYPTO_CURRENCY_CHOICES:
            if code == "USDT":
                continue
            CurrencyRate.objects.get_or_create(
                code=code,
                defaults={"name": label.split("—", 1)[-1].strip(), "symbol": code, "rate_to_base": Decimal("1.0"), "active": False},
            )

        plan, _ = MembershipPlan.objects.get_or_create(
            slug="hbl-100",
            defaults={
                "name": "HBL 100",
                "description": "Nivel mensual de ejemplo: completa 3 canciones diarias para recibir la recompensa configurada.",
                "price_usd": 100,
                "daily_reward_nio": 122,
                "daily_tracks": 3,
                "duration_days": 30,
                "badge": "Nivel destacado",
                "featured": True,
                "active": True,
                "sort_order": 10,
            },
        )

        methods = [
            (PaymentMethod.Kind.USDT_TRC20, "USDT por TRC20", "USDT", "TRON (TRC20)", Decimal(config.exchange_rate_usd_nio)),
            (PaymentMethod.Kind.USDT_BEP20, "USDT por BEP20", "USDT", "BNB Smart Chain (BEP20)", Decimal(config.exchange_rate_usd_nio)),
        ]
        for kind, label, currency, network, rate in methods:
            PaymentMethod.objects.get_or_create(
                kind=kind,
                label=label,
                defaults={
                    "currency": currency, "network": network, "active": False, "balance_rate": rate,
                    "min_amount": Decimal("100.00") if currency == "USDT" else (Decimal(config.minimum_deposit_usd) * Decimal(config.exchange_rate_usd_nio)).quantize(Decimal("0.01")),
                    "require_proof": False,
                    "require_txid": False,
                    "instructions": "NOWPayments generará el monto y la dirección exactos para la orden.",
                },
            )

        withdrawal_methods = [
            ("usdt-trc20", "USDT TRC20", "USDT", "TRON (TRC20)", "₮", "Dirección USDT TRC20", False, WithdrawalMethod.CurrencyMode.FIXED, WithdrawalMethod.IdentifierType.TRC20, "Ej. TAbc...", "Verifica que la dirección corresponda a USDT en TRC20."),
            ("usdt-bep20", "USDT BEP20", "USDT", "BNB Smart Chain (BEP20)", "₮", "Dirección USDT BEP20", False, WithdrawalMethod.CurrencyMode.FIXED, WithdrawalMethod.IdentifierType.BEP20, "Ej. 0xabc...", "Verifica que la dirección corresponda a USDT en BEP20/EVM."),
        ]
        for slug, name, currency, network, icon, account_label, holder_required, currency_mode, identifier_type, placeholder, help_text in withdrawal_methods:
            WithdrawalMethod.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name, "currency_mode": currency_mode, "currency": currency, "network": network, "icon": icon,
                    "account_label": account_label, "identifier_type": identifier_type, "identifier_placeholder": placeholder,
                    "identifier_help": help_text, "holder_required": holder_required,
                    "min_amount_nio": Decimal("0.00"), "max_amount_nio": Decimal("0.00"),
                    "fee_percent": Decimal("0.00"), "fee_fixed_nio": Decimal("0.00"),
                    "active": True,
                },
            )
        WithdrawalMethod.objects.filter(slug="usdt-trc20").update(
            currency_mode=WithdrawalMethod.CurrencyMode.FIXED,
            currency="USDT",
            country="",
            network="TRON (TRC20)",
            identifier_type=WithdrawalMethod.IdentifierType.TRC20,
            holder_required=False,
            active=True,
        )
        WithdrawalMethod.objects.filter(slug="usdt-bep20").update(
            currency_mode=WithdrawalMethod.CurrencyMode.FIXED,
            currency="USDT",
            country="",
            network="BNB Smart Chain (BEP20)",
            identifier_type=WithdrawalMethod.IdentifierType.BEP20,
            holder_required=False,
            active=True,
        )
        WithdrawalMethod.objects.exclude(
            slug__in=["usdt-trc20", "usdt-bep20"],
        ).update(active=False)

        # No sobrescribir reglas de ruleta ya editadas desde HBL Control.
        WheelConfig.objects.get_or_create(pk=1)
        if not WheelPrize.objects.exists():
            WheelPrize.objects.bulk_create([
                WheelPrize(name="Sigue participando", reward_type=WheelPrize.RewardType.NONE, value=0, weight=55, icon="🎧", color="#303955", sort_order=10),
                WheelPrize(name="5 de saldo", reward_type=WheelPrize.RewardType.BALANCE, value=5, weight=25, icon="✨", color="#7C5CFC", sort_order=20),
                WheelPrize(name="10 de saldo", reward_type=WheelPrize.RewardType.BALANCE, value=10, weight=15, icon="🎁", color="#25D9A6", sort_order=30),
                WheelPrize(name="25 de saldo", reward_type=WheelPrize.RewardType.BALANCE, value=25, weight=5, icon="💎", color="#FFB648", daily_global_limit=10, sort_order=40),
            ])

        tiers = [("Bronce", 5), ("Plata", 15), ("Oro", 30)]
        for name, threshold in tiers:
            ReferralTier.objects.get_or_create(
                min_active_referrals=threshold,
                defaults={"name": name, "weekly_salary": 0, "active": False},
            )

        demos = [
            ("hbl-demo-neon", "Neon Pulse", 220),
            ("hbl-demo-wave", "Midnight Wave", 261.63),
            ("hbl-demo-orbit", "Orbit Dreams", 329.63),
        ]
        for slug, title, freq in demos:
            audio_name = self._make_demo_audio(f"{slug}.wav", freq)
            track, _ = Track.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "artist": "HBL Demo Studio",
                    "audio": audio_name,
                    "duration_seconds": 40,
                    "min_listen_seconds": 10,
                    "reward_amount": 0,
                    "daily_user_limit": 1,
                    "active": True,
                    "featured": True,
                },
            )
            if track.min_listen_seconds != 10:
                track.min_listen_seconds = 10
                track.save(update_fields=["min_listen_seconds"])

        self.stdout.write(self.style.SUCCESS(
            "HBL Ultra inicializado: HBL 100 + audios demo + retiros administrables + ruleta promocional. Entra a /control/."
        ))
