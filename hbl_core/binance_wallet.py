"""Helpers for receiving USDT directly in the configured Binance account.

Only public deposit addresses are persisted/displayed. API credentials are read from
server environment variables and are never returned to templates or stored in the DB.
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode


class BinanceWalletError(Exception):
    pass


_NETWORKS = {
    "TRX": {
        "env": ("USDT_TRC20_ADDRESS", "USDT_TRC20_WALLET"),
        "pattern": re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$"),
        "label": "USDT TRC20",
    },
    "BSC": {
        "env": ("USDT_BEP20_ADDRESS", "USDT_BEP20_WALLET"),
        "pattern": re.compile(r"^0x[a-fA-F0-9]{40}$"),
        "label": "USDT BEP20",
    },
}


class BinanceWalletClient:
    """Small signed client for Binance Wallet USER_DATA endpoints."""

    def __init__(self, api_key=None, secret_key=None, host=None, timeout=12):
        self.api_key = (api_key or os.getenv("BINANCE_API_KEY", "")).strip()
        self.secret_key = (secret_key or os.getenv("BINANCE_API_SECRET", "")).strip()
        self.host = (host or os.getenv("BINANCE_API_BASE_URL", "https://api.binance.com")).strip().rstrip("/")
        self.timeout = timeout
        if not self.api_key or not self.secret_key:
            raise BinanceWalletError("BINANCE_API_KEY/BINANCE_API_SECRET no están configuradas.")

    @classmethod
    def configured(cls):
        return bool(os.getenv("BINANCE_API_KEY", "").strip() and os.getenv("BINANCE_API_SECRET", "").strip())

    def deposit_address(self, *, coin="USDT", network):
        network = (network or "").upper().strip()
        if network not in _NETWORKS:
            raise BinanceWalletError(f"Red Binance no permitida: {network or 'vacía'}.")

        params = {
            "coin": coin.upper().strip(),
            "network": network,
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000),
        }
        query = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            f"{self.host}/sapi/v1/capital/deposit/address?{query}&signature={signature}",
            method="GET",
            headers={"X-MBX-APIKEY": self.api_key, "Accept": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise BinanceWalletError(f"Binance respondió HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BinanceWalletError("No fue posible consultar la dirección de depósito en Binance.") from exc

        address = str(payload.get("address") or "").strip()
        if not address:
            raise BinanceWalletError("Binance no devolvió una dirección de depósito.")
        validate_usdt_address(network, address)
        return address


def validate_usdt_address(network, address):
    network = (network or "").upper().strip()
    spec = _NETWORKS.get(network)
    if not spec:
        raise BinanceWalletError(f"Red no permitida: {network or 'vacía'}.")
    address = (address or "").strip()
    if not spec["pattern"].fullmatch(address):
        raise BinanceWalletError(f"La dirección configurada para {spec['label']} no tiene un formato válido.")
    return address


def _static_address(network):
    spec = _NETWORKS[network]
    for env_name in spec["env"]:
        value = os.getenv(env_name, "").strip()
        if value:
            return validate_usdt_address(network, value)
    return ""


def resolve_usdt_deposit_address(network):
    """Return (address, source) for TRX or BSC.

    Preference: Binance signed API -> public address environment variable.
    """
    network = (network or "").upper().strip()
    if network not in _NETWORKS:
        raise BinanceWalletError(f"Red no permitida: {network or 'vacía'}.")

    if BinanceWalletClient.configured():
        try:
            return BinanceWalletClient().deposit_address(coin="USDT", network=network), "binance_api"
        except BinanceWalletError:
            fallback = _static_address(network)
            if fallback:
                return fallback, "environment"
            raise

    fallback = _static_address(network)
    if fallback:
        return fallback, "environment"

    names = " o ".join(_NETWORKS[network]["env"])
    raise BinanceWalletError(
        f"No hay dirección para {_NETWORKS[network]['label']}. Configura {names} "
        "o BINANCE_API_KEY/BINANCE_API_SECRET."
    )
