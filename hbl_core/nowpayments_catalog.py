"""Sincronización y presentación del catálogo de criptomonedas NOWPayments."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from .models import CurrencyRate, PaymentMethod, PlatformConfig
from .nowpayments import NowPaymentsClient, NowPaymentsError

logger = logging.getLogger(__name__)

CATALOG_CACHE_KEY = "hbl:nowpayments:merchant-coins:v2"
CATALOG_CACHE_SECONDS = 600

# Iconos ligeros sin depender de CDNs externos. Para cualquier moneda no
# listada, la UI genera una insignia con la primera letra del ticker.
ICON_MAP = {
    "BTC": "₿", "ETH": "Ξ", "USDT": "₮", "USDC": "◉", "BNB": "◆",
    "SOL": "◎", "TRX": "♦", "LTC": "Ł", "DOGE": "Ð", "ADA": "₳",
    "XRP": "✕", "XMR": "ɱ", "DOT": "●", "BCH": "₿", "TON": "◇",
    "SHIB": "🐕", "DAI": "◈", "MATIC": "⬡", "POL": "⬡", "AVAX": "▲",
    "ARB": "A", "OP": "O", "ETC": "Ξ", "XLM": "✦", "ATOM": "⚛",
    "NEAR": "N", "APT": "A", "SUI": "S", "FIL": "F", "ALGO": "A",
}

NAME_MAP = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "USDT": "Tether", "USDC": "USD Coin",
    "BNB": "BNB", "SOL": "Solana", "TRX": "TRON", "LTC": "Litecoin",
    "DOGE": "Dogecoin", "ADA": "Cardano", "XRP": "XRP", "XMR": "Monero",
    "DOT": "Polkadot", "BCH": "Bitcoin Cash", "TON": "Toncoin", "SHIB": "Shiba Inu",
    "DAI": "DAI", "MATIC": "Polygon", "POL": "Polygon", "AVAX": "Avalanche",
    "XLM": "Stellar", "ATOM": "Cosmos", "NEAR": "NEAR", "ETC": "Ethereum Classic",
}

# Los códigos de NOWPayments suelen combinar activo + red, por ejemplo
# usdttrc20, usdterc20, usdtbsc. Se prueban primero los sufijos largos.
NETWORK_SUFFIXES = (
    ("trc20", "TRON (TRC20)"),
    ("erc20", "Ethereum (ERC20)"),
    ("bep20", "BNB Smart Chain (BEP20)"),
    ("bsc", "BNB Smart Chain (BEP20)"),
    ("polygon", "Polygon"),
    ("matic", "Polygon"),
    ("arbitrum", "Arbitrum"),
    ("arb", "Arbitrum"),
    ("optimism", "Optimism"),
    ("avaxc", "Avalanche C-Chain"),
    ("sol", "Solana"),
    ("ton", "TON"),
    ("base", "Base"),
)

SPECIAL_CODES = {
    "usdttrc20": ("USDT", "TRON (TRC20)"),
    "usdtbsc": ("USDT", "BNB Smart Chain (BEP20)"),
    "usdtbep20": ("USDT", "BNB Smart Chain (BEP20)"),
    "usdterc20": ("USDT", "Ethereum (ERC20)"),
    "usdtsol": ("USDT", "Solana"),
    "usdcerc20": ("USDC", "Ethereum (ERC20)"),
    "usdcbsc": ("USDC", "BNB Smart Chain (BEP20)"),
    "usdcsol": ("USDC", "Solana"),
}


def _clean_code(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())[:48]


def describe_provider_code(code: str) -> dict:
    """Convierte un código NOWPayments en ticker, red, etiqueta e icono."""
    raw = _clean_code(code)
    if not raw:
        return {"code": "", "symbol": "CRYPTO", "network": "NOWPayments", "label": "Criptomoneda", "icon": "◈"}

    if raw in SPECIAL_CODES:
        symbol, network = SPECIAL_CODES[raw]
    else:
        symbol = raw.upper()
        network = "Red principal"
        for suffix, network_label in NETWORK_SUFFIXES:
            if raw.endswith(suffix) and len(raw) > len(suffix):
                candidate = raw[:-len(suffix)].upper()
                if candidate:
                    symbol = candidate
                    network = network_label
                    break

    # Evita superar el max_length existente de PaymentMethod.currency.
    symbol = symbol[:12] or raw[:12].upper()
    name = NAME_MAP.get(symbol, symbol)
    label = f"{name} · {network}" if network != "Red principal" else name
    icon = ICON_MAP.get(symbol, symbol[:1] or "◈")
    return {"code": raw, "symbol": symbol, "network": network, "label": label, "icon": icon}


def _extract_codes(payload) -> list[str]:
    """Tolera las variantes de respuesta conocidas de merchant/coins y currencies."""
    values = []
    if isinstance(payload, dict):
        for key in ("selectedCurrencies", "currencies", "coins", "data", "result"):
            candidate = payload.get(key)
            if isinstance(candidate, (list, tuple)):
                values = list(candidate)
                break
        if not values and all(isinstance(k, str) for k in payload.keys()):
            # Algunas respuestas pueden usar el ticker como clave.
            values = [k for k, v in payload.items() if v not in (False, None, 0, "")]
    elif isinstance(payload, (list, tuple)):
        values = list(payload)

    codes = []
    for item in values:
        if isinstance(item, str):
            code = _clean_code(item)
        elif isinstance(item, dict):
            code = _clean_code(
                item.get("code") or item.get("currency") or item.get("ticker")
                or item.get("symbol") or item.get("name")
            )
            enabled = item.get("enabled")
            if enabled is False:
                continue
        else:
            code = ""
        if code and code not in codes:
            codes.append(code)
    return codes


def _usdt_rate(config: PlatformConfig) -> Decimal:
    row = CurrencyRate.objects.filter(code="USDT", active=True).first()
    if row and Decimal(row.rate_to_base or 0) > 0:
        return Decimal(row.rate_to_base)
    usd = CurrencyRate.objects.filter(code="USD", active=True).first()
    if usd and Decimal(usd.rate_to_base or 0) > 0:
        return Decimal(usd.rate_to_base)
    return Decimal(config.exchange_rate_usd_nio)


def _kind_for(code: str):
    if code == "usdttrc20":
        return PaymentMethod.Kind.USDT_TRC20
    if code in {"usdtbsc", "usdtbep20"}:
        return PaymentMethod.Kind.USDT_BEP20
    return PaymentMethod.Kind.CRYPTO_OTHER


def sync_nowpayments_methods(*, force: bool = False, client: NowPaymentsClient | None = None) -> int:
    """Sincroniza en BD todas las monedas activas de la cuenta NOWPayments.

    Se consulta primero ``/merchant/coins`` porque representa lo que realmente
    puede usar esta cuenta. Si no devuelve una lista utilizable, se intenta el
    catálogo general ``/currencies``. Un fallo del proveedor nunca borra el
    catálogo que ya estaba funcionando.
    """
    if not settings.NOWPAYMENTS_API_KEY:
        return 0
    if not force and cache.get(CATALOG_CACHE_KEY):
        return PaymentMethod.objects.filter(
            active=True,
            kind__in=[PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20, PaymentMethod.Kind.CRYPTO_OTHER],
        ).count()

    client = client or NowPaymentsClient()
    try:
        payload = client.get_merchant_currencies()
        codes = _extract_codes(payload)
        if not codes:
            codes = _extract_codes(client.get_available_currencies())
    except NowPaymentsError:
        logger.exception("No se pudo sincronizar el catálogo NOWPayments")
        return 0

    if not codes:
        return 0

    config = PlatformConfig.get_solo()
    min_credit = (
        Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
        if settings.NOWPAYMENTS_TEST_MODE
        else Decimal(config.minimum_deposit_usd)
    )
    rate = _usdt_rate(config)
    keep_ids = []

    for index, code in enumerate(codes):
        meta = describe_provider_code(code)
        kind = _kind_for(code)
        method = PaymentMethod.objects.filter(
            kind__in=[PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20, PaymentMethod.Kind.CRYPTO_OTHER],
            destination=code,
        ).first()
        if not method and kind in {PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20}:
            # Reutiliza las filas históricas TRC20/BEP20 para no duplicarlas.
            method = PaymentMethod.objects.filter(kind=kind).order_by("id").first()
        if not method:
            method = PaymentMethod(kind=kind)

        method.label = meta["label"]
        method.currency = meta["symbol"]
        method.network = meta["network"]
        method.destination = code  # Código exacto de pay_currency en NOWPayments.
        method.instructions = (
            f"Paga con {meta['symbol']} por {meta['network']}. "
            "NOWPayments generará la dirección, el monto exacto y cualquier memo/tag requerido."
        )
        method.min_amount = min_credit
        method.max_amount = Decimal("0")
        method.require_proof = False
        method.require_txid = False
        method.balance_rate = rate
        method.sender_network_fee_estimate = Decimal("0")
        method.active = True
        method.sort_order = 10 + index
        method.save()
        keep_ids.append(method.pk)

    # Solo desactiva métodos automáticos NOWPayments que ya no aparezcan en el
    # catálogo válido. Los métodos manuales ajenos a NOWPayments no se tocan.
    PaymentMethod.objects.filter(
        kind__in=[PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20, PaymentMethod.Kind.CRYPTO_OTHER],
    ).exclude(pk__in=keep_ids).update(active=False)

    cache.set(CATALOG_CACHE_KEY, True, CATALOG_CACHE_SECONDS)
    return len(keep_ids)


def decorate_method(method: PaymentMethod):
    """Añade atributos efímeros para la UI sin exigir una migración de iconos."""
    meta = describe_provider_code(method.destination or method.currency)
    method.ui_icon = meta["icon"]
    method.ui_symbol = meta["symbol"]
    method.ui_network = method.network or meta["network"]
    method.ui_provider_code = meta["code"]
    return method
