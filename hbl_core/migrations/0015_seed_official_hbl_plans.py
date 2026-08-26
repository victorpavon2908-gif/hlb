from decimal import Decimal

from django.db import migrations


PLAN_SPECS = [
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


def seed_official_plans(apps, schema_editor):
    MembershipPlan = apps.get_model("hbl_core", "MembershipPlan")
    CurrencyRate = apps.get_model("hbl_core", "CurrencyRate")
    PlatformConfig = apps.get_model("hbl_core", "PlatformConfig")

    usd_rate = CurrencyRate.objects.filter(code="USD", active=True).values_list("rate_to_base", flat=True).first()
    if not usd_rate:
        config = PlatformConfig.objects.filter(pk=1).first()
        usd_rate = getattr(config, "exchange_rate_usd_nio", None) or Decimal("36.62")
    usd_rate = Decimal(str(usd_rate))

    for slug, name, price_usd, icon, badge, featured, sort_order, accent_from, accent_to in PLAN_SPECS:
        daily_reward_usd = (price_usd * Decimal("0.05")).quantize(Decimal("0.01"))
        daily_reward_base = (daily_reward_usd * usd_rate).quantize(Decimal("0.01"))
        MembershipPlan.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": "Completa 3 canciones diarias para recibir la recompensa programada del nivel.",
                "price_usd": price_usd,
                "daily_reward_nio": daily_reward_base,
                "daily_tracks": 3,
                "duration_days": 365,
                "badge": badge,
                "icon": icon,
                "accent_from": accent_from,
                "accent_to": accent_to,
                "active": True,
                "featured": featured,
                "sort_order": sort_order,
            },
        )

    MembershipPlan.objects.filter(slug="hbl-100").update(active=False)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hbl_core", "0014_global_minimum_10_usdt"),
    ]

    operations = [
        migrations.RunPython(seed_official_plans, noop_reverse),
    ]
