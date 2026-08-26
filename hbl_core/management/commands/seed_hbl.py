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
    help = "Crea la base inicial de HBL Pro: configuración, catálogo de planes, métodos, referidos y audios demo."

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
        # posteriormente desde HBL Control, salvo el catálogo oficial de planes y las
        # políticas financieras globales que HBL debe mantener consistentes.
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
        usd_rate_row, _ = CurrencyRate.objects.get_or_create(
            code="USD",
            defaults={"name": "US Dollar", "symbol": "$", "rate_to_base": Decimal(config.exchange_rate_usd_nio), "active": True},
        )
        usd_rate = Decimal(usd_rate_row.rate_to_base or 0)
        if usd_rate <= 0:
            usd_rate = Decimal(config.exchange_rate_usd_nio)
        usdt_rate_row, _ = CurrencyRate.objects.get_or_create(
            code="USDT",
            defaults={"name": "Tether USD", "symbol": "₮", "rate_to_base": Decimal(config.exchange_rate_usd_nio), "active": True},
        )
        usdt_rate = Decimal(usdt_rate_row.rate_to_base or 0)
        if usdt_rate <= 0:
            usdt_rate = Decimal(config.exchange_rate_usd_nio)
        for code, label in CRYPTO_CURRENCY_CHOICES:
            if code == "USDT":
                continue
            CurrencyRate.objects.get_or_create(
                code=code,
                defaults={"name": label.split("—", 1)[-1].strip(), "symbol": code, "rate_to_base": Decimal("1.0"), "active": False},
            )

        # Catálogo oficial HLB: 10 niveles, 365 días y retorno diario simple del 5%.
        # La plataforma maneja el saldo en moneda base, por eso convertimos el 5% de
        # cada precio USD usando la tasa USD activa al momento del despliegue.
        plan_specs = [
            ("hbl-basico-20", "BÁSICO", Decimal("20.00"), "🎵", "Inicio HBL", False, 10, "#16C8FF", "#5B7CFF"),
            ("hbl-estandar-100", "ESTÁNDAR", Decimal("100.00"), "🎶", "Popular", True, 20, "#10D7C4", "#43E27D"),
            ("hbl-avanzado-300", "AVANZADO", Decimal("300.00"), "🎧", "Avanzado", False, 30, "#8BD52B", "#35D88B"),
            ("hbl-premium-800", "PREMIUM", Decimal("800.00"), "🎼", "Premium", False, 40, "#F6C526", "#FF9E2A"),
            ("hbl-exclusivo-1500", "EXCLUSIVO", Decimal("1500.00"), "🎤", "Exclusivo", False, 50, "#FF8A18", "#FF5A36"),
            ("hbl-vip-4500", "VIP", Decimal("4500.00"), "🎹", "VIP", False, 60, "#FF4F9A", "#E547D8"),
            ("hbl-elite-10000", "ÉLITE", Decimal("10000.00"), "🎷", "Élite", False, 70, "#B84DFF", "#7D5CFF"),
            ("hbl-maestro-20000", "MAESTRO", Decimal("20000.00"), "🎻", "Maestro", False, 80, "#9D4DFF", "#C346FF"),
            ("hbl-leyenda-50000", "LEYENDA", Decimal("50000.00"), "🏆", "Leyenda", False, 90, "#FFD34D", "#FF9E2A"),
            ("hbl-diamante-100000", "DIAMANTE", Decimal("100000.00"), "💎", "Diamante", False, 100, "#28D7FF", "#36F0E0"),
        ]
        official_plan_slugs = []
        for slug, name, price_usd, icon, badge, featured, sort_order, accent_from, accent_to in plan_specs:
            official_plan_slugs.append(slug)
            daily_reward_usd = (price_usd * Decimal("0.05")).quantize(Decimal("0.01"))
            daily_reward_base = (daily_reward_usd * usd_rate).quantize(Decimal("0.01"))
            MembershipPlan.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": "Completa 3 canciones diarias para recibir la recompensa programada del nivel. Proyección simple: 5% diario sobre el valor USD del plan durante 365 días.",
                    "price_usd": price_usd,
                    "daily_reward_nio": daily_reward_base,
                    "daily_tracks": 3,
                    "duration_days": 365,
                    "badge": badge,
                    "icon": icon,
                    "accent_from": accent_from,
                    "accent_to": accent_to,
                    "featured": featured,
                    "active": True,
                    "sort_order": sort_order,
                },
            )

        # El plan demo anterior queda fuera del catálogo nuevo, sin borrar membresías históricas.
        MembershipPlan.objects.filter(slug="hbl-100").update(active=False)

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
                    "fee_percent": Decimal("0.00"), "fee_fixed_nio": usdt_rate,
                    "active": True,
                },
            )
        # Política HBL: el retiro cobra exactamente 1 USDT adicional. El formulario
        # suma ese cargo al total reservado para que el usuario reciba el monto neto
        # que escribió en pantalla.
        WithdrawalMethod.objects.filter(slug="usdt-trc20").update(
            currency_mode=WithdrawalMethod.CurrencyMode.FIXED,
            currency="USDT",
            country="",
            network="TRON (TRC20)",
            identifier_type=WithdrawalMethod.IdentifierType.TRC20,
            holder_required=False,
            fee_percent=Decimal("0.00"),
            fee_fixed_nio=usdt_rate,
            active=True,
        )
        WithdrawalMethod.objects.filter(slug="usdt-bep20").update(
            currency_mode=WithdrawalMethod.CurrencyMode.FIXED,
            currency="USDT",
            country="",
            network="BNB Smart Chain (BEP20)",
            identifier_type=WithdrawalMethod.IdentifierType.BEP20,
            holder_required=False,
            fee_percent=Decimal("0.00"),
            fee_fixed_nio=usdt_rate,
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
            "HBL Ultra inicializado: 10 planes oficiales al 5% diario + audios demo + retiros administrables + ruleta promocional. Entra a /control/."
        ))
