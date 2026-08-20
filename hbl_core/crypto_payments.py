"""Validación automática de depósitos USDT por TRC20 y BEP20.

La aplicación nunca necesita una private key para validar depósitos. Solo consulta
la blockchain y compara token, destino, monto, TXID y confirmaciones antes de
acreditar el saldo HBL.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import Deposit, PaymentMethod
from .services import HBLError, approve_deposit

logger = logging.getLogger(__name__)

TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TRON_USDT_CONTRACT_DEFAULT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BSC_USDT_CONTRACT_DEFAULT = "0x55d398326f99059ff775485246999027b3197955"
TRON_DECIMALS = 6
BSC_DECIMALS = 18


class CryptoPaymentError(Exception):
    """Error de validación de pago.

    retryable=True significa que la transacción puede estar aún pendiente de
    indexación/finalidad o que el proveedor RPC tuvo un fallo temporal.
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class VerificationResult:
    network: str
    txid: str
    amount: Decimal
    confirmations: int | None
    block_number: int | None
    block_timestamp: int | None


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, str(default)) or str(default)).strip())
    except (TypeError, ValueError):
        return default


def _http_json(url: str, *, payload=None, headers=None, timeout=12):
    data = None
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        raise CryptoPaymentError(
            f"Proveedor blockchain respondió HTTP {exc.code}: {detail}",
            retryable=500 <= exc.code < 600 or exc.code == 429,
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CryptoPaymentError(
            "No fue posible consultar la blockchain en este momento.",
            retryable=True,
        ) from exc


def _rpc(url: str, method: str, params: list):
    body = _http_json(
        url,
        payload={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
    )
    if body.get("error"):
        error = body["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise CryptoPaymentError(f"RPC BSC rechazó {method}: {message}", retryable=True)
    return body.get("result")


def _normalize_hex(value: str) -> str:
    return (value or "").lower().removeprefix("0x")


def _validate_hex_txid(value: str, *, prefix: bool) -> str:
    raw = (value or "").strip().lower()
    raw_no_prefix = raw.removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_no_prefix):
        raise CryptoPaymentError("El TXID debe ser un hash hexadecimal de 64 caracteres.")
    return f"0x{raw_no_prefix}" if prefix else raw_no_prefix


def _base58check_decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    index = {c: i for i, c in enumerate(alphabet)}
    number = 0
    try:
        for char in value:
            number = number * 58 + index[char]
    except KeyError as exc:
        raise CryptoPaymentError("Dirección TRON inválida.") from exc
    full = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    zeros = len(value) - len(value.lstrip("1"))
    decoded = b"\x00" * zeros + full
    if len(decoded) < 5:
        raise CryptoPaymentError("Dirección TRON inválida.")
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected or len(payload) != 21 or payload[0] != 0x41:
        raise CryptoPaymentError("Dirección TRON inválida.")
    return payload


def _tron_evm_hex(address: str) -> str:
    return _base58check_decode((address or "").strip())[1:].hex().lower()


def _topic_address(topic: str) -> str:
    raw = _normalize_hex(topic)
    return raw[-40:] if len(raw) >= 40 else ""


def _log_contract_hex(address: str) -> str:
    raw = _normalize_hex(address)
    return raw[-40:] if len(raw) >= 40 else raw


def _amount_from_units(units: int, decimals: int) -> Decimal:
    return Decimal(units) / (Decimal(10) ** decimals)


def _assert_exact_amount(expected: Decimal, received: Decimal):
    try:
        expected = Decimal(expected)
        received = Decimal(received)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CryptoPaymentError("Monto de la transacción inválido.") from exc
    if received != expected:
        raise CryptoPaymentError(
            f"El monto en blockchain es {received} USDT y HBL esperaba exactamente {expected} USDT. Requiere revisión manual."
        )


def _assert_recent(block_timestamp_seconds: int | None, submitted_at):
    if not block_timestamp_seconds or not submitted_at:
        return
    max_minutes = max(1, _env_int("CRYPTO_TX_MAX_AGE_MINUTES", 30))
    tx_time = timezone.datetime.fromtimestamp(block_timestamp_seconds, tz=timezone.get_current_timezone())
    if tx_time < submitted_at - timedelta(minutes=max_minutes):
        raise CryptoPaymentError(
            f"La transacción es demasiado antigua para esta solicitud (más de {max_minutes} minutos antes del registro). Requiere revisión manual."
        )


def verify_trc20(deposit: Deposit) -> VerificationResult:
    txid = _validate_hex_txid(deposit.txid, prefix=False)
    destination = (
        deposit.payment_method.destination or os.getenv("USDT_TRC20_ADDRESS", "")
    ).strip()
    if not destination:
        raise CryptoPaymentError("No hay dirección TRC20 receptora configurada.")

    contract_b58 = (
        os.getenv("USDT_TRC20_CONTRACT", TRON_USDT_CONTRACT_DEFAULT)
        or TRON_USDT_CONTRACT_DEFAULT
    ).strip()
    expected_contract = _tron_evm_hex(contract_b58)
    expected_destination = _tron_evm_hex(destination)

    base_url = (
        os.getenv("TRONGRID_API_URL", "https://api.trongrid.io")
        or "https://api.trongrid.io"
    ).rstrip("/")
    headers = {}
    api_key = (os.getenv("TRONGRID_API_KEY", "") or "").strip()
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    info = _http_json(
        f"{base_url}/walletsolidity/gettransactioninfobyid",
        payload={"value": txid},
        headers=headers,
    )
    if not info or not info.get("id"):
        raise CryptoPaymentError(
            "La transacción TRC20 todavía no está solidificada o no fue encontrada.",
            retryable=True,
        )

    receipt = info.get("receipt") or {}
    execution = (receipt.get("result") or info.get("result") or "SUCCESS").upper()
    if execution != "SUCCESS":
        raise CryptoPaymentError(f"La transacción TRC20 terminó con estado {execution}.")

    total_units = 0
    for log in info.get("log") or []:
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        if _normalize_hex(topics[0]) != TRANSFER_TOPIC:
            continue
        if _log_contract_hex(log.get("address", "")) != expected_contract:
            continue
        if _topic_address(topics[2]) != expected_destination:
            continue
        try:
            total_units += int(_normalize_hex(log.get("data", "0")) or "0", 16)
        except ValueError:
            continue

    if total_units <= 0:
        raise CryptoPaymentError(
            "El TXID no contiene una transferencia USDT TRC20 hacia la dirección HBL configurada."
        )

    received = _amount_from_units(total_units, TRON_DECIMALS)
    _assert_exact_amount(deposit.payment_amount, received)

    timestamp_ms = info.get("blockTimeStamp") or info.get("block_timestamp")
    timestamp_seconds = int(timestamp_ms) // 1000 if timestamp_ms else None
    _assert_recent(timestamp_seconds, deposit.submitted_at)

    return VerificationResult(
        network="TRC20",
        txid=txid,
        amount=received,
        confirmations=None,
        block_number=int(info.get("blockNumber")) if info.get("blockNumber") is not None else None,
        block_timestamp=timestamp_seconds,
    )


def verify_bep20(deposit: Deposit) -> VerificationResult:
    txid = _validate_hex_txid(deposit.txid, prefix=True)
    destination = (
        deposit.payment_method.destination or os.getenv("USDT_BEP20_ADDRESS", "")
    ).strip().lower()
    if not re.fullmatch(r"0x[a-f0-9]{40}", destination):
        raise CryptoPaymentError("No hay una dirección BEP20 receptora válida configurada.")

    contract = (
        os.getenv("USDT_BEP20_CONTRACT", BSC_USDT_CONTRACT_DEFAULT)
        or BSC_USDT_CONTRACT_DEFAULT
    ).strip().lower()
    if not re.fullmatch(r"0x[a-f0-9]{40}", contract):
        raise CryptoPaymentError("El contrato USDT BEP20 configurado no es válido.")

    rpc_url = (
        os.getenv("BSC_RPC_URL", "https://bsc-dataseed.bnbchain.org")
        or "https://bsc-dataseed.bnbchain.org"
    ).strip()
    receipt = _rpc(rpc_url, "eth_getTransactionReceipt", [txid])
    if not receipt:
        raise CryptoPaymentError(
            "La transacción BEP20 todavía no fue minada o no fue encontrada.",
            retryable=True,
        )
    if str(receipt.get("status", "")).lower() != "0x1":
        raise CryptoPaymentError("La transacción BEP20 falló en la blockchain.")

    block_hex = receipt.get("blockNumber")
    if not block_hex:
        raise CryptoPaymentError(
            "La transacción BEP20 todavía no tiene bloque confirmado.",
            retryable=True,
        )
    tx_block = int(block_hex, 16)
    latest_hex = _rpc(rpc_url, "eth_blockNumber", [])
    if not latest_hex:
        raise CryptoPaymentError("No fue posible obtener la altura actual de BSC.", retryable=True)
    latest_block = int(latest_hex, 16)
    confirmations = max(0, latest_block - tx_block + 1)
    required = max(1, _env_int("BSC_REQUIRED_CONFIRMATIONS", 12))
    if confirmations < required:
        raise CryptoPaymentError(
            f"La transacción BEP20 tiene {confirmations}/{required} confirmaciones requeridas.",
            retryable=True,
        )

    total_units = 0
    expected_destination = destination.removeprefix("0x")
    expected_contract = contract.removeprefix("0x")
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        if _normalize_hex(topics[0]) != TRANSFER_TOPIC:
            continue
        if _log_contract_hex(log.get("address", "")) != expected_contract:
            continue
        if _topic_address(topics[2]) != expected_destination:
            continue
        try:
            total_units += int(_normalize_hex(log.get("data", "0")) or "0", 16)
        except ValueError:
            continue

    if total_units <= 0:
        raise CryptoPaymentError(
            "El TXID no contiene una transferencia USDT BEP20 hacia la dirección HBL configurada."
        )

    received = _amount_from_units(total_units, BSC_DECIMALS)
    _assert_exact_amount(deposit.payment_amount, received)

    block = _rpc(rpc_url, "eth_getBlockByNumber", [block_hex, False]) or {}
    timestamp_hex = block.get("timestamp")
    timestamp_seconds = int(timestamp_hex, 16) if timestamp_hex else None
    _assert_recent(timestamp_seconds, deposit.submitted_at)

    return VerificationResult(
        network="BEP20",
        txid=txid,
        amount=received,
        confirmations=confirmations,
        block_number=tx_block,
        block_timestamp=timestamp_seconds,
    )


def verify_deposit(deposit: Deposit) -> VerificationResult:
    if deposit.payment_method.kind == PaymentMethod.Kind.USDT_TRC20:
        return verify_trc20(deposit)
    if deposit.payment_method.kind == PaymentMethod.Kind.USDT_BEP20:
        return verify_bep20(deposit)
    raise CryptoPaymentError("Este método no admite validación automática de USDT.")


def _set_verification_state(deposit_id, *, status, notes):
    with transaction.atomic():
        deposit = Deposit.objects.select_for_update().get(pk=deposit_id)
        if deposit.status == Deposit.Status.APPROVED:
            return deposit
        deposit.status = status
        deposit.notes = (notes or "")[:2000]
        deposit.save(update_fields=["status", "notes"])
        return deposit


def verify_and_credit_deposit(deposit_id):
    """Verifica una recarga y la acredita de forma idempotente si es válida."""
    deposit = Deposit.objects.select_related("payment_method", "user").get(pk=deposit_id)
    if deposit.status == Deposit.Status.APPROVED:
        return deposit, False
    if deposit.payment_method.kind not in {
        PaymentMethod.Kind.USDT_TRC20,
        PaymentMethod.Kind.USDT_BEP20,
    }:
        return deposit, False
    if not deposit.txid:
        return deposit, False

    _set_verification_state(
        deposit.id,
        status=Deposit.Status.PROCESSING,
        notes="Validación automática de blockchain en curso.",
    )
    deposit.refresh_from_db()

    try:
        result = verify_deposit(deposit)
    except CryptoPaymentError as exc:
        next_status = Deposit.Status.PROCESSING if exc.retryable else Deposit.Status.PENDING
        prefix = (
            "Pendiente de confirmación automática"
            if exc.retryable
            else "Revisión manual requerida"
        )
        _set_verification_state(deposit.id, status=next_status, notes=f"{prefix}: {exc}")
        logger.info(
            "Validación USDT no acreditada deposit=%s retryable=%s reason=%s",
            deposit.id,
            exc.retryable,
            exc,
        )
        return Deposit.objects.get(pk=deposit.id), False
    except Exception:
        logger.exception("Error inesperado validando depósito USDT %s", deposit.id)
        _set_verification_state(
            deposit.id,
            status=Deposit.Status.PROCESSING,
            notes="Pendiente de confirmación automática: error temporal consultando la blockchain.",
        )
        return Deposit.objects.get(pk=deposit.id), False

    note = (
        f"Validado automáticamente en {result.network}. "
        f"Monto={result.amount} USDT; bloque={result.block_number or 'final'}"
    )
    if result.confirmations is not None:
        note += f"; confirmaciones={result.confirmations}"

    try:
        approved, changed = approve_deposit(
            deposit.id,
            transaction_id=result.txid,
            notes=note,
        )
    except HBLError:
        current = Deposit.objects.get(pk=deposit.id)
        if current.status == Deposit.Status.APPROVED:
            return current, False
        raise
    return approved, changed
