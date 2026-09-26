"""Read-only TRON mainnet adapter backed by bounded TronGrid requests."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .base import ChainAdapter, ChainDataError
from ..schemas import NormalizedTransaction


BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}
SUN = Decimal("1000000")
PAGE_SIZE = 200
MAX_PAGES = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _base58_decode(value: str) -> bytes:
    number = 0
    for character in value:
        try:
            digit = BASE58_INDEX[character]
        except KeyError:
            raise ValueError("Invalid TRON address format") from None
        number = number * 58 + digit
    payload = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + payload


def _base58_encode(value: bytes) -> str:
    leading = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, digit = divmod(number, 58)
        encoded = BASE58_ALPHABET[digit] + encoded
    return "1" * leading + encoded


def tron_address_to_hex(address: str) -> str:
    """Validate a user-facing address and return its 41-prefixed hex form."""
    candidate = address.strip()
    if len(candidate) != 34 or not candidate.startswith("T"):
        raise ValueError("Invalid TRON address format")
    decoded = _base58_decode(candidate)
    if len(decoded) != 25 or decoded[0] != 0x41:
        raise ValueError("Invalid TRON address format")
    payload, checksum = decoded[:21], decoded[21:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise ValueError("Invalid TRON address checksum")
    return payload.hex()


def tron_address_from_hex(value: str) -> str:
    """Convert an exact 41-prefixed hex address to canonical Base58Check."""
    candidate = value.strip()
    if not re.fullmatch(r"41[0-9a-fA-F]{40}", candidate):
        raise ValueError("Invalid TRON hex address")
    payload = bytes.fromhex(candidate)
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _base58_encode(payload + checksum)


def _decimal_amount(raw_value, decimals: int) -> str:
    try:
        raw = Decimal(str(raw_value))
    except (InvalidOperation, ValueError, TypeError):
        raise ChainDataError("tron_invalid_provider_response") from None
    if raw != raw.to_integral_value() or decimals < 0 or decimals > 80:
        raise ChainDataError("tron_invalid_provider_response")
    return str(raw / (Decimal(10) ** decimals))


def _timestamp(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        raise ChainDataError("tron_invalid_provider_response") from None


class TronAdapter(ChainAdapter):
    chain = "tron"
    address_case = "sensitive"
    address_pattern = re.compile(r"T[1-9A-HJ-NP-Za-km-z]{33}")
    transaction_pattern = re.compile(r"[0-9a-fA-F]{64}")
    # Bare 64-hex identifiers remain Bitcoin by default. A TRON hint resolves a
    # TRON transaction deterministically without provider traffic.
    resolve_unqualified_transactions = False
    behavioral_risk = False
    base_url = "https://api.trongrid.io"

    def validate_address(self, address: str) -> str:
        candidate = address.strip()
        if not self.address_pattern.fullmatch(candidate):
            raise ValueError("Invalid TRON address format")
        tron_address_to_hex(candidate)
        return candidate

    def normalize_transaction_id(self, value: str) -> str:
        candidate = value.strip()
        if not self.identify_transaction(candidate):
            raise ValueError("Invalid TRON transaction ID")
        return candidate.lower()

    def monitoring_interval(self, settings):
        return settings.tron_monitor_minutes

    def _require_key(self) -> str:
        if not self.settings.tron_pro_api_key:
            raise ChainDataError("tron_configuration_unavailable")
        return self.settings.tron_pro_api_key

    async def _request_json(self, method: str, path: str, *, params=None, payload=None):
        headers = {
            "User-Agent": "Greedy-Collector/0.1 (+Greedy Collector)",
            "Accept-Encoding": "identity",
            "TRON-PRO-API-KEY": self._require_key(),
        }
        try:
            async with httpx.AsyncClient(
                timeout=min(self.settings.request_timeout, 20),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    method, self.base_url + path, params=params, json=payload, headers=headers
                ) as response:
                    status = response.status_code
                    if status == 429:
                        raise ChainDataError("tron_rate_limited")
                    if status in (401, 403):
                        raise ChainDataError("tron_configuration_unavailable")
                    if status == 404:
                        raise ChainDataError("tron_not_found")
                    if status == 400:
                        raise ChainDataError("tron_request_rejected")
                    if status >= 500 or status != 200:
                        raise ChainDataError("tron_provider_unavailable")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ChainDataError("tron_invalid_provider_response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ChainDataError("tron_invalid_provider_response")
                        body.extend(chunk)
            data = json.loads(body)
        except ChainDataError:
            raise
        except httpx.TimeoutException:
            raise ChainDataError("tron_timeout") from None
        except httpx.HTTPError:
            raise ChainDataError("tron_transport_failed") from None
        except (ValueError, UnicodeError):
            raise ChainDataError("tron_invalid_provider_response") from None
        if not isinstance(data, dict) or data.get("success") is False:
            raise ChainDataError("tron_invalid_provider_response")
        return data

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        data = await self._request_json(
            "GET", f"/v1/accounts/{address}", params={"only_confirmed": "true"}
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ChainDataError("tron_invalid_provider_response")
        account = rows[0] if rows else {}
        if not isinstance(account, dict):
            raise ChainDataError("tron_invalid_provider_response")
        balance = account.get("balance", 0)
        if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
            raise ChainDataError("tron_invalid_provider_response")
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": str(Decimal(balance) / SUN),
            "source_api": "trongrid",
        }

    async def _history(self, path: str, address: str) -> list[dict]:
        rows: list[dict] = []
        fingerprint = None
        seen_fingerprints = set()
        for _ in range(MAX_PAGES):
            params = {
                "only_confirmed": "true",
                "limit": PAGE_SIZE,
                "order_by": "block_timestamp,desc",
            }
            if fingerprint:
                params["fingerprint"] = fingerprint
            data = await self._request_json("GET", path, params=params)
            page = data.get("data")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise ChainDataError("tron_invalid_provider_response")
            rows.extend(page[:PAGE_SIZE])
            meta = data.get("meta") or {}
            next_fingerprint = meta.get("fingerprint") if isinstance(meta, dict) else None
            if not page or len(page) < PAGE_SIZE or not isinstance(next_fingerprint, str):
                break
            if not next_fingerprint or next_fingerprint in seen_fingerprints:
                break
            seen_fingerprints.add(next_fingerprint)
            fingerprint = next_fingerprint
        return rows[: PAGE_SIZE * MAX_PAGES]

    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        address = self.validate_address(address)
        ordinary_rows = await self._history(f"/v1/accounts/{address}/transactions", address)
        token_rows = await self._history(f"/v1/accounts/{address}/transactions/trc20", address)
        combined = []
        for row in ordinary_rows:
            tx = self._normalize_account_transaction(row, address)
            if tx is not None:
                combined.append(tx)
        for row in token_rows:
            combined.append(self._normalize_trc20(row, address))
        seen = set()
        result = []
        for tx in combined:
            identity = self.transfer_identity(tx)
            if identity and identity not in seen:
                seen.add(identity)
                result.append(tx)
        return sorted(
            result,
            key=lambda tx: (
                tx.timestamp or datetime.min.replace(tzinfo=timezone.utc),
                tx.tx_hash,
                self.transfer_identity(tx),
            ),
            reverse=True,
        )

    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        tx_hash = self.normalize_transaction_id(tx_hash)
        data = await self._request_json(
            "POST", "/walletsolidity/gettransactionbyid", payload={"value": tx_hash, "visible": True}
        )
        if not data or not data.get("txID"):
            raise ChainDataError("tron_not_found")
        tx = self._normalize_account_transaction(data, "")
        if tx is None:
            raise ChainDataError("tron_unsupported_transaction_type")
        return tx

    @staticmethod
    def _provider_address(value) -> str:
        if not isinstance(value, str):
            raise ChainDataError("tron_invalid_provider_response")
        if value.startswith("T"):
            try:
                tron_address_to_hex(value)
                return value
            except ValueError:
                raise ChainDataError("tron_invalid_provider_response") from None
        try:
            return tron_address_from_hex(value)
        except ValueError:
            raise ChainDataError("tron_invalid_provider_response") from None

    @staticmethod
    def _event_id(kind: str, values: dict) -> str:
        material = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return kind + ":" + hashlib.sha256(material.encode()).hexdigest()

    def _normalize_account_transaction(self, row: dict, focus_address: str) -> NormalizedTransaction | None:
        try:
            contract = row["raw_data"]["contract"][0]
            contract_type = contract["type"]
            values = contract["parameter"]["value"]
        except (KeyError, IndexError, TypeError):
            raise ChainDataError("tron_invalid_provider_response") from None
        if not isinstance(contract_type, str) or not isinstance(values, dict):
            raise ChainDataError("tron_invalid_provider_response")
        if contract_type not in ("TransferContract", "TransferAssetContract"):
            tx_hash = str(row.get("txID") or "").lower()
            if not self.identify_transaction(tx_hash):
                raise ChainDataError("tron_invalid_provider_response")
            event_id = self._event_id("unsupported", {"tx_hash": tx_hash, "type": str(contract_type)})
            return NormalizedTransaction(
                tx_hash=tx_hash,
                chain=self.chain,
                timestamp=_timestamp(row.get("block_timestamp") or (row.get("raw_data") or {}).get("timestamp")),
                block_number=str(row.get("blockNumber") or row.get("block_number") or ""),
                direction="unknown",
                source_api="trongrid",
                raw_payload={"_event_id": event_id, "_public": {
                    "asset_type": "unsupported", "unsupported_type": contract_type[:128],
                    "confirmed": True, "event_id": event_id,
                }},
            )
        sender = self._provider_address(values.get("owner_address"))
        recipient = self._provider_address(values.get("to_address"))
        amount = values.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ChainDataError("tron_invalid_provider_response")
        tx_hash = str(row.get("txID") or "").lower()
        if not self.identify_transaction(tx_hash):
            raise ChainDataError("tron_invalid_provider_response")
        if contract_type == "TransferContract":
            symbol = "TRX"
            normalized = str(Decimal(amount) / SUN)
            asset_type = "native"
        else:
            asset_name = values.get("asset_name", "")
            try:
                symbol = bytes.fromhex(asset_name).decode("utf-8") if re.fullmatch(r"[0-9a-fA-F]+", str(asset_name)) else str(asset_name)
            except (ValueError, UnicodeError):
                symbol = str(asset_name)
            symbol = symbol[:32] or "TRC-10"
            normalized = str(Decimal(amount))
            asset_type = "trc10"
        event_values = {
            "tx_hash": tx_hash,
            "type": contract_type,
            "from": sender,
            "to": recipient,
            "raw_value": str(amount),
            "asset": symbol,
            "contract_index": row.get("contract_index", 0),
        }
        event_id = self._event_id(asset_type, event_values)
        timestamp = _timestamp(row.get("block_timestamp") or (row.get("raw_data") or {}).get("timestamp"))
        return NormalizedTransaction(
            tx_hash=tx_hash,
            chain=self.chain,
            from_address=sender,
            to_address=recipient,
            value_native=normalized,
            token_symbol=symbol,
            timestamp=timestamp,
            block_number=str(row.get("blockNumber") or row.get("block_number") or ""),
            fee="0",
            direction="outgoing" if focus_address and sender == focus_address else "incoming" if focus_address else "unknown",
            source_api="trongrid",
            raw_payload={
                "_event_id": event_id,
                "_public": {
                    "asset_type": asset_type,
                    "raw_value": str(amount),
                    "confirmed": True,
                    "event_id": event_id,
                },
                "provider": row,
            },
        )

    def _normalize_trc20(self, row: dict, focus_address: str) -> NormalizedTransaction:
        token = row.get("token_info")
        if not isinstance(token, dict):
            raise ChainDataError("tron_invalid_provider_response")
        sender = self._provider_address(row.get("from"))
        recipient = self._provider_address(row.get("to"))
        contract = self._provider_address(token.get("address"))
        tx_hash = str(row.get("transaction_id") or "").lower()
        if not self.identify_transaction(tx_hash):
            raise ChainDataError("tron_invalid_provider_response")
        try:
            if isinstance(token.get("decimals", 0), bool):
                raise TypeError()
            decimals = int(token.get("decimals", 0))
        except (ValueError, TypeError):
            raise ChainDataError("tron_invalid_provider_response") from None
        raw_value = str(row.get("value", ""))
        normalized = _decimal_amount(raw_value, decimals)
        symbol = str(token.get("symbol") or "TOKEN")[:32]
        event_values = {
            "tx_hash": tx_hash,
            "from": sender,
            "to": recipient,
            "contract": contract,
            "raw_value": raw_value,
            "decimals": decimals,
            "event_index": row.get("event_index", row.get("log_index")),
        }
        event_id = self._event_id("trc20", event_values)
        from ..transaction_identity import normalize_event_index
        try:
            event_index = normalize_event_index(event_values["event_index"])
        except ValueError:
            raise ChainDataError("tron_invalid_provider_response") from None
        public = {
            "asset_type": "trc20",
            "token_contract": contract,
            "token_name": str(token.get("name") or "")[:255],
            "token_decimals": decimals,
            "raw_value": raw_value,
            "confirmed": True,
            "event_id": event_id,
        }
        return NormalizedTransaction(
            tx_hash=tx_hash,
            chain=self.chain,
            from_address=sender,
            to_address=recipient,
            value_native=normalized,
            token_symbol=symbol,
            timestamp=_timestamp(row.get("block_timestamp")),
            block_number=str(row.get("block") or row.get("block_number") or ""),
            fee="0",
            direction="outgoing" if focus_address and sender == focus_address else "incoming",
            source_api="trongrid_trc20",
            raw_payload={"_event_id": event_id, "_public": public, "provider": row},
            event_index=event_index,
            asset_contract=contract,
        )
