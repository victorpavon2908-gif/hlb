from decimal import Decimal

from django import forms
from django.conf import settings

from .models import PaymentMethod, PlatformConfig
from .payment_policies import CRYPTO_DEPOSIT_KINDS


class CryptoDepositForm(forms.Form):
    payment_method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.none(),
        label="Criptomoneda y red",
    )
    payment_amount = forms.DecimalField(
        label="Monto que deseas acreditar (USDT)",
        min_value=Decimal("0.00000001"),
        max_digits=18,
        decimal_places=8,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
            active=True,
            kind__in=CRYPTO_DEPOSIT_KINDS,
        ).order_by("sort_order", "label")
        self.fields["payment_method"].widget.attrs.update({
            "class": "hbl-input crypto-native-select",
            "data-crypto-native-select": "1",
        })
        self.fields["payment_amount"].widget.attrs.update({
            "class": "hbl-input",
            "placeholder": "Ej. 10.00",
            "autocomplete": "off",
            "inputmode": "decimal",
        })

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("payment_method")
        amount = cleaned.get("payment_amount")
        if not method or amount is None:
            return cleaned

        if method.kind not in CRYPTO_DEPOSIT_KINDS:
            self.add_error("payment_method", "Selecciona una criptomoneda disponible en NOWPayments.")
            return cleaned

        config = PlatformConfig.get_solo()
        global_min_usdt = (
            Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
            if settings.NOWPAYMENTS_TEST_MODE
            else Decimal(config.minimum_deposit_usd)
        )
        method_min = max(Decimal(method.min_amount or 0), global_min_usdt)
        if Decimal(amount) < method_min:
            self.add_error(
                "payment_amount",
                f"El mínimo que puedes acreditar con este método es {method_min} USDT.",
            )
        if method.max_amount and Decimal(method.max_amount) > 0 and Decimal(amount) > Decimal(method.max_amount):
            self.add_error(
                "payment_amount",
                f"El máximo que puedes acreditar con este método es {method.max_amount} USDT.",
            )
        return cleaned
