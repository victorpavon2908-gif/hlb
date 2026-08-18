import re
import secrets
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .countries import COUNTRY_CHOICES
from .country_currency import COUNTRY_CURRENCY


class User(AbstractUser):
    REQUIRED_FIELDS = []

    class ContactPreference(models.TextChoices):
        AUTO = "auto", "Automático"
        EMAIL = "email", "Correo electrónico"
        PHONE = "phone", "Teléfono"

    email = models.EmailField(unique=True, blank=True, null=True)
    saldo = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    telefono = models.CharField(max_length=32, unique=True, blank=True, null=True)
    country = models.CharField(max_length=2, choices=COUNTRY_CHOICES, default="NI", db_index=True)
    preferred_currency = models.CharField(max_length=3, blank=True, default="", help_text="Moneda usada para mostrar equivalencias al usuario.")
    timezone_name = models.CharField(max_length=64, blank=True, default="UTC", help_text="Zona horaria IANA detectada en el dispositivo, por ejemplo America/Managua.")
    contact_preference = models.CharField(max_length=10, choices=ContactPreference.choices, default=ContactPreference.AUTO)
    codigo_invitacion = models.CharField(max_length=16, unique=True, blank=True, db_index=True)
    referido_por = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="referidos",
    )
    blocked_reason = models.CharField(max_length=240, blank=True)
    blocked_at = models.DateTimeField(blank=True, null=True)
    blocked_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="hbl_blocked_users",
    )

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return self.email or self.telefono or self.username

    @property
    def country_currency(self):
        """Moneda local asociada al país de la cuenta.

        Se usa para retiros locales y no depende de la moneda de visualización
        que el usuario elija en su perfil.
        """
        return COUNTRY_CURRENCY.get(self.country, self.preferred_currency or "USD")

    @property
    def primary_contact(self):
        if self.contact_preference == self.ContactPreference.PHONE and self.telefono:
            return self.telefono
        if self.contact_preference == self.ContactPreference.EMAIL and self.email:
            return self.email
        return self.email or self.telefono or self.username

    @property
    def is_blocked(self):
        return not self.is_active

    @classmethod
    def _new_referral_code(cls):
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))

    @classmethod
    def generate_username(cls):
        for _ in range(50):
            candidate = f"hbl{secrets.token_hex(4)}"
            if not cls.objects.filter(username=candidate).exists():
                return candidate
        raise RuntimeError("No se pudo generar un usuario único.")

    @staticmethod
    def normalize_phone(value):
        value = (value or "").strip()
        if not value:
            return None
        value = re.sub(r"[\s().-]", "", value)
        if value.startswith("00"):
            value = "+" + value[2:]
        return value

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower() or None
        self.telefono = self.normalize_phone(self.telefono)
        if not self.preferred_currency:
            self.preferred_currency = COUNTRY_CURRENCY.get(self.country, "USD")
        if not self.codigo_invitacion:
            for _ in range(20):
                candidate = self._new_referral_code()
                if not type(self).objects.filter(codigo_invitacion=candidate).exists():
                    self.codigo_invitacion = candidate
                    break
            else:
                raise RuntimeError("No se pudo generar un código de invitación único.")
        if self.is_active and self.blocked_at:
            self.blocked_at = None
            self.blocked_reason = ""
            self.blocked_by = None
        super().save(*args, **kwargs)

    def block(self, actor=None, reason=""):
        self.is_active = False
        self.blocked_at = timezone.now()
        self.blocked_reason = (reason or "Bloqueada por administración")[:240]
        self.blocked_by = actor
        self.save(update_fields=["is_active", "blocked_at", "blocked_reason", "blocked_by"])

    def unblock(self):
        self.is_active = True
        self.blocked_at = None
        self.blocked_reason = ""
        self.blocked_by = None
        self.save(update_fields=["is_active", "blocked_at", "blocked_reason", "blocked_by"])
