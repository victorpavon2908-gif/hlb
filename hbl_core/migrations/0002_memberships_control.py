from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("hbl_core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformconfig",
            name="exchange_rate_usd_nio",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("36.6200"),
                help_text="Córdobas (NIO) equivalentes a US$1. Se usa para mostrar equivalencias y comprar planes.",
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name="platformconfig",
            name="legal_notice",
            field=models.TextField(
                blank=True,
                default="HBL ofrece membresías de recompensas por tareas de escucha. Las recompensas, condiciones y vigencia deben mostrarse de forma transparente al usuario.",
            ),
        ),
        migrations.CreateModel(
            name="MembershipPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("price_usd", models.DecimalField(decimal_places=2, max_digits=12)),
                ("daily_reward_nio", models.DecimalField(decimal_places=2, max_digits=12)),
                ("daily_tracks", models.PositiveSmallIntegerField(default=3)),
                ("duration_days", models.PositiveSmallIntegerField(default=30)),
                ("badge", models.CharField(blank=True, max_length=40)),
                ("active", models.BooleanField(default=True)),
                ("featured", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "price_usd"]},
        ),
        migrations.AddField(
            model_name="track",
            name="allowed_plans",
            field=models.ManyToManyField(
                blank=True,
                help_text="Vacío = disponible para todos los planes.",
                related_name="tracks",
                to="hbl_core.membershipplan",
            ),
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("active", "Activa"), ("expired", "Vencida"), ("canceled", "Cancelada")], default="active", max_length=16)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("price_usd_snapshot", models.DecimalField(decimal_places=2, max_digits=12)),
                ("exchange_rate_snapshot", models.DecimalField(decimal_places=4, max_digits=10)),
                ("daily_reward_snapshot", models.DecimalField(decimal_places=2, max_digits=12)),
                ("daily_tracks_snapshot", models.PositiveSmallIntegerField(default=3)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="hbl_memberships_activated", to=settings.AUTH_USER_MODEL)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="hbl_core.membershipplan")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="hbl_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-starts_at"]},
        ),
        migrations.AddIndex(
            model_name="membership",
            index=models.Index(fields=["user", "status", "ends_at"], name="hbl_member_user_status_end"),
        ),
        migrations.CreateModel(
            name="DailyAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assignment_date", models.DateField()),
                ("position", models.PositiveSmallIntegerField()),
                ("reward_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("membership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="daily_assignments", to="hbl_core.membership")),
                ("track", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="daily_assignments", to="hbl_core.track")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="hbl_daily_assignments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["assignment_date", "position"]},
        ),
        migrations.AddConstraint(
            model_name="dailyassignment",
            constraint=models.UniqueConstraint(fields=("user", "assignment_date", "position"), name="uniq_hbl_daily_assignment_position"),
        ),
        migrations.AddConstraint(
            model_name="dailyassignment",
            constraint=models.UniqueConstraint(fields=("user", "assignment_date", "track"), name="uniq_hbl_daily_assignment_track"),
        ),
        migrations.AddIndex(
            model_name="dailyassignment",
            index=models.Index(fields=["user", "assignment_date", "completed_at"], name="hbl_daily_user_date_done"),
        ),
        migrations.AddField(
            model_name="listeningsession",
            name="assignment",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="listening_sessions", to="hbl_core.dailyassignment"),
        ),
        migrations.AlterField(
            model_name="rewardledger",
            name="kind",
            field=models.CharField(
                choices=[
                    ("listen", "Escucha"),
                    ("membership_reward", "Recompensa de membresía"),
                    ("plan_purchase", "Compra de plan"),
                    ("referral", "Referido"),
                    ("referral_salary", "Sueldo por referidos"),
                    ("deposit", "Recarga"),
                    ("withdrawal", "Retiro"),
                    ("withdrawal_refund", "Reembolso de retiro"),
                    ("signup", "Registro"),
                    ("admin", "Ajuste administrativo"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="AdminAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=80)),
                ("target_type", models.CharField(blank=True, max_length=80)),
                ("target_id", models.CharField(blank=True, max_length=100)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="hbl_admin_actions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="adminauditlog",
            index=models.Index(fields=["action", "created_at"], name="hbl_audit_action_date"),
        ),
    ]
