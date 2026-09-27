"""Bounded read-only Litecoin mainnet adapter using the LitecoinSpace Esplora API."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote, urlsplit

import httpx

from .base import ChainAdapter, ChainDataError
from .base58 import base58_decode
from ..schemas import NormalizedTransaction


LITOSHI = Decimal("100000000")
PAGE_SIZE = 25
MAX_HISTORY_PAGES = 3
MAX_CONFIRMED_RECORDS = PAGE_SIZE * MAX_HISTORY_PAGES
MAX_MEMPOOL_RECORDS = 50
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_INDEX = {character: index for index, character in enumerate(BECH32_ALPHABET)}
BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _sha256d(value: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(value).digest()).digest()


def _convert_bits(data: list[int], from_bits: int, to_bits: int) -> bytes:
    accumulator = 0
    bits = 0
    output = bytearray()
    maximum = (1 << to_bits) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise ValueError("Invalid Litecoin SegWit address")
        accumulator = (accumulator << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            output.append((accumulator >> bits) & maximum)
    if bits >= from_bits or ((accumulator << (to_bits - bits)) & maximum):
        raise ValueError("Invalid Litecoin SegWit address")
    return bytes(output)


def _bech32_polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(BECH32_GENERATORS):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _decode_litecoin_segwit(value: str) -> str:
    if not value or len(value) > 90 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError("Invalid Litecoin SegWit address")
    if value.lower() != value and value.upper() != value:
        raise ValueError("Invalid Litecoin SegWit address")
    normalized = value.lower()
    separator = normalized.rfind("1")
    if separator < 1 or separator + 7 > len(normalized) or normalized[:separator] != "ltc":
        raise ValueError("Invalid Litecoin SegWit address")
    try:
        data = [BECH32_INDEX[char] for char in normalized[separator + 1:]]
    except KeyError:
        raise ValueError("Invalid Litecoin SegWit address") from None
    hrp = normalized[:separator]
    expanded = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    polymod = _bech32_polymod(expanded + data)
    payload = data[:-6]
    if not payload:
        raise ValueError("Invalid Litecoin SegWit address")
    witness_version = payload[0]
    if witness_version > 16:
        raise ValueError("Invalid Litecoin SegWit address")
    expected = 1 if witness_version == 0 else 0x2BC830A3
    if polymod != expected:
        raise ValueError("Invalid Litecoin SegWit checksum")
    program = _convert_bits(payload[1:], 5, 8)
    if not 2 <= len(program) <= 40:
        raise ValueError("Invalid Litecoin SegWit witness program")
    if witness_version == 0 and len(program) not in (20, 32):
        raise ValueError("Invalid Litecoin SegWit witness program")
    return value


def validate_litecoin_address(value: str) -> str:
    """Validate transparent Litecoin mainnet Base58Check or SegWit syntax locally."""
    if not isinstance(value, str):
        raise ValueError("Invalid Litecoin address format")
    candidate = value.strip()
    if candidate.lower().startswith("ltc1"):
        return _decode_litecoin_segwit(candidate)
    if candidate.lower().startswith("ltcmweb1"):
        raise ValueError("MWEB addresses do not expose transparent address history")
    try:
        decoded = base58_decode(candidate)
    except ValueError:
        raise ValueError("Invalid Litecoin address format") from None
    if len(decoded) != 25 or decoded[0] not in (48, 5, 50):
        raise ValueError("Invalid Litecoin mainnet address prefix")
    if decoded[-4:] != _sha256d(decoded[:-4])[:4]:
        raise ValueError("Invalid Litecoin address checksum")
    return candidate


def _atomic_amount(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChainDataError("litecoin_invalid_provider_response")
    return format(Decimal(value) / LITOSHI, "f")


def _stat_value(stats: object, key: str) -> int:
    if not isinstance(stats, dict):
        raise ChainDataError("litecoin_invalid_provider_response")
    value = stats.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChainDataError("litecoin_invalid_provider_response")
    return value


def _is_confirmed(row: dict) -> bool:
    status = row.get("status")
    if not isinstance(status, dict):
        raise ChainDataError("litecoin_invalid_provider_response")
    confirmed = status.get("confirmed")
    if confirmed is True:
        return True
    if confirmed is False:
        return False
    if status.get("block_height") is not None:
        return True
    raise ChainDataError("litecoin_invalid_provider_response")


class LitecoinAdapter(ChainAdapter):
    chain = "litecoin"
    address_pattern = re.compile(r".+")
    transaction_pattern = re.compile(r"[0-9a-fA-F]{64}")
    transaction_identifier_name = "transaction ID"
    address_case = "bech32_insensitive"
    # Bare 64-hex txids remain Bitcoin by current resolver precedence.
    resolve_unqualified_transactions = False
    behavioral_risk = False

    def address_key(self, address: str) -> str:
        value = address.strip()
        return value.lower() if value.lower().startswith("ltc1") else value

    def address_case_insensitive(self, address: str) -> bool:
        return address.lower().startswith("ltc1")

    def validate_address(self, address: str) -> str:
        return validate_litecoin_address(address)

    def monitoring_interval(self, settings):
        return settings.litecoin_monitor_minutes

    def monitoring_baseline(self, transactions):
        return next(
            (tx for tx in transactions if (tx.get("timestamp") if isinstance(tx, dict) else tx.timestamp) is not None),
            None,
        )

    def _base_url(self) -> str:
        value = (self.settings.litecoin_api_url or "").strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ChainDataError("litecoin_configuration_unavailable")
        return value

    async def _request_json(self, path: str, *, params=None):
        url = self._base_url() + path
        try:
            async with httpx.AsyncClient(
                timeout=min(self.settings.request_timeout, 20),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    params=params,
                    headers={
                        "User-Agent": "Greedy-Collector/0.1",
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code == 429:
                        raise ChainDataError("litecoin_rate_limited")
                    if response.status_code in (401, 403):
                        raise ChainDataError("litecoin_configuration_unavailable")
                    if response.status_code != 200:
                        raise ChainDataError("litecoin_provider_failed")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ChainDataError("litecoin_invalid_provider_response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ChainDataError("litecoin_invalid_provider_response")
                        body.extend(chunk)
            return json.loads(body)
        except ChainDataError:
            raise
        except httpx.HTTPError:
            raise ChainDataError("litecoin_provider_failed") from None
        except (ValueError, UnicodeError):
            raise ChainDataError("litecoin_invalid_provider_response") from None

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        path = "/address/" + quote(address, safe="")
        payload = await self._request_json(path)
        if not isinstance(payload, dict):
            raise ChainDataError("litecoin_invalid_provider_response")
        chain = payload.get("chain_stats")
        mempool = payload.get("mempool_stats")
        funded = _stat_value(chain, "funded_txo_sum") + _stat_value(mempool, "funded_txo_sum")
        spent = _stat_value(chain, "spent_txo_sum") + _stat_value(mempool, "spent_txo_sum")
        if spent > funded:
            raise ChainDataError("litecoin_invalid_provider_response")
        transaction_count = _stat_value(chain, "tx_count") + _stat_value(mempool, "tx_count")
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": format(Decimal(funded - spent) / LITOSHI, "f"),
            "transaction_count": transaction_count,
            "source_api": "litecoinspace",
        }

    async def _history(self, address: str) -> list[dict]:
        path = "/address/" + quote(address, safe="") + "/txs"
        confirmed_rows = []
        mempool_rows = []
        confirmed_seen = set()
        mempool_seen = set()
        cursor = None
        seen_cursors = set()
        for page in range(MAX_HISTORY_PAGES):
            params = {"after_txid": cursor} if cursor else None
            rows = await self._request_json(path, params=params)
            if not isinstance(rows, list):
                raise ChainDataError("litecoin_invalid_provider_response")
            page_confirmed = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ChainDataError("litecoin_invalid_provider_response")
                txid = row.get("txid")
                if not isinstance(txid, str) or not self.transaction_pattern.fullmatch(txid):
                    raise ChainDataError("litecoin_invalid_provider_response")
                if _is_confirmed(row):
                    page_confirmed.append(row)
                elif page == 0 and txid not in mempool_seen:
                    mempool_seen.add(txid)
                    if len(mempool_rows) < MAX_MEMPOOL_RECORDS:
                        mempool_rows.append(row)
            if len(page_confirmed) > PAGE_SIZE:
                raise ChainDataError("litecoin_invalid_provider_response")
            for row in page_confirmed:
                txid = row["txid"].lower()
                if txid not in confirmed_seen and len(confirmed_rows) < MAX_CONFIRMED_RECORDS:
                    confirmed_seen.add(txid)
                    confirmed_rows.append(row)
            if page_confirmed:
                next_cursor = page_confirmed[-1]["txid"]
                if next_cursor.lower() in seen_cursors or next_cursor.lower() == (cursor or "").lower():
                    raise ChainDataError("litecoin_pagination_stalled")
                seen_cursors.add(next_cursor.lower())
                cursor = next_cursor
            if len(page_confirmed) < PAGE_SIZE or len(confirmed_rows) >= MAX_CONFIRMED_RECORDS:
                break
        # Mempool records come first so monitoring can retain a confirmed boundary.
        return mempool_rows + confirmed_rows

    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        address = self.validate_address(address)
        rows = await self._history(address)
        unique = {}
        for row in rows:
            txid = row["txid"].lower()
            previous = unique.get(txid)
            if previous is None or (not _is_confirmed(previous) and _is_confirmed(row)):
                unique[txid] = row
        mempool = []
        confirmed = []
        for row in unique.values():
            tx = self._normalize(row, address, "litecoinspace")
            (confirmed if tx.timestamp is not None else mempool).append(tx)
        confirmed.sort(key=lambda tx: tx.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return mempool + confirmed

    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        normalized = self.normalize_transaction_id(tx_hash)
        row = await self._request_json("/tx/" + quote(normalized, safe=""))
        txid = row.get("txid") if isinstance(row, dict) else None
        if not isinstance(txid, str) or txid.lower() != normalized:
            raise ChainDataError("litecoin_invalid_provider_response")
        return self._normalize(row, "", "litecoinspace")

    def _normalize(self, row: dict, focus_address: str, source_api: str) -> NormalizedTransaction:
        inputs = row.get("vin")
        outputs = row.get("vout")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            raise ChainDataError("litecoin_invalid_provider_response")
        from_addresses = []
        to_addresses = []
        output_value = 0
        sent = 0
        received = 0
        for item in inputs:
            if not isinstance(item, dict):
                raise ChainDataError("litecoin_invalid_provider_response")
            prevout = item.get("prevout")
            if not isinstance(prevout, dict):
                continue
            value = prevout.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ChainDataError("litecoin_invalid_provider_response")
            participant = prevout.get("scriptpubkey_address")
            if isinstance(participant, str) and participant:
                from_addresses.append(participant)
                if focus_address and self.address_key(participant) == self.address_key(focus_address):
                    sent += value
        for item in outputs:
            if not isinstance(item, dict):
                raise ChainDataError("litecoin_invalid_provider_response")
            value = item.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ChainDataError("litecoin_invalid_provider_response")
            output_value += value
            participant = item.get("scriptpubkey_address")
            if isinstance(participant, str) and participant:
                to_addresses.append(participant)
                if focus_address and self.address_key(participant) == self.address_key(focus_address):
                    received += value
        unique_from = list(dict.fromkeys(from_addresses))
        unique_to = list(dict.fromkeys(to_addresses))
        focus_known = not focus_address or any(
            self.address_key(value) == self.address_key(focus_address)
            for value in unique_from + unique_to
        )
        # Complex UTXO transactions preserve all raw participants but do not
        # become an inferred sender/recipient pair for graphs or counterparties.
        single_pair = len(unique_from) == 1 and len(unique_to) == 1 and focus_known
        status = row.get("status")
        if not isinstance(status, dict):
            raise ChainDataError("litecoin_invalid_provider_response")
        confirmed = _is_confirmed(row)
        block_time = status.get("block_time") if confirmed else None
        if block_time is not None and (isinstance(block_time, bool) or not isinstance(block_time, int)):
            raise ChainDataError("litecoin_invalid_provider_response")
        try:
            timestamp = datetime.fromtimestamp(block_time, timezone.utc) if block_time is not None else None
        except (ValueError, OSError, OverflowError):
            raise ChainDataError("litecoin_invalid_provider_response") from None
        height = status.get("block_height") if confirmed else None
        if height is not None and (isinstance(height, bool) or not isinstance(height, int) or height < 0):
            raise ChainDataError("litecoin_invalid_provider_response")
        fee_raw = row.get("fee")
        fee = _atomic_amount(fee_raw) if fee_raw is not None else ""
        if focus_address:
            direction = "outgoing" if sent else "incoming" if received else "unknown"
            amount = sent if sent else received
        else:
            direction = "unknown"
            amount = output_value
        txid = row.get("txid")
        if not isinstance(txid, str) or not self.transaction_pattern.fullmatch(txid):
            raise ChainDataError("litecoin_invalid_provider_response")
        return NormalizedTransaction(
            tx_hash=txid.lower(),
            chain=self.chain,
            from_address=unique_from[0] if single_pair else "",
            to_address=unique_to[0] if single_pair else "",
            value_native=_atomic_amount(amount),
            token_symbol="LTC",
            timestamp=timestamp,
            block_number=str(height) if height is not None else "",
            fee=fee,
            direction=direction,
            source_api=source_api,
            raw_payload={**row, "_public": {"confirmed": confirmed, "participant_pair_available": single_pair}},
        )
