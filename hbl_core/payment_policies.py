"""Reglas únicas para los canales financieros habilitados en HBL."""

import re


CRYPTO_DEPOSIT_KINDS = ("usdt_trc20", "usdt_bep20")
CRYPTO_WITHDRAWAL_SLUGS = ("usdt-trc20", "usdt-bep20")
CRYPTO_WITHDRAWAL_IDENTIFIER_TYPES = ("trc20", "bep20")


def detect_usdt_withdrawal_network(address):
    """Detecta la red por el formato de una dirección pública USDT."""
    value = (address or "").strip()
    if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", value):
        return "usdt-trc20"
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
        return "usdt-bep20"
    return ""
