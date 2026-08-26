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

CATALOG_CACHE_KEY = "hbl:nowpayments:merchant-coins:v3"
CATALOG_CACHE_SECONDS = 3600
CRYPTO_KINDS = [
    PaymentMethod.Kind.USDT_TRC20,
    PaymentMethod.Kind.USDT_BEP20,
    PaymentMethod.Kind.CRYPTO_OTHER,
]

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
            if item.get("enabled") is False:
                continue
        else:
            code = ""
        if code and code not in codes:
            codes.append(code)
    return codes


def _usdt_rate(config: PlatformConfig) -> Decimal:
    rows = {
        row.code: row
        for row in CurrencyRate.objects.filter(code__in=["USDT", "USD"], active=True)
    }
    usdt = rows.get("USDT")
    if usdt and Decimal(usdt.rate_to_base or 0) > 0:
        return Decimal(usdt.rate_to_base)
    usd = rows.get("USD")
    if usd and Decimal(usd.rate_to_base or 0) > 0:
        return Decimal(usd.rate_to_base)
    return Decimal(config.exchange_rate_usd_nio)


def _kind_for(code: str):
    if code == "usdttrc20":
        return PaymentMethod.Kind.USDT_TRC20
    if code in {"usdtbsc", "usdtbep20"}:
        return PaymentMethod.Kind.USDT_BEP20
    return PaymentMethod.Kind.CRYPTO_OTHER


def _active_count() -> int:
    return PaymentMethod.objects.filter(active=True, kind__in=CRYPTO_KINDS).count()


def _apply_method_values(method: PaymentMethod, *, code: str, index: int, min_credit: Decimal, rate: Decimal):
    meta = describe_provider_code(code)
    method.kind = _kind_for(code)
    method.label = meta["label"]
    method.currency = meta["symbol"]
    method.network = meta["network"]
    method.destination = code
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
    return method


def sync_nowpayments_methods(*, force: bool = False, client: NowPaymentsClient | None = None) -> int:
    """Sincroniza el catálogo NOWPayments con pocas consultas a la base de datos.

    Antes se hacía un ``SELECT`` y un ``SAVE`` por cada criptomoneda. Con cientos
    de monedas y una base remota eso podía bloquear un worker de Gunicorn hasta
    superar su timeout. Ahora se precargan los métodos y se persisten por lotes.
    """
    if not settings.NOWPAYMENTS_API_KEY:
        return 0
    if settings.DEBUG and not force:
        return _active_count()
    if not force and cache.get(CATALOG_CACHE_KEY):
        return _active_count()

    client = client or NowPaymentsClient()
    codes = []
    try:
        codes = _extract_codes(client.get_merchant_currencies())
    except NowPaymentsError as exc:
        logger.warning("merchant/coins no disponible; se intentará /currencies: %s", exc)

    if not codes:
        try:
            codes = _extract_codes(client.get_available_currencies())
        except NowPaymentsError:
            logger.exception("No se pudo sincronizar el catálogo NOWPayments")
            return _active_count()

    if not codes:
        return _active_count()

    config = PlatformConfig.get_solo()
    min_credit = (
        Decimal(settings.NOWPAYMENTS_TEST_MIN_USDT)
        if settings.NOWPAYMENTS_TEST_MODE
        else Decimal(config.minimum_deposit_usd)
    )
    rate = _usdt_rate(config)

    existing = list(PaymentMethod.objects.filter(kind__in=CRYPTO_KINDS).order_by("id"))
    by_destination = {}
    base_by_kind = {}
    for method in existing:
        destination = _clean_code(method.destination)
        if destination and destination not in by_destination:
            by_destination[destination] = method
        base_by_kind.setdefault(method.kind, method)

    used_ids = set()
    to_update = []
    to_create = []

    for index, code in enumerate(codes):
        kind = _kind_for(code)
        method = by_destination.get(code)
        if method is None and kind in {PaymentMethod.Kind.USDT_TRC20, PaymentMethod.Kind.USDT_BEP20}:
            candidate = base_by_kind.get(kind)
            if candidate is not None and candidate.pk not in used_ids:
                method = candidate

        if method is None:
            method = PaymentMethod(kind=kind)
            _apply_method_values(method, code=code, index=index, min_credit=min_credit, rate=rate)
            to_create.append(method)
        else:
            used_ids.add(method.pk)
            _apply_method_values(method, code=code, index=index, min_credit=min_credit, rate=rate)
            to_update.append(method)

    # Una sola desactivación evita que queden métodos antiguos visibles. Después
    # bulk_update reactiva únicamente los existentes que siguen en el catálogo.
    PaymentMethod.objects.filter(kind__in=CRYPTO_KINDS).update(active=False)

    update_fields = [
        "kind", "label", "currency", "network", "destination", "instructions",
        "min_amount", "max_amount", "require_proof", "require_txid", "balance_rate",
        "sender_network_fee_estimate", "active", "sort_order",
    ]
    if to_update:
        PaymentMethod.objects.bulk_update(to_update, update_fields, batch_size=250)
    if to_create:
        PaymentMethod.objects.bulk_create(to_create, batch_size=250)

    cache.set(CATALOG_CACHE_KEY, True, CATALOG_CACHE_SECONDS)
    return len(codes)


def decorate_method(method: PaymentMethod):
    """Añade atributos efímeros para la UI sin exigir una migración de iconos."""
    meta = describe_provider_code(method.destination or method.currency)
    method.ui_icon = meta["icon"]
    method.ui_symbol = meta["symbol"]
    method.ui_network = method.network or meta["network"]
    method.ui_provider_code = meta["code"]
    return method
