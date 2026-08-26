"""Reglas únicas para los canales financieros habilitados en HBL."""

from decimal import Decimal, ROUND_HALF_UP
import re


# NOWPayments puede exponer cientos de activos/redes. Los dos kinds USDT se
# conservan por compatibilidad y el resto se sincroniza como crypto_other.
CRYPTO_DEPOSIT_KINDS = ("usdt_trc20", "usdt_bep20", "crypto_other")
CRYPTO_WITHDRAWAL_SLUGS = ("usdt-trc20", "usdt-bep20")
CRYPTO_WITHDRAWAL_IDENTIFIER_TYPES = ("trc20", "bep20")

# Regla comercial HBL: cada depósito/retiro lleva un cargo fijo equivalente a
# 1 USDT. En depósitos el usuario acredita el monto solicitado y paga 1 USDT
# adicional, aunque elija pagar con BTC, ETH u otra criptomoneda. En retiros,
# la interfaz suma este cargo al total reservado para que el usuario reciba el
# monto neto que indicó.
USDT_OPERATION_FEE = Decimal("1.00000000")
USDT_QUANT = Decimal("0.00000001")


def usdt_total_with_fee(amount):
    """Devuelve el total comercial en USDT después de sumar el cargo fijo."""
    value = Decimal(amount or 0)
    return (value + USDT_OPERATION_FEE).quantize(USDT_QUANT, rounding=ROUND_HALF_UP)


def usdt_fee_from_total(total, credited_amount):
    """Calcula cuánto del total está por encima del monto acreditado/solicitado."""
    total = Decimal(total or 0)
    credited_amount = Decimal(credited_amount or 0)
    return max(total - credited_amount, Decimal("0")).quantize(USDT_QUANT, rounding=ROUND_HALF_UP)


def detect_usdt_withdrawal_network(address):
    """Detecta la red por el formato de una dirección pública USDT."""
    value = (address or "").strip()
    if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", value):
        return "usdt-trc20"
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
        return "usdt-bep20"
    return ""
