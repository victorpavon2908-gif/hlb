import re

from django import forms

from .forms import WithdrawalForm
from .models import PayoutAccount, WithdrawalMethod
from .payment_policies import CRYPTO_WITHDRAWAL_SLUGS


NETWORK_CHOICES = (
    ("usdt-trc20", "USDT · TRC20 — Red TRON"),
    ("usdt-bep20", "USDT · BEP20 — BNB Smart Chain"),
)


class PayoutAccountNetworkForm(forms.ModelForm):
    """Formulario de wallet donde el usuario elige la red antes de pegar la dirección."""

    network = forms.ChoiceField(
        label="Red de la wallet",
        choices=NETWORK_CHOICES,
        widget=forms.RadioSelect,
        required=True,
    )
    label = forms.CharField(
        label="Nombre de la wallet",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "hbl-input",
            "placeholder": "Ej. Mi Binance o Wallet principal",
            "autocomplete": "off",
        }),
    )
    confirm_network = forms.BooleanField(
        label="Confirmo que la dirección pertenece a la red seleccionada",
        required=True,
    )

    class Meta:
        model = PayoutAccount
        fields = ["label", "identifier", "is_default"]
        labels = {
            "identifier": "Dirección USDT",
            "is_default": "Usar como predeterminada",
        }
        widgets = {
            "identifier": forms.TextInput(attrs={
                "class": "hbl-input",
                "placeholder": "Primero selecciona TRC20 o BEP20",
                "autocomplete": "off",
                "spellcheck": "false",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["identifier"].help_text = (
            "TRC20 normalmente comienza con T. BEP20 usa una dirección 0x de BNB Smart Chain."
        )

    def clean(self):
        cleaned = super().clean()
        slug = cleaned.get("network")
        identifier = (cleaned.get("identifier") or "").strip()

        if not slug or slug not in CRYPTO_WITHDRAWAL_SLUGS:
            self.add_error("network", "Selecciona TRC20 o BEP20.")
            return cleaned

        method = WithdrawalMethod.objects.filter(slug=slug, active=True).first()
        if not method:
            self.add_error("network", "La red seleccionada no está disponible temporalmente.")
            return cleaned

        if slug == "usdt-trc20":
            if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", identifier):
                self.add_error(
                    "identifier",
                    "Seleccionaste TRC20. Pega una dirección TRON válida que comience con T y tenga 34 caracteres.",
                )
        elif slug == "usdt-bep20":
            if not re.fullmatch(r"0x[a-fA-F0-9]{40}", identifier):
                self.add_error(
                    "identifier",
                    "Seleccionaste BEP20. Pega una dirección BNB Smart Chain válida que comience con 0x.",
                )

        if self.user and identifier and PayoutAccount.objects.filter(
            user=self.user,
            identifier__iexact=identifier,
            withdrawal_method=method,
            active=True,
        ).exists():
            self.add_error("identifier", "Ya tienes guardada esta dirección para esa red.")

        cleaned["identifier"] = identifier
        cleaned["withdrawal_method"] = method
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
        obj.holder_name = ""
        if not obj.label:
            obj.label = "Wallet TRC20" if method.slug == "usdt-trc20" else "Wallet BEP20"
        if commit:
            obj.save()
        return obj


class WithdrawalUSDTForm(WithdrawalForm):
    """Muestra la red claramente junto a cada wallet guardada."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)

        def wallet_label(obj):
            short_network = "TRC20" if obj.withdrawal_method.slug == "usdt-trc20" else "BEP20"
            return f"{obj.label} · {short_network} · {obj.masked_identifier}"

        self.fields["payout_account"].label = "Wallet de destino"
        self.fields["payout_account"].label_from_instance = wallet_label
