import re
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts.calling_codes import CALLING_CODES
from accounts.countries import COUNTRY_CHOICES
from accounts.currencies import CURRENCY_CHOICES
from .models import CurrencyRate, PaymentMethod, PayoutAccount, PlatformConfig, WithdrawalMethod
from .payment_policies import (
    CRYPTO_DEPOSIT_KINDS,
    CRYPTO_WITHDRAWAL_SLUGS,
    detect_usdt_withdrawal_network,
)

User = get_user_model()
def normalize_phone(value, country):
    value = re.sub(r"[\s().-]", "", (value or "").strip())
    if not value:
        return None
    if value.startswith("00"):
        value = "+" + value[2:]
    elif not value.startswith("+"):
        prefix = CALLING_CODES.get(country)
        if prefix:
            value = f"+{prefix}{value.lstrip('0')}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise forms.ValidationError("Usa un número válido con código internacional, por ejemplo +50588888888.")
    return value


def _field_ui(field, *, placeholder=None, autocomplete=None):
    if isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.FileInput)):
        return
    field.widget.attrs.setdefault("class", "hbl-input")
    if placeholder:
        field.widget.attrs.setdefault("placeholder", placeholder)
    if autocomplete:
        field.widget.attrs.setdefault("autocomplete", autocomplete)


def _validate_timezone(value):
    value = (value or "UTC").strip()[:64]
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return value


def validate_payout_identifier(method, value, country="NI"):
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError("Este dato es obligatorio.")
    kind = method.identifier_type
    if kind == WithdrawalMethod.IdentifierType.BINANCE_ID:
        if not re.fullmatch(r"\d{5,20}", value):
            raise forms.ValidationError("El Binance Pay ID debe contener entre 5 y 20 dígitos.")
    elif kind == WithdrawalMethod.IdentifierType.TRC20:
        if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", value):
            raise forms.ValidationError("La dirección TRC20 debe comenzar con T y tener 34 caracteres válidos.")
    elif kind == WithdrawalMethod.IdentifierType.BEP20:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
            raise forms.ValidationError("La dirección BEP20/EVM debe comenzar con 0x y contener 40 caracteres hexadecimales.")
    elif kind == WithdrawalMethod.IdentifierType.EMAIL:
        try:
            validate_email(value)
        except ValidationError as exc:
            raise forms.ValidationError("Escribe un correo electrónico válido.") from exc
    elif kind == WithdrawalMethod.IdentifierType.PHONE:
        value = normalize_phone(value, country)
    elif kind == WithdrawalMethod.IdentifierType.BANK:
        compact = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"[A-Za-z0-9]{6,34}", compact):
            raise forms.ValidationError("La cuenta/IBAN debe contener entre 6 y 34 caracteres alfanuméricos.")
    elif len(value) < 3 or len(value) > 255:
        raise forms.ValidationError("El identificador debe contener entre 3 y 255 caracteres.")
    return value


class LoginForm(forms.Form):
    identity = forms.CharField(label="Correo, teléfono o usuario", max_length=180)
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _field_ui(self.fields["identity"], placeholder="correo@ejemplo.com o +50588888888", autocomplete="username")
        _field_ui(self.fields["password"], placeholder="Tu contraseña", autocomplete="current-password")


class RegistrationForm(forms.Form):
    first_name = forms.CharField(label="Nombre", max_length=80)
    last_name = forms.CharField(label="Apellido", max_length=80, required=False)
    country = forms.ChoiceField(label="País / territorio", choices=COUNTRY_CHOICES, initial="NI")
    email = forms.EmailField(label="Correo electrónico", required=False)
    phone = forms.CharField(label="Número de teléfono", max_length=32, required=False, help_text="Puedes registrarte con teléfono, correo o ambos.")
    timezone_name = forms.CharField(required=False, widget=forms.HiddenInput, initial="UTC")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput, help_text="Usa al menos 8 caracteres y evita contraseñas comunes.")
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)
    referral_code = forms.CharField(label="Código de referido", max_length=16, required=False, help_text="Opcional. Se valida antes de crear la cuenta.")
    accept_terms = forms.BooleanField(label="Acepto los términos, políticas de recompensas y tratamiento de datos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _field_ui(self.fields["first_name"], placeholder="Ej. Víctor", autocomplete="given-name")
        _field_ui(self.fields["last_name"], placeholder="Ej. Pavón", autocomplete="family-name")
        _field_ui(self.fields["country"], autocomplete="country")
        _field_ui(self.fields["email"], placeholder="Ej. victor@email.com", autocomplete="email")
        _field_ui(self.fields["phone"], placeholder="Ej. 8888 8888", autocomplete="tel")
        _field_ui(self.fields["password1"], placeholder="Mínimo 8 caracteres", autocomplete="new-password")
        _field_ui(self.fields["password2"], placeholder="Repite tu contraseña", autocomplete="new-password")
        _field_ui(self.fields["referral_code"], placeholder="Opcional: ABCD1234")

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip().lower() or None
        if value and User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("Ese correo ya está registrado.")
        return value

    def clean_timezone_name(self):
        return _validate_timezone(self.cleaned_data.get("timezone_name"))

    def clean(self):
        cleaned = super().clean()
        country = cleaned.get("country") or "NI"
        phone = cleaned.get("phone")
        if phone:
            try:
                phone = normalize_phone(phone, country)
            except forms.ValidationError as exc:
                self.add_error("phone", exc)
            else:
                if User.objects.filter(telefono=phone).exists():
                    self.add_error("phone", "Ese teléfono ya está registrado.")
                cleaned["phone"] = phone
        if not cleaned.get("email") and not cleaned.get("phone"):
            raise forms.ValidationError("Debes registrar al menos un correo electrónico o un número de teléfono.")
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
            self.add_error("referral_code", "Código de referido no válido.")
        cleaned["referral_code"] = code
        return cleaned


class DepositForm(forms.Form):
    payment_method = forms.ModelChoiceField(queryset=PaymentMethod.objects.none(), label="Red de depósito")
    payment_amount = forms.DecimalField(label="Monto a depositar (USDT)", min_value=Decimal("0.00000001"), max_digits=18, decimal_places=8)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
            active=True, kind__in=CRYPTO_DEPOSIT_KINDS,
        )
        _field_ui(self.fields["payment_method"])
        _field_ui(self.fields["payment_amount"], placeholder="Ej. 100.00", autocomplete="off")

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("payment_method")
        amount = cleaned.get("payment_amount")
        if not method or not amount:
            return cleaned
        if method.kind not in CRYPTO_DEPOSIT_KINDS:
            self.add_error("payment_method", "Solo se aceptan depósitos USDT por TRC20 o BEP20.")
            return cleaned
        method_minimum = (
            Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
            if settings.NOWPAYMENTS_TEST_MODE
            else Decimal(method.min_amount)
        )
        if amount < method_minimum:
            self.add_error("payment_amount", f"El mínimo del método {method.label} es {method_minimum} {method.currency}.")
        if method.max_amount and method.max_amount > 0 and amount > method.max_amount:
            self.add_error("payment_amount", f"El máximo del método {method.label} es {method.max_amount} {method.currency}.")
        config = PlatformConfig.get_solo()
        base_code = config.base_currency_code.upper()
        rate_row = CurrencyRate.objects.filter(code=method.currency.upper(), active=True).first()
        if method.currency.upper() == base_code:
            rate = Decimal("1")
        elif rate_row:
            rate = Decimal(rate_row.rate_to_base)
        else:
            rate = Decimal(method.balance_rate or 0)
        if rate <= 0:
            self.add_error("payment_method", f"No hay tasa activa para {method.currency}.")
        else:
            credit_base = Decimal(amount) * rate
            usd_row = CurrencyRate.objects.filter(code="USD", active=True).first()
            usd_to_base = Decimal(usd_row.rate_to_base) if usd_row else Decimal(config.exchange_rate_usd_nio or 0)
            global_min_usdt = (
                Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
                if settings.NOWPAYMENTS_TEST_MODE
                else Decimal(config.minimum_deposit_usd)
            )
            global_min_base = global_min_usdt * usd_to_base
            if credit_base < global_min_base:
                self.add_error(
                    "payment_amount",
                    f"La recarga mínima global es US${global_min_usdt} (≈ {config.base_currency_symbol}{global_min_base.quantize(Decimal('0.01'))} {base_code}).",
                )
        return cleaned


class PayoutAccountForm(forms.ModelForm):
    class Meta:
        model = PayoutAccount
        fields = ["label", "holder_name", "identifier", "is_default"]
        labels = {
            "label": "Nombre para identificarlo",
            "holder_name": "Titular",
            "identifier": "Dirección USDT",
            "is_default": "Usar como predeterminado",
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        _field_ui(self.fields["label"], placeholder="Ej. Mi wallet principal")
        _field_ui(self.fields["holder_name"], placeholder="Nombre del titular (opcional)", autocomplete="name")
        _field_ui(self.fields["identifier"], placeholder="T... para TRC20 o 0x... para BEP20", autocomplete="off")

    def clean(self):
        cleaned = super().clean()
        identifier = (cleaned.get("identifier") or "").strip()
        if not identifier:
            return cleaned
        method_slug = detect_usdt_withdrawal_network(identifier)
        if not method_slug:
            self.add_error(
                "identifier",
                "Dirección no reconocida. Usa una dirección TRC20 que comience con T o una BEP20 que comience con 0x.",
            )
            return cleaned
        method = WithdrawalMethod.objects.filter(
            slug=method_slug, active=True,
        ).first()
        if not method:
            self.add_error("identifier", "La red detectada no está disponible temporalmente.")
            return cleaned
        cleaned["withdrawal_method"] = method
        if method.holder_required and not (cleaned.get("holder_name") or "").strip():
            self.add_error("holder_name", f"{method.name} requiere el nombre del titular.")
        if identifier:
            try:
                cleaned["identifier"] = validate_payout_identifier(
                    method, identifier, getattr(self.user, "country", "NI"),
                )
            except forms.ValidationError as exc:
                self.add_error("identifier", exc)
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        method = self.cleaned_data["withdrawal_method"]
        obj.withdrawal_method = method
        obj.kind = (
            PayoutAccount.Kind.USDT_TRC20
            if method.slug == "usdt-trc20"
            else PayoutAccount.Kind.USDT_BEP20
        )
        obj.network = method.network
        if not obj.label:
            obj.label = method.name
        if commit:
            obj.save()
        return obj


class WithdrawalForm(forms.Form):
    payout_account = forms.ModelChoiceField(queryset=PayoutAccount.objects.none(), label="Método y destino")
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=18, decimal_places=2)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        currency = (getattr(user, "country_currency", "") or PlatformConfig.get_solo().base_currency_code).upper()
        self.fields["amount"].label = f"Monto a retirar ({currency})"
        self.fields["amount"].help_text = f"Escribe el monto en {currency}. HBL mostrará y guardará la conversión a la moneda del método."
        self.fields["payout_account"].queryset = PayoutAccount.objects.filter(
            user=user,
            active=True,
            withdrawal_method__active=True,
            withdrawal_method__slug__in=CRYPTO_WITHDRAWAL_SLUGS,
        ).select_related("withdrawal_method")
        _field_ui(self.fields["payout_account"])
        _field_ui(self.fields["amount"], placeholder="Ej. 750.00", autocomplete="off")

    def clean(self):
        cleaned = super().clean()
        currency = (getattr(self.user, "country_currency", "") or PlatformConfig.get_solo().base_currency_code).upper()
        config = PlatformConfig.get_solo()
        if currency != config.base_currency_code.upper() and not CurrencyRate.objects.filter(code=currency, active=True).exists():
            self.add_error("amount", f"La tasa para {currency} aún no está activa. Administración debe configurarla antes de retirar en esa moneda.")
        account = cleaned.get("payout_account")
        if account and account.withdrawal_method:
            if account.withdrawal_method.slug not in CRYPTO_WITHDRAWAL_SLUGS:
                self.add_error("payout_account", "Solo se permiten retiros USDT por TRC20 o BEP20.")
                return cleaned
            payout_currency = account.withdrawal_method.payout_currency_for(self.user)
            if payout_currency != config.base_currency_code.upper() and not CurrencyRate.objects.filter(code=payout_currency, active=True).exists():
                self.add_error("payout_account", f"El método requiere {payout_currency}, pero esa moneda no tiene una tasa activa.")
        return cleaned


class ProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_currency"].widget = forms.Select(choices=CURRENCY_CHOICES)
        self.fields["preferred_currency"].choices = CURRENCY_CHOICES
        self.fields["preferred_currency"].label = "Moneda de visualización"
        self.fields["preferred_currency"].help_text = "Solo cambia cómo ves equivalencias. Los retiros locales usan la moneda asociada a tu país."
        for name, field in self.fields.items():
            _field_ui(field)
        self.fields["first_name"].widget.attrs["placeholder"] = "Ej. Víctor"
        self.fields["last_name"].widget.attrs["placeholder"] = "Ej. Pavón"
        self.fields["email"].widget.attrs["placeholder"] = "correo@ejemplo.com"
        self.fields["telefono"].widget.attrs["placeholder"] = "+50588888888"

    class Meta:
        model = User
        fields = ["first_name", "last_name", "country", "preferred_currency", "email", "telefono", "contact_preference"]

    def clean(self):
        cleaned = super().clean()
        country = cleaned.get("country") or self.instance.country or "NI"
        phone = cleaned.get("telefono")
        if phone:
            try:
                phone = normalize_phone(phone, country)
            except forms.ValidationError as exc:
                self.add_error("telefono", exc)
            else:
                qs = User.objects.filter(telefono=phone).exclude(pk=self.instance.pk)
                if qs.exists():
                    self.add_error("telefono", "Ese teléfono ya está registrado.")
                cleaned["telefono"] = phone
        email = (cleaned.get("email") or "").strip().lower() or None
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            self.add_error("email", "Ese correo ya está registrado.")
        cleaned["email"] = email
        if not email and not cleaned.get("telefono"):
            raise forms.ValidationError("Debes conservar al menos un correo o teléfono.")
        return cleaned


class GiftRedeemForm(forms.Form):
    code = forms.CharField(label="Código de regalo", max_length=32)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _field_ui(self.fields["code"], placeholder="Ej. HBLBIENVENIDA", autocomplete="off")

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
