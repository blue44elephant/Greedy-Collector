"""Stable, generic identity for normalized blockchain activity events."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_EVENT_INDEX = (1 << 64) - 1
MAX_EVENT_KEY_LENGTH = 160
_EVENT_ID = re.compile(r"[a-z0-9_-]{1,24}:[0-9a-f]{64}\Z")
_STABLE_EVENT_KEY = re.compile(r"solana-(?:ix:[0-9]{1,20}|inner:[0-9]{1,20}:[0-9]{1,20})\Z")


def normalize_event_index(value: Any) -> str | None:
    """Return a canonical decimal protocol index, rejecting malformed values."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid provider event index")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and len(value) <= 20:
        if re.fullmatch(r"[0-9]+", value):
            number = int(value, 10)
        elif re.fullmatch(r"0x[0-9a-fA-F]{1,16}", value):
            number = int(value, 16)
        else:
            raise ValueError("Invalid provider event index")
    else:
        raise ValueError("Invalid provider event index")
    if number < 0 or number > MAX_EVENT_INDEX:
        raise ValueError("Invalid provider event index")
    return str(number)


def _get(value: Any, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _digest(material: Any) -> str:
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def legacy_event_key(value: Any, *, prefix: str = "legacy") -> str:
    """Deterministic compatibility key for an old normalized activity tuple."""
    material = [_get(value, key) for key in (
        "chain", "tx_hash", "from_address", "to_address", "value_native", "token_symbol", "asset_contract"
    )]
    return f"{prefix}:{_digest(material)}"


def build_event_key(value: Any) -> str:
    """Derive a bounded event key from normalized fields and validated provider metadata."""
    chain = _get(value, "chain", "")
    payload = _get(value, "raw_payload", {})
    payload = payload if isinstance(payload, dict) else {}

    stable_key = payload.get("_stable_event_key")
    if isinstance(stable_key, str) and _STABLE_EVENT_KEY.fullmatch(stable_key):
        return stable_key

    if chain in ("bitcoin", "litecoin"):
        if payload.get("_wallet_view") is not None:
            return "activity:" + _digest([chain, payload["_wallet_view"]])
        # Bitcoin rows are wallet-relative normalized activities. This preserves
        # the former tuple dedupe semantics while allowing multiple outputs/views.
        return legacy_event_key(value, prefix="activity")

    contract = _get(value, "asset_contract")
    if contract is not None:
        if (not isinstance(contract, str) or not contract or len(contract) > 128
                or any(ch.isspace() or ord(ch) < 32 for ch in contract)):
            raise ValueError("Invalid normalized asset contract")
    provider_event = payload.get("_event_id")
    if isinstance(provider_event, str) and _EVENT_ID.fullmatch(provider_event):
        return "provider:" + provider_event

    index = normalize_event_index(_get(value, "event_index"))
    if index is not None:
        return "evm-log:" + index

    source = _get(value, "source_api", "")
    if contract is not None or source in {"etherscan_token", "trongrid_trc20"}:
        # Without a protocol position, distinguish available contract metadata,
        # but do not invent ordering for otherwise identical provider events.
        public = payload.get("_public", {})
        raw_amount = public.get("raw_value") if isinstance(public, dict) else None
        material = [_get(value, key) for key in ("chain", "tx_hash", "from_address", "to_address")]
        material += [raw_amount if raw_amount is not None else _get(value, "value_native"), contract]
        return "legacy:" + _digest(material)
    return "tx"


def event_identity(value: Any, event_key: str | None = None) -> str:
    """Cursor/graph identity; preserve established Bitcoin and TRON identifiers."""
    if isinstance(value, dict) and isinstance(value.get("event_identity"), str):
        return value["event_identity"]
    if isinstance(value, dict) and isinstance(value.get("event_id"), str) and _EVENT_ID.fullmatch(value["event_id"]):
        return value["event_id"]
    chain = _get(value, "chain", "")
    tx_hash = _get(value, "tx_hash", "")
    if chain == "bitcoin":
        return tx_hash
    payload = _get(value, "raw_payload", {})
    payload = payload if isinstance(payload, dict) else {}
    stable_key = payload.get("_stable_event_key")
    if isinstance(stable_key, str) and _STABLE_EVENT_KEY.fullmatch(stable_key):
        return f"{chain}:{tx_hash}:{stable_key}"
    provider_event = payload.get("_event_id")
    if isinstance(provider_event, str) and _EVENT_ID.fullmatch(provider_event):
        return provider_event
    key = event_key or build_event_key(value)
    return tx_hash if key == "tx" else f"{chain}:{tx_hash}:{key}"


def persist_normalized_event(db, tx) -> tuple[Any, bool]:
    """Insert once by stable event key, upgrading a matching legacy row in place."""
    from sqlalchemy import or_, select
    from .models import Transaction

    event_key = build_event_key(tx)
    if len(event_key) > MAX_EVENT_KEY_LENGTH:
        raise ValueError("Normalized event key exceeds its storage limit")
    fields = tx.model_dump() if hasattr(tx, "model_dump") else tx.dict()
    fields["event_key"] = event_key
    fields["event_index"] = normalize_event_index(fields.get("event_index"))
    fields["asset_contract"] = fields.get("asset_contract")
    row = db.scalar(select(Transaction).where(
        Transaction.chain == tx.chain, Transaction.tx_hash == tx.tx_hash,
        Transaction.event_key == event_key,
    ))
    if row is not None:
        # Refresh observation/finality in place; preserve primary key and Case references.
        old = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        current = fields.get("raw_payload", {})
        if current:
            fields["raw_payload"] = {**old, **current}
        for key, value in fields.items():
            if key not in ("event_key", "chain", "tx_hash") and (value not in (None, "") or key in ("timestamp", "block_number", "fee", "value_native")):
                setattr(row, key, value)
        return row, False

    if tx.chain in ("bitcoin", "litecoin") and "_wallet_view" in tx.raw_payload:
        older = db.scalars(select(Transaction).where(Transaction.chain == tx.chain,
            Transaction.tx_hash == tx.tx_hash, Transaction.value_native == tx.value_native,
            Transaction.direction == tx.direction)).all()
        older = [r for r in older if "_wallet_view" not in (r.raw_payload or {})]
        if len(older) == 1:
            row = older[0]
            for key, value in fields.items(): setattr(row, key, value)
            db.flush([row])
            return row, False

    # If a legacy provider record is re-ingested with richer identity metadata,
    # upgrade its row in place, preserving its primary key and references.
    filters = [
        Transaction.chain == tx.chain, Transaction.tx_hash == tx.tx_hash,
        Transaction.from_address == tx.from_address, Transaction.to_address == tx.to_address,
        Transaction.value_native == tx.value_native, Transaction.token_symbol == tx.token_symbol,
        Transaction.event_key.like("legacy:%"),
    ]
    contract = fields.get("asset_contract")
    if contract is None:
        filters.append(Transaction.asset_contract.is_(None))
    else:
        filters.append(or_(Transaction.asset_contract.is_(None), Transaction.asset_contract == contract))
    candidates = db.scalars(select(Transaction).where(*filters)).all()
    if len(candidates) == 1:
        row = candidates[0]
        row.event_key = event_key
        row.event_index = fields.get("event_index") or row.event_index
        row.asset_contract = contract or row.asset_contract
        if not row.raw_payload and fields.get("raw_payload"):
            row.raw_payload = fields["raw_payload"]
        return row, False

    row = Transaction(**fields)
    db.add(row)
    db.flush([row])
    return row, True
