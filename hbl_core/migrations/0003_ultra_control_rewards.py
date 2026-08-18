from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_worldwide_contact_blocking"),
        ("hbl_core", "0002_memberships_control"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformconfig",
            name="minimum_deposit_usd",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("100.00"),
                help_text="Recarga mínima global expresada en USD. Se convierte con la tasa USD/NIO vigente.",
                max_digits=12,
            ),
        ),
        migrations.AddField(model_name="membershipplan", name="icon", field=models.CharField(blank=True, default="🎧", max_length=16)),
        migrations.AddField(model_name="membershipplan", name="accent_from", field=models.CharField(blank=True, default="#7C5CFC", max_length=7)),
        migrations.AddField(model_name="membershipplan", name="accent_to", field=models.CharField(blank=True, default="#25D9A6", max_length=7)),
        migrations.AddField(
            model_name="paymentmethod",
            name="max_amount",
            field=models.DecimalField(decimal_places=8, default=Decimal("0.00000000"), help_text="0 = sin máximo por operación", max_digits=18),
        ),
        migrations.AddField(model_name="paymentmethod", name="require_proof", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="paymentmethod", name="require_txid", field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name="WithdrawalMethod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("currency", models.CharField(default="NIO", max_length=12)),
                ("network", models.CharField(blank=True, max_length=40)),
                ("icon", models.CharField(blank=True, default="💸", max_length=16)),
                ("instructions", models.TextField(blank=True)),
                ("account_label", models.CharField(default="Cuenta / dirección", max_length=80)),
                ("holder_required", models.BooleanField(default=True)),
                ("min_amount_nio", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="0 = usar mínimo global", max_digits=14)),
                ("max_amount_nio", models.DecimalField(decimal_places=2, default=Decimal("0.00"), help_text="0 = sin máximo", max_digits=14)),
                ("fee_percent", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6)),
                ("fee_fixed_nio", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["sort_order", "name"]},
        ),
        migrations.AlterField(
            model_name="payoutaccount",
            name="kind",
            field=models.CharField(
                choices=[
                    ("bank", "Cuenta bancaria"), ("binance_id", "Binance Pay ID / Binance ID"),
                    ("usdt_trc20", "USDT TRC20"), ("usdt_bep20", "USDT BEP20"),
                    ("crypto_other", "Otra wallet"), ("remittance", "Giro / remesa"),
                    ("mobile_wallet", "Billetera móvil"), ("custom", "Método administrable"),
                ],
                default="custom",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="payoutaccount",
            name="withdrawal_method",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payout_accounts", to="hbl_core.withdrawalmethod"),
        ),
        migrations.AlterField(
            model_name="rewardledger",
            name="kind",
            field=models.CharField(
                choices=[
                    ("listen", "Escucha"), ("membership_reward", "Recompensa de membresía"),
                    ("plan_purchase", "Compra de plan"), ("referral", "Referido"),
                    ("referral_salary", "Sueldo por referidos"), ("deposit", "Recarga"),
                    ("withdrawal", "Retiro"), ("withdrawal_refund", "Reembolso de retiro"),
                    ("wheel", "Premio de ruleta"), ("gift_code", "Código de regalo"),
                    ("signup", "Registro"), ("admin", "Ajuste administrativo"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="WheelConfig",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True)),
                ("title", models.CharField(default="Ruleta HBL", max_length=120)),
                ("subtitle", models.CharField(blank=True, default="Giro promocional gratuito", max_length=220)),
                ("spins_per_day", models.PositiveSmallIntegerField(default=1)),
                ("cooldown_minutes", models.PositiveIntegerField(default=0)),
                ("require_active_membership", models.BooleanField(default=True)),
                ("terms", models.TextField(blank=True, default="Participación promocional gratuita. No requiere apuesta ni pago por giro.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Configuración de ruleta", "verbose_name_plural": "Configuración de ruleta"},
        ),
        migrations.CreateModel(
            name="WheelPrize",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("reward_type", models.CharField(choices=[("balance", "Saldo C$"), ("membership_days", "Días extra de membresía"), ("none", "Sin premio")], default="balance", max_length=24)),
                ("value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("weight", models.PositiveIntegerField(default=10, help_text="Peso relativo. Mayor peso = más frecuente.")),
                ("icon", models.CharField(blank=True, default="🎁", max_length=16)),
                ("color", models.CharField(default="#7C5CFC", max_length=7)),
                ("daily_global_limit", models.PositiveIntegerField(default=0, help_text="0 = sin límite diario global")),
                ("total_stock", models.PositiveIntegerField(default=0, help_text="0 = ilimitado")),
                ("active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=10)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="WheelSpin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reward_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("prize", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="spins", to="hbl_core.wheelprize")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="hbl_wheel_spins", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="wheelspin", index=models.Index(fields=["user", "created_at"], name="hbl_wheel_user_date")),
        migrations.CreateModel(
            name="GiftCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=32, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("reward_type", models.CharField(choices=[("balance", "Saldo C$"), ("membership_days", "Días extra de membresía")], default="balance", max_length=24)),
                ("value", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("max_redemptions", models.PositiveIntegerField(default=1, help_text="Cantidad total de personas/usos permitidos. 0 = ilimitado")),
                ("per_user_limit", models.PositiveSmallIntegerField(default=1)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
                ("require_active_membership", models.BooleanField(default=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("required_plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="gift_codes", to="hbl_core.membershipplan")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="GiftRedemption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reward_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("gift", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redemptions", to="hbl_core.giftcode")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="hbl_gift_redemptions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="giftredemption", index=models.Index(fields=["gift", "user", "created_at"], name="hbl_gift_user_date")),
    ]
