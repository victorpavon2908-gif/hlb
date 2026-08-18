from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

from accounts.countries import COUNTRY_CHOICES


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="user",
            name="telefono",
            field=models.CharField(blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="user",
            name="country",
            field=models.CharField(choices=COUNTRY_CHOICES, db_index=True, default="NI", max_length=2),
        ),
        migrations.AddField(
            model_name="user",
            name="contact_preference",
            field=models.CharField(
                choices=[("auto", "Automático"), ("email", "Correo electrónico"), ("phone", "Teléfono")],
                default="auto",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="blocked_reason",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name="user",
            name="blocked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="blocked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hbl_blocked_users",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
