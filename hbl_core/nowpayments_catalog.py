"""Sincronización y presentación del catálogo de criptomonedas NOWPayments."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from .models import CurrencyRate, PaymentMethod, PlatformConfig
from .nowpayments import NowPaymentsClient, NowPaymentsError
from .payment_policies import GLOBAL_MIN_DEPOSIT_USDT

logger = logging.getLogger(__name__)

CATALOG_CACHE_KEY = "hbl:nowpayments:merchant-coins:v6"
CATALOG_CACHE_SECONDS = 3600
CRYPTO_KINDS = [
    PaymentMethod.Kind.USDT_TRC20,
    PaymentMethod.Kind.USDT_BEP20,
    PaymentMethod.Kind.CRYPTO_OTHER,
]

# HBL solo ofrece estas monedas al usuario. Los métodos antiguos de otros
# tokens se conservan en la base por historial, pero quedan desactivados.
ALLOWED_PAYMENT_SYMBOLS = (
    "BTC",
    "ETH",
    "USDT",
    "USDC",
    "BNB",
    "SOL",
    "TRX",
    "DOGE",
    "LTC",
    "ADA",
    "XRP",
)
ALLOWED_PAYMENT_SYMBOL_SET = frozenset(ALLOWED_PAYMENT_SYMBOLS)

# Se conserva un glifo únicamente como último fallback accesible. La interfaz
# principal usa logos reales por ticker mediante assets.coincap.io.
ICON_MAP = {
    "BTC": "₿", "ETH": "Ξ", "USDT": "₮", "USDC": "$", "BNB": "B",
    "SOL": "S", "TRX": "T", "LTC": "Ł", "DOGE": "Ð", "ADA": "A",
    "XRP": "X",
}

NAME_MAP = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "USDT": "Tether", "USDC": "USD Coin",
    "BNB": "BNB", "SOL": "Solana", "TRX": "TRON", "LTC": "Litecoin",
    "DOGE": "Dogecoin", "ADA": "Cardano", "XRP": "XRP",
}

POPULAR_CODE_PRIORITY = {
    "usdttrc20": 0,
    "usdtbsc": 1,
    "usdtbep20": 2,
    "usdterc20": 3,
    "btc": 10,
    "eth": 20,
    "bnbbsc": 30,
    "bnb": 31,
    "sol": 40,
    "usdcerc20": 50,
    "usdcbsc": 51,
    "usdcsol": 52,
    "usdc": 53,
    "trx": 60,
    "doge": 70,
    "ltc": 80,
    "ada": 90,
    "xrp": 100,
}
POPULAR_SYMBOL_PRIORITY = {
    "USDT": 0,
    "BTC": 10,
    "ETH": 20,
    "BNB": 30,
    "SOL": 40,
    "USDC": 50,
    "TRX": 60,
    "DOGE": 70,
    "LTC": 80,
    "ADA": 90,
    "XRP": 100,
}

NETWORK_SUFFIXES = (
    ("trc20", "TRON (TRC20)"),
    ("erc20", "Ethereum (ERC20)"),
    ("arc20", "ARC20"),
    ("bep20", "BNB Smart Chain (BEP20)"),
    ("bep2", "BNB Beacon Chain (BEP2)"),
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


def _priority_for(code: str, symbol: str) -> int:
    if code in POPULAR_CODE_PRIORITY:
        return POPULAR_CODE_PRIORITY[code]
    if symbol in POPULAR_SYMBOL_PRIORITY:
        return POPULAR_SYMBOL_PRIORITY[symbol] + 5
    return 1000


def _logo_url(symbol: str) -> str:
    safe = re.sub(r"[^a-z0-9]", "", str(symbol or "").lower())[:16]
    return f"https://assets.coincap.io/assets/icons/{safe}@2x.png" if safe else ""


def describe_provider_code(code: str) -> dict:
    """Convierte un código NOWPayments en ticker, red, etiqueta y logo."""
    raw = _clean_code(code)
    if not raw:
        return {
            "code": "", "symbol": "CRYPTO", "network": "NOWPayments",
            "label": "Criptomoneda", "icon": "•", "logo_url": "", "priority": 1000,
        }

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
    icon = ICON_MAP.get(symbol, "•")
    return {
        "code": raw,
        "symbol": symbol,
        "network": network,
        "label": label,
        "icon": icon,
        "logo_url": _logo_url(symbol),
        "priority": _priority_for(raw, symbol),
    }


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


def _filter_allowed_codes(codes: list[str]) -> list[str]:
    """Conserva solo las 11 monedas aprobadas y evita redes duplicadas."""
    best_by_route: dict[tuple[str, str], tuple[tuple[int, str], str]] = {}
    for code in codes:
        meta = describe_provider_code(code)
        symbol = meta["symbol"]
        if symbol not in ALLOWED_PAYMENT_SYMBOL_SET:
            continue
        route = (symbol, meta["network"])
        score = (int(meta["priority"]), code)
        current = best_by_route.get(route)
        if current is None or score < current[0]:
            best_by_route[route] = (score, code)

    selected = [entry[1] for entry in best_by_route.values()]
    selected.sort(
        key=lambda code: (
            int(describe_provider_code(code)["priority"]),
            describe_provider_code(code)["symbol"],
            describe_provider_code(code)["network"],
            code,
        )
    )
    return selected


def _deactivate_disallowed_existing() -> None:
    PaymentMethod.objects.filter(kind__in=CRYPTO_KINDS).exclude(
        currency__in=ALLOWED_PAYMENT_SYMBOLS,
    ).update(active=False)
    PaymentMethod.objects.filter(
        kind__in=CRYPTO_KINDS,
        currency__in=ALLOWED_PAYMENT_SYMBOLS,
    ).update(min_amount=GLOBAL_MIN_DEPOSIT_USDT)


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
    return PaymentMethod.objects.filter(
        active=True,
        kind__in=CRYPTO_KINDS,
        currency__in=ALLOWED_PAYMENT_SYMBOLS,
    ).count()


def _apply_method_values(method: PaymentMethod, *, code: str, index: int, min_credit: Decimal, rate: Decimal):
    meta = describe_provider_code(code)
    method.kind = _kind_for(code)
    method.label = meta["label"]
    method.currency = meta["symbol"]
    method.network = meta["network"]
    method.destination = code
    method.instructions = (
        f"Paga con {meta['symbol']} por {meta['network']}. "
        "Mínimo a acreditar: 10 USDT. NOWPayments generará la dirección, el monto exacto y cualquier memo/tag requerido."
    )
    method.min_amount = GLOBAL_MIN_DEPOSIT_USDT
    method.max_amount = Decimal("0")
    method.require_proof = False
    method.require_txid = False
    method.balance_rate = rate
    method.sender_network_fee_estimate = Decimal("0")
    method.active = True
    priority = int(meta["priority"])
    method.sort_order = priority if priority < 1000 else 1000 + index
    return method


def sync_nowpayments_methods(*, force: bool = False, client: NowPaymentsClient | None = None) -> int:
    """Sincroniza únicamente las monedas populares permitidas por HBL."""
    _deactivate_disallowed_existing()

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

    codes = _filter_allowed_codes(codes)
    if not codes:
        logger.warning("NOWPayments no devolvió ninguna de las monedas permitidas por HBL")
        return _active_count()

    config = PlatformConfig.get_solo()
    min_credit = GLOBAL_MIN_DEPOSIT_USDT
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
    method.ui_logo_url = meta["logo_url"]
    method.ui_symbol = meta["symbol"]
    method.ui_network = method.network or meta["network"]
    method.ui_provider_code = meta["code"]
    method.ui_priority = meta["priority"]
    return method
