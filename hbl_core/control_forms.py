from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.countries import COUNTRY_CHOICES
from accounts.currencies import CURRENCY_CHOICES, PAYMENT_CURRENCY_CHOICES
from .forms import normalize_phone
from .models import (
    CurrencyRate,
    GiftCode,
    MembershipPlan,
    PaymentMethod,
    PlatformConfig,
    ReferralTier,
    Track,
    WheelConfig,
    WheelPrize,
    WithdrawalMethod,
)

User = get_user_model()


PLACEHOLDERS = {
    "name": "Nombre descriptivo",
    "slug": "ej. hbl-premium",
    "description": "Descripción clara para el cliente",
    "label": "Nombre visible",
    "network": "Ej. TRC20, BEP20, Banco X",
    "destination": "Cuenta, wallet o identificador receptor",
    "instructions": "Instrucciones visibles para el cliente",
    "account_label": "Ej. Binance Pay ID",
    "identifier_placeholder": "Ej. 123456789 o TAbc...",
    "identifier_help": "Explica exactamente qué dato debe ingresar el cliente",
    "badge": "Ej. Recomendado",
    "icon": "Ej. 🎧",
    "title": "Título",
    "artist": "Artista",
    "cover_url": "https://.../portada.webp",
    "audio_url": "https://.../audio.mp3",
    "code": "Ej. HBLBIENVENIDA",
    "reason": "Motivo obligatorio para auditoría",
    "base_currency_symbol": "Ej. C$",
}


class ControlModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple, forms.FileInput)):
                field.widget.attrs.setdefault("class", "control-input")
                if name in PLACEHOLDERS:
                    field.widget.attrs.setdefault("placeholder", PLACEHOLDERS[name])
                elif isinstance(field, (forms.DecimalField, forms.IntegerField, forms.FloatField)):
                    field.widget.attrs.setdefault("placeholder", "Ej. 100.00")
                elif isinstance(field, (forms.CharField,)) and not isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("placeholder", f"Ingresa {field.label.lower()}")
            if isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", "control-file")


class MembershipPlanForm(ControlModelForm):
    class Meta:
        model = MembershipPlan
        fields = [
            "name", "slug", "description", "price_usd", "daily_reward_nio",
            "daily_tracks", "duration_days", "badge", "icon", "accent_from", "accent_to",
            "active", "featured", "sort_order",
        ]
        labels = {
            "price_usd": "Precio del plan (USD)",
            "daily_reward_nio": "Recompensa diaria (moneda base)",
            "daily_tracks": "Canciones requeridas por día",
            "duration_days": "Duración del ciclo (días)",
            "active": "Disponible para clientes",
            "featured": "Destacar visualmente",
            "sort_order": "Orden de aparición",
        }
        help_texts = {
            "daily_reward_nio": "Se acredita una sola vez al completar todas las canciones del día.",
            "daily_tracks": "El cliente debe completar todas para recibir la recompensa diaria.",
        }
        widgets = {
            "accent_from": forms.TextInput(attrs={"type": "color"}),
            "accent_to": forms.TextInput(attrs={"type": "color"}),
        }


class TrackForm(ControlModelForm):
    MAX_AUDIO_BYTES = 25 * 1024 * 1024
    ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}

    def clean_audio(self):
        audio = self.cleaned_data.get("audio")
        if not audio:
            return audio
        if getattr(audio, "size", 0) > self.MAX_AUDIO_BYTES:
            raise forms.ValidationError("El audio no puede superar 25 MB.")
        from pathlib import Path as _Path
        suffix = _Path(getattr(audio, "name", "")).suffix.lower()
        if suffix not in self.ALLOWED_AUDIO_EXTENSIONS:
            raise forms.ValidationError("Formato no permitido. Usa MP3, WAV, OGG, M4A, AAC o FLAC.")
        return audio

    class Meta:
        model = Track
        fields = [
            "title", "artist", "slug", "cover", "cover_url", "audio", "audio_url",
            "duration_seconds", "min_listen_seconds", "allowed_plans", "active", "featured",
        ]
        labels = {
            "duration_seconds": "Duración aproximada (segundos)",
            "min_listen_seconds": "Segundos mínimos de escucha",
            "allowed_plans": "Planes permitidos",
            "active": "Canción activa",
            "featured": "Destacada",
        }
        help_texts = {
            "audio": "Sube audio propio/licenciado. Evita archivos innecesariamente pesados.",
            "allowed_plans": "Sin seleccionar planes = disponible para todos.",
        }
        widgets = {"allowed_plans": forms.CheckboxSelectMultiple}


class PaymentMethodForm(ControlModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].widget = forms.Select(choices=PAYMENT_CURRENCY_CHOICES, attrs={"class": "control-input"})
        self.fields["currency"].choices = PAYMENT_CURRENCY_CHOICES

    class Meta:
        model = PaymentMethod
        fields = [
            "kind", "label", "currency", "network", "destination", "instructions",
            "min_amount", "max_amount", "balance_rate", "require_proof", "require_txid",
            "active", "sort_order",
        ]
        labels = {
            "kind": "Tipo", "label": "Nombre visible", "currency": "Moneda recibida",
            "network": "Red / proveedor", "destination": "Cuenta / wallet de destino",
            "instructions": "Instrucciones para el usuario", "min_amount": "Mínimo del método",
            "max_amount": "Máximo del método (0 = sin máximo)", "balance_rate": "Unidades de moneda base por unidad recibida",
            "require_proof": "Exigir comprobante", "require_txid": "Exigir TXID / referencia",
            "active": "Método activo", "sort_order": "Orden",
        }
        help_texts = {
            "balance_rate": "Debe coincidir con la tasa real usada para acreditar saldo. Para monedas administradas en Monedas y tasas, mantén ambas coherentes.",
            "destination": "Nunca publiques claves privadas, secretos API ni frases semilla en este campo.",
        }


class WithdrawalMethodForm(ControlModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].widget = forms.Select(choices=PAYMENT_CURRENCY_CHOICES, attrs={"class": "control-input"})
        self.fields["currency"].choices = PAYMENT_CURRENCY_CHOICES
        self.fields["country"].widget = forms.Select(choices=[("", "Todos los países")] + list(COUNTRY_CHOICES), attrs={"class": "control-input"})
        self.fields["country"].choices = [("", "Todos los países")] + list(COUNTRY_CHOICES)

    class Meta:
        model = WithdrawalMethod
        fields = [
            "name", "slug", "country", "currency_mode", "currency", "network", "icon", "instructions",
            "account_label", "identifier_type", "identifier_placeholder", "identifier_help", "holder_required",
            "min_amount_nio", "max_amount_nio", "fee_percent", "fee_fixed_nio", "active", "sort_order",
        ]
        labels = {
            "name": "Nombre visible", "slug": "Identificador interno", "country": "País permitido",
            "currency_mode": "Cómo se determina la moneda de pago", "currency": "Moneda fija del método",
            "network": "Red / proveedor", "icon": "Icono", "instructions": "Instrucciones para el cliente",
            "account_label": "Etiqueta del campo de destino", "identifier_type": "Tipo de dato / validación",
            "identifier_placeholder": "Ejemplo mostrado al cliente", "identifier_help": "Ayuda debajo del campo",
            "holder_required": "Exigir nombre del titular", "min_amount_nio": "Mínimo en moneda base (0 = mínimo global)",
            "max_amount_nio": "Máximo en moneda base (0 = sin máximo)", "fee_percent": "Comisión porcentual %",
            "fee_fixed_nio": "Comisión fija en moneda base", "active": "Disponible para usuarios", "sort_order": "Orden",
        }
        help_texts = {
            "currency_mode": "Moneda local usa la moneda asociada al país de la cuenta; moneda fija usa el código seleccionado.",
            "country": "Déjalo en Todos los países para un método global como Binance/USDT.",
            "identifier_type": "HBL aplicará validación del lado servidor según el tipo elegido.",
            "min_amount_nio": "Se aplica el mayor entre este mínimo y el mínimo global.",
        }


class PlatformConfigForm(ControlModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_currency_code"].widget = forms.Select(choices=CURRENCY_CHOICES, attrs={"class": "control-input"})
        self.fields["base_currency_code"].choices = CURRENCY_CHOICES

    class Meta:
        model = PlatformConfig
        fields = [
            "base_currency_code", "base_currency_symbol", "exchange_rate_usd_nio", "minimum_deposit_usd", "withdrawal_min",
            "referral_first_deposit_percent", "free_upgrade_referrals_required", "wheel_requires_qualified_referral",
            "wheel_min_qualified_referrals", "daily_listen_reward_cap", "referral_activity_days", "signup_bonus",
            "listen_verification_seconds", "maintenance_mode", "legal_notice",
        ]
        labels = {
            "base_currency_code": "Moneda base del sistema", "base_currency_symbol": "Símbolo visible de la moneda base",
            "exchange_rate_usd_nio": "Tasa USD → moneda base", "minimum_deposit_usd": "Depósito mínimo global (USD)",
            "withdrawal_min": "Retiro mínimo global (moneda base)",
            "referral_first_deposit_percent": "Comisión SOLO sobre la primera recarga aprobada del referido (%)",
            "free_upgrade_referrals_required": "Referidos calificados por cada subida gratuita de plan",
            "wheel_requires_qualified_referral": "Exigir referidos calificados para usar la ruleta",
            "wheel_min_qualified_referrals": "Referidos calificados mínimos para ruleta",
            "daily_listen_reward_cap": "Tope diario global de recompensas (moneda base, 0 = sin tope)",
            "referral_activity_days": "Días para considerar referido activo", "signup_bonus": "Bono de registro (moneda base)",
            "listen_verification_seconds": "Segundos efectivos para validar cada canción",
            "maintenance_mode": "Modo mantenimiento", "legal_notice": "Aviso / términos visibles",
        }
        help_texts = {
            "withdrawal_min": "Valor inicial recomendado: 500. El cliente ve el equivalente en su moneda local y en la moneda del método.",
            "referral_first_deposit_percent": "No se paga en la segunda ni en recargas posteriores.",
            "listen_verification_seconds": "Valor solicitado: 10 segundos. El servidor valida tiempo efectivo, no solo el botón del navegador.",
        }


class CurrencyRateForm(ControlModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget = forms.Select(choices=PAYMENT_CURRENCY_CHOICES, attrs={"class": "control-input"})
        self.fields["code"].choices = PAYMENT_CURRENCY_CHOICES

    class Meta:
        model = CurrencyRate
        fields = ["code", "name", "symbol", "rate_to_base", "active"]
        labels = {
            "code": "Moneda", "name": "Nombre", "symbol": "Símbolo",
            "rate_to_base": "1 unidad equivale a (moneda base)", "active": "Disponible para conversiones",
        }
        help_texts = {"rate_to_base": "No adivines tasas. Usa una tasa vigente y verificable antes de habilitar la moneda para operaciones reales."}


class ReferralTierForm(ControlModelForm):
    class Meta:
        model = ReferralTier
        fields = ["name", "min_active_referrals", "weekly_salary", "active"]
        labels = {"min_active_referrals": "Referidos activos mínimos", "weekly_salary": "Sueldo semanal (moneda base)"}


class WheelConfigForm(ControlModelForm):
    class Meta:
        model = WheelConfig
        fields = ["enabled", "title", "subtitle", "spins_per_day", "cooldown_minutes", "require_active_membership", "terms"]
        labels = {
            "enabled": "Ruleta habilitada", "title": "Título", "subtitle": "Subtítulo",
            "spins_per_day": "Giros gratuitos por usuario/día", "cooldown_minutes": "Espera entre giros (minutos)",
            "require_active_membership": "Exigir membresía activa", "terms": "Términos de la promoción",
        }


class WheelPrizeForm(ControlModelForm):
    class Meta:
        model = WheelPrize
        fields = ["name", "reward_type", "value", "weight", "icon", "color", "daily_global_limit", "total_stock", "active", "sort_order"]
        labels = {
            "name": "Nombre del premio", "reward_type": "Tipo de premio", "value": "Valor",
            "weight": "Peso / frecuencia relativa", "icon": "Icono", "color": "Color",
            "daily_global_limit": "Máximo global por día (0 = ilimitado)",
            "total_stock": "Stock total (0 = ilimitado)", "active": "Premio activo", "sort_order": "Orden visual",
        }
        help_texts = {"weight": "Es un peso relativo, no un porcentaje exacto. El servidor selecciona el premio y registra el resultado."}
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class GiftCodeForm(ControlModelForm):
    class Meta:
        model = GiftCode
        fields = ["code", "name", "description", "reward_type", "value", "max_redemptions", "per_user_limit", "valid_from", "valid_until", "require_active_membership", "required_plan", "active"]
        labels = {
            "code": "Código", "name": "Nombre de campaña", "description": "Descripción",
            "reward_type": "Tipo de regalo", "value": "Valor", "max_redemptions": "Usos/personas totales (0 = ilimitado)",
            "per_user_limit": "Usos máximos por usuario", "valid_from": "Disponible desde", "valid_until": "Vence el",
            "require_active_membership": "Exigir membresía activa", "required_plan": "Limitar a un plan", "active": "Código activo",
        }
        widgets = {
            "valid_from": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "valid_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class BalanceAdjustmentForm(forms.Form):
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), label="Monto (moneda base)")
    direction = forms.ChoiceField(choices=[("credit", "Acreditar"), ("debit", "Debitar")], label="Operación")
    reason = forms.CharField(max_length=180, label="Motivo de auditoría")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "control-input")
        self.fields["amount"].widget.attrs["placeholder"] = "Ej. 500.00"
        self.fields["reason"].widget.attrs["placeholder"] = "Ej. Corrección documentada de saldo"


class ManualMembershipForm(forms.Form):
    plan = forms.ModelChoiceField(queryset=MembershipPlan.objects.filter(active=True), label="Plan")
    days = forms.IntegerField(min_value=1, max_value=366, required=False, label="Días (vacío = duración del plan)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "control-input")
        self.fields["days"].widget.attrs["placeholder"] = "Ej. 30"


class UserBlockForm(forms.Form):
    reason = forms.CharField(max_length=240, required=True, label="Motivo del bloqueo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].widget.attrs.update({"class": "control-input", "placeholder": "Describe la razón; quedará en auditoría"})


class AdminUserCreateForm(forms.Form):
    first_name = forms.CharField(max_length=80, label="Nombre")
    last_name = forms.CharField(max_length=80, required=False, label="Apellido")
    country = forms.ChoiceField(choices=COUNTRY_CHOICES, initial="NI", label="País / territorio")
    email = forms.EmailField(label="Correo", required=False)
    telefono = forms.CharField(max_length=32, required=False, label="Teléfono")
    referral_code = forms.CharField(max_length=16, required=False, label="Código de referidor")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Contraseña temporal")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirmar contraseña")
    is_staff = forms.BooleanField(required=False, label="Acceso a HBL Control")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "first_name": "Ej. Víctor", "last_name": "Ej. Pavón", "email": "correo@ejemplo.com",
            "telefono": "+50588888888", "referral_code": "Opcional", "password1": "Contraseña segura",
            "password2": "Repite la contraseña",
        }
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "control-input")
                if name in placeholders:
                    field.widget.attrs.setdefault("placeholder", placeholders[name])

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip().lower() or None
        if value and User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("Ese correo ya existe.")
        return value

    def clean(self):
        cleaned = super().clean()
        country = cleaned.get("country") or "NI"
        phone = cleaned.get("telefono")
        if phone:
            try:
                phone = normalize_phone(phone, country)
            except forms.ValidationError as exc:
                self.add_error("telefono", exc)
            else:
                if User.objects.filter(telefono=phone).exists():
                    self.add_error("telefono", "Ese teléfono ya existe.")
                cleaned["telefono"] = phone
        if not cleaned.get("email") and not cleaned.get("telefono"):
            raise forms.ValidationError("Debes indicar correo o teléfono.")
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        if p1:
            try:
                validate_password(p1)
            except ValidationError as exc:
                self.add_error("password1", exc)
        code = (cleaned.get("referral_code") or "").strip().upper()
        if code and not User.objects.filter(codigo_invitacion=code, is_active=True).exists():
            self.add_error("referral_code", "Código de referidor inválido.")
        cleaned["referral_code"] = code
        return cleaned
