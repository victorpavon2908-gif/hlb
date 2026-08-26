from decimal import Decimal

from django import forms

from .models import PaymentMethod
from .payment_policies import CRYPTO_DEPOSIT_KINDS, GLOBAL_MIN_DEPOSIT_USDT


class CryptoDepositForm(forms.Form):
    payment_method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.none(),
        label="Criptomoneda y red",
    )
    payment_amount = forms.DecimalField(
        label="Monto que deseas acreditar (USDT)",
        min_value=GLOBAL_MIN_DEPOSIT_USDT,
        max_digits=18,
        decimal_places=8,
        error_messages={
            "min_value": "El depósito mínimo global es 10 USDT.",
        },
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
            "placeholder": "Mínimo 10.00 USDT",
            "autocomplete": "off",
            "inputmode": "decimal",
            "min": "10",
            "step": "0.00000001",
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

        # Regla única para todos: el mínimo siempre es 10 USDT, incluso en
        # modo de prueba y aunque un método antiguo conserve otro mínimo.
        if Decimal(amount) < GLOBAL_MIN_DEPOSIT_USDT:
            self.add_error(
                "payment_amount",
                "El depósito mínimo global es 10 USDT.",
            )
        if method.max_amount and Decimal(method.max_amount) > 0 and Decimal(amount) > Decimal(method.max_amount):
            self.add_error(
                "payment_amount",
                f"El máximo que puedes acreditar con este método es {method.max_amount} USDT.",
            )
        return cleaned
