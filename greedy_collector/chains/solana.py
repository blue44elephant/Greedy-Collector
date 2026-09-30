"""Bounded, read-only Solana mainnet JSON-RPC adapter."""
from __future__ import annotations

import re
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from .base import ChainAdapter, ChainDataError, RpcReadError
from .base58 import BASE58_ALPHABET, BASE58_INDEX, base58_decode, base58_encode
from ..schemas import NormalizedTransaction
from ..collection import atomic_amount, utc_timestamp, decimals_or_none

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_RPC_URL = "https://api.mainnet.solana.com"
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100
PAGE_LIMIT = 100
SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def validate_pubkey(value: str) -> str:
    candidate = value.strip()
    if len(base58_decode(candidate)) != 32 or base58_encode(base58_decode(candidate)) != candidate:
        raise ValueError("Invalid Solana address format")
    return candidate


def validate_signature(value: str) -> str:
    candidate = value.strip()
    if len(base58_decode(candidate)) != 64 or base58_encode(base58_decode(candidate)) != candidate:
        raise ValueError("Invalid Solana transaction signature")
    return candidate


def _amount(raw: object, decimals: int) -> str:
    if isinstance(raw, bool) or not re.fullmatch(r"[0-9]+", str(raw)):
        raise ChainDataError("solana_invalid_provider_response")
    if type(decimals) is not int or not 0 <= decimals <= 38:
        raise ChainDataError("solana_invalid_provider_response")
    return atomic_amount(raw, decimals)


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChainDataError("solana_invalid_provider_response")
    try:
        return utc_timestamp(value)
    except (ValueError, OSError, OverflowError):
        raise ChainDataError("solana_invalid_provider_response") from None


class SolanaAdapter(ChainAdapter):
    chain = "solana"
    address_case = "sensitive"
    address_pattern = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
    transaction_pattern = re.compile(r"[1-9A-HJ-NP-Za-km-z]{80,90}")
    transaction_identifier_name = "transaction signature"
    resolve_unqualified_transactions = True
    behavioral_risk = False

    def validate_address(self, address: str) -> str:
        candidate = address.strip()
        if not self.address_pattern.fullmatch(candidate):
            raise ValueError("Invalid Solana address format")
        return validate_pubkey(candidate)

    def identify_transaction(self, value: str) -> bool:
        try:
            validate_signature(value)
            return True
        except ValueError:
            return False

    def normalize_transaction_id(self, value: str) -> str:
        return validate_signature(value)

    def monitoring_interval(self, settings):
        return settings.solana_monitor_minutes

    def monitoring_cursor(self, transaction):
        return transaction.get("tx_hash") if isinstance(transaction, dict) else transaction.tx_hash

    def _rpc_url(self) -> str:
        value = (self.settings.solana_rpc_url or DEFAULT_RPC_URL).strip()
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ChainDataError("solana_configuration_unavailable")
        return value

    async def _rpc(self, method: str, params: list, *, maximum=2 * 1024 * 1024):
        if method not in {"getBalance", "getSignaturesForAddress", "getTransaction"}:
            raise ChainDataError("solana_unsupported_rpc_method")
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for attempt in range(2):
            try:
                data = await self._post_bounded(self._rpc_url(), payload, maximum=maximum)
                break
            except RpcReadError as exc:
                # Honor short provider backoff signals once. Longer or unknown
                # Retry-After values end this lookup; the next scheduled/manual
                # request can retry without sleeping or looping in the worker.
                delay = exc.retry_after_seconds
                if exc.category == "rate_limited" and attempt == 0 and delay is not None and 0 <= delay <= 2:
                    await asyncio.sleep(delay)
                    continue
                raise ChainDataError(f"solana_{exc.category}") from None
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0" or data.get("id") != 1:
            raise ChainDataError("solana_invalid_provider_response")
        if isinstance(data.get("error"), dict):
            code = data["error"].get("code")
            if code == -32004 or code == -32015:
                raise ChainDataError("solana_unsupported_transaction_version")
            raise ChainDataError("solana_provider_rejected_request")
        if "result" not in data:
            raise ChainDataError("solana_invalid_provider_response")
        return data["result"]

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        result = await self._rpc("getBalance", [address, {"commitment": "finalized"}], maximum=65536)
        if not isinstance(result, dict):
            raise ChainDataError("solana_invalid_provider_response")
        lamports = result.get("value")
        if isinstance(lamports, bool) or not isinstance(lamports, int) or lamports < 0:
            raise ChainDataError("solana_invalid_provider_response")
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": atomic_amount(lamports, 9),
            "source_api": "solana-json-rpc",
            "rpc_endpoint": "configured" if self.settings.solana_rpc_url else "public_mainnet_fallback",
        }

    async def _signatures(self, address: str, *, limit: int, before: str | None = None) -> list[dict]:
        address = self.validate_address(address)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise ValueError("Solana history limit must be between 1 and 100")
        result = await self._rpc("getSignaturesForAddress", [address, {
            "commitment": "confirmed", "limit": min(limit, PAGE_LIMIT), **({"before": before} if before else {})
        }])
        if not isinstance(result, list) or len(result) > PAGE_LIMIT:
            raise ChainDataError("solana_invalid_provider_response")
        rows = []
        for row in result:
            if not isinstance(row, dict) or not isinstance(row.get("signature"), str):
                raise ChainDataError("solana_invalid_provider_response")
            try:
                signature = validate_signature(row["signature"])
            except ValueError:
                raise ChainDataError("solana_invalid_provider_response") from None
            rows.append({**row, "signature": signature})
        return rows[:limit]

    async def transactions(self, address: str, *, limit: int = DEFAULT_HISTORY_LIMIT, before: str | None = None) -> list[NormalizedTransaction]:
        if before is not None: before = self.normalize_transaction_id(before)
        rows = await self._signatures(address, limit=limit, before=before)
        self.collection_streams = {"signatures": {"status": "TRUNCATED" if len(rows) >= limit else "PROVIDER_LIMITED",
            "reason": "signature_bound" if len(rows) >= limit else "provider_retention", "max_records": limit}}
        output = []
        seen = set()
        for row in rows:
            if row["signature"] in seen: continue
            seen.add(row["signature"])
            try:
                tx = await self._get_transaction(row["signature"])
            except ChainDataError as exc:
                self.collection_streams["signatures"].update(status="PARTIAL", reason=exc.category)
                tx = None
            if tx is None:
                if hasattr(self, "collection_streams"): self.collection_streams["signatures"].update(status="PARTIAL", reason="transaction_unavailable")
                output.append(self._activity_record(row["signature"], row, None))
                continue
            try:
                output.extend(self.parse_transaction(tx, focus_address=address, signature=row["signature"]))
            except (ChainDataError, ValueError, TypeError):
                self.collection_streams["signatures"].update(status="PARTIAL", reason="malformed_response")
                marker = self._activity_record(row["signature"], row, None)
                marker.raw_payload["provider"] = tx
                output.append(marker)
        return output

    async def monitoring_delta(self, address: str, previous_identity: str, *, limit: int = MAX_HISTORY_LIMIT) -> dict:
        """Fetch only signatures newer than a saved event boundary, within 100 rows."""
        match = re.match(r"^solana:([^:]+):", previous_identity or "")
        boundary = match.group(1) if match else previous_identity
        if not self.identify_transaction(boundary):
            return {"transactions": [], "boundary_found": False}
        boundary = self.normalize_transaction_id(boundary)
        rows = await self._signatures(address, limit=min(limit, MAX_HISTORY_LIMIT))
        position = next((index for index, row in enumerate(rows) if row["signature"] == boundary), None)
        if position is None:
            return {"transactions": [], "boundary_found": False}
        output = []
        for row in rows[:position]:
            tx = await self._get_transaction(row["signature"])
            if tx is None:
                output.append(self._activity_record(row["signature"], row, None))
            else:
                output.extend(self.parse_transaction(tx, focus_address=address, signature=row["signature"]))
        return {"transactions": output, "boundary_found": True}

    async def lookup_transaction_events(self, signature: str) -> list[NormalizedTransaction]:
        signature = self.normalize_transaction_id(signature)
        tx = await self._get_transaction(signature)
        if tx is None:
            raise ChainDataError("solana_transaction_unavailable")
        return self.parse_transaction(tx, signature=signature)

    async def lookup_transaction(self, signature: str) -> NormalizedTransaction:
        return (await self.lookup_transaction_events(signature))[0]

    async def _get_transaction(self, signature: str):
        try:
            return await self._rpc("getTransaction", [signature, {
                "commitment": "confirmed", "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 1,
            }])
        except ChainDataError as exc:
            if str(exc) == "solana_unsupported_transaction_version":
                return {"_unsupported_version": True}
            raise

    @staticmethod
    def _account_keys(transaction: dict, meta: dict) -> list[str]:
        message = transaction.get("message") if isinstance(transaction, dict) else None
        raw = message.get("accountKeys", []) if isinstance(message, dict) else []
        keys = []
        for item in raw if isinstance(raw, list) else []:
            key = item.get("pubkey") if isinstance(item, dict) else item
            if isinstance(key, str):
                keys.append(key)
        # jsonParsed normally expands loaded keys into accountKeys. Accommodate
        # providers that also return the standard loadedAddresses metadata.
        loaded = meta.get("loadedAddresses") if isinstance(meta, dict) else None
        if isinstance(loaded, dict):
            for name in ("writable", "readonly"):
                values = loaded.get(name, [])
                if isinstance(values, list):
                    keys.extend(value for value in values if isinstance(value, str))
        return keys

    @staticmethod
    def _token_owners(meta: dict, keys: list[str]):
        owners = {"pre": {}, "post": {}}
        decimals = {}
        mints = {}
        for field in ("preTokenBalances", "postTokenBalances"):
            phase = "pre" if field == "preTokenBalances" else "post"
            rows = meta.get(field, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                index, mint = row.get("accountIndex"), row.get("mint")
                amount = row.get("uiTokenAmount")
                if type(index) is not int or not 0 <= index < len(keys) or not isinstance(mint, str) or not isinstance(amount, dict):
                    continue
                account = keys[index]
                if isinstance(row.get("owner"), str):
                    owners[phase][(account, mint)] = row["owner"]
                if type(amount.get("decimals")) is int and 0 <= amount["decimals"] <= 38:
                    decimals[mint] = amount["decimals"]
                mints.setdefault(account, set()).add(mint)
        return owners, decimals, mints

    def _activity_record(self, signature, row, transaction):
        block_time = transaction.get("blockTime") if isinstance(transaction, dict) else row.get("blockTime")
        slot = transaction.get("slot") if isinstance(transaction, dict) else row.get("slot")
        public = {"execution_status": "failed" if row.get("err") is not None else "succeeded" if transaction and not transaction.get("_unsupported_version") else "unavailable"}
        if isinstance(transaction, dict) and transaction.get("_unsupported_version"):
            public["transaction_version_status"] = "unsupported"
        return NormalizedTransaction(tx_hash=signature, chain=self.chain, timestamp=_timestamp(block_time),
            block_number=str(slot or ""), direction="unknown", source_api="solana-json-rpc",
            value_native="", fee="", raw_payload={"_public": {**public, "asset_type": "unsupported"}, "provider": transaction, "signature_record": row})

    def parse_transaction(self, transaction: dict, *, focus_address: str = "", signature: str | None = None) -> list[NormalizedTransaction]:
        if not isinstance(transaction, dict):
            raise ChainDataError("solana_invalid_provider_response")
        if transaction.get("_unsupported_version"):
            return [self._activity_record(signature or "", {}, transaction)]
        tx_message = transaction.get("transaction")
        if isinstance(tx_message, list):
            tx_message = tx_message[0] if tx_message and isinstance(tx_message[0], dict) else None
        if not isinstance(tx_message, dict):
            raise ChainDataError("solana_invalid_provider_response")
        message = tx_message.get("message")
        if not isinstance(message, dict):
            raise ChainDataError("solana_invalid_provider_response")
        signatures = tx_message.get("signatures")
        if not isinstance(signature, str):
            signature = signatures[0] if isinstance(signatures, list) and signatures else None
        if not isinstance(signature, str):
            raise ChainDataError("solana_invalid_provider_response")
        try:
            signature = validate_signature(signature)
        except ValueError:
            raise ChainDataError("solana_invalid_provider_response") from None
        meta = transaction.get("meta")
        if meta is None:
            activity = self._activity_record(signature, {}, None)
            activity.raw_payload["provider"] = transaction
            return [activity]
        if not isinstance(meta, dict):
            raise ChainDataError("solana_invalid_provider_response")
        if meta.get("err") is not None:
            return [self._activity_record(signature, {"err": meta.get("err")}, transaction)]
        version = transaction.get("version", "legacy")
        if version not in ("legacy", 0, 1):
            return [self._activity_record(signature, {}, {**transaction, "_unsupported_version": True})]
        keys = self._account_keys({"message": message}, meta)
        owner_map, token_decimals, token_mints = self._token_owners(meta, keys)
        events = []
        seen_paths = set()
        instructions = message.get("instructions", [])
        if not isinstance(instructions, list):
            raise ChainDataError("solana_invalid_provider_response")
        for outer_index, instruction in enumerate(instructions):
            event = self._parse_instruction(instruction, outer_index, None, signature, transaction, focus_address, owner_map, token_decimals, token_mints)
            if event:
                events.append(event); seen_paths.add(event.raw_payload["_stable_event_key"])
        inner = meta.get("innerInstructions", [])
        if isinstance(inner, list):
            for group in inner:
                if not isinstance(group, dict) or type(group.get("index")) is not int or not isinstance(group.get("instructions"), list):
                    continue
                outer_index = group["index"]
                for inner_index, instruction in enumerate(group["instructions"]):
                    event = self._parse_instruction(instruction, outer_index, inner_index, signature, transaction, focus_address, owner_map, token_decimals, token_mints)
                    if event:
                        key = event.raw_payload["_stable_event_key"]
                        if key not in seen_paths:
                            events.append(event); seen_paths.add(key)
        if not events:
            return [self._activity_record(signature, {}, transaction)]
        return events

    def _parse_instruction(self, instruction, outer, inner, signature, transaction, focus, owner_map, token_decimals, token_mints):
        if not isinstance(instruction, dict) or not isinstance(instruction.get("parsed"), dict):
            return None
        program_id = instruction.get("programId")
        parsed = instruction["parsed"]
        kind, info = parsed.get("type"), parsed.get("info")
        if not isinstance(info, dict):
            return None
        event_key = f"solana-ix:{outer}" if inner is None else f"solana-inner:{outer}:{inner}"
        if program_id == SYSTEM_PROGRAM and kind == "transfer":
            sender, recipient = info.get("source"), info.get("destination")
            raw = info.get("lamports")
            if not isinstance(sender, str) or not isinstance(recipient, str):
                return None
            amount = _amount(raw, 9)
            symbol, mint, source_token, destination_token = "SOL", None, None, None
            public = {"asset_type": "native", "raw_value": str(raw), "instruction_type": kind}
        elif program_id in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM) and kind in ("transfer", "transferChecked"):
            source_token, destination_token = info.get("source"), info.get("destination")
            mint = info.get("mint")
            if not isinstance(mint, str):
                candidates = token_mints.get(source_token, set()) | token_mints.get(destination_token, set())
                mint = next(iter(candidates)) if len(candidates) == 1 else None
            token_amount = info.get("tokenAmount")
            raw = info.get("amount")
            decimals = token_amount.get("decimals") if isinstance(token_amount, dict) else None
            if raw is None and isinstance(token_amount, dict):
                raw = token_amount.get("amount")
            if not isinstance(source_token, str) or not isinstance(destination_token, str) or not isinstance(mint, str):
                return None
            if type(decimals) is not int:
                decimals = token_decimals.get(mint)
            if not isinstance(raw, (int, str)):
                return None
            amount = _amount(raw, decimals) if type(decimals) is int else ""
            sender = owner_map["pre"].get((source_token, mint)) or owner_map["post"].get((source_token, mint))
            recipient = owner_map["post"].get((destination_token, mint)) or owner_map["pre"].get((destination_token, mint))
            if not isinstance(sender, str) or not isinstance(recipient, str):
                sender = recipient = ""
            symbol = "SPL"
            public = {"asset_type": "token2022" if program_id == TOKEN_2022_PROGRAM else "spl_token",
                "raw_value": str(raw), "token_mint": mint, "token_decimals": decimals,
                "source_token_account": source_token, "destination_token_account": destination_token,
                "source_owner_known": bool(sender), "destination_owner_known": bool(recipient),
                "amount_basis": "parsed_instruction_amount",
                "instruction_type": kind}
        else:
            return None
        block_time = transaction.get("blockTime")
        slot = transaction.get("slot")
        direction = "outgoing" if sender and focus and sender == focus else "incoming" if recipient and focus and recipient == focus else "unknown"
        if direction == "unknown" and focus:
            if source_token == focus: direction = "outgoing"
            elif destination_token == focus: direction = "incoming"
        payload = {"provider": transaction, "_stable_event_key": event_key, "_public": {**public, "execution_status": "succeeded", "event_key": event_key}}
        return NormalizedTransaction(tx_hash=signature, chain=self.chain, from_address=sender or "", to_address=recipient or "",
            value_native=amount, token_symbol=symbol, timestamp=_timestamp(block_time), block_number=str(slot or ""),
            fee=atomic_amount(transaction.get("meta", {}).get("fee", 0), 9),
            direction=direction, source_api="solana-json-rpc", raw_payload=payload,
            asset_contract=mint)
