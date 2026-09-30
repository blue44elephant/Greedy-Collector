"""Collection contract helpers. Metadata lives beside retained raw provider evidence."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re


def atomic_integer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]{1,256}", str(value)):
        from .chains.base import ChainDataError
        raise ChainDataError("malformed_response")
    return int(value)


def decimals_or_none(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]{1,3}", str(value)):
        return None
    result = int(value)
    return result if 0 <= result <= 255 else None


def atomic_amount(value, decimals):
    """Decimal tuple construction is exact even beyond the ambient precision."""
    number = atomic_integer(value)
    if type(decimals) is not int or not 0 <= decimals <= 255:
        from .chains.base import ChainDataError
        raise ChainDataError("malformed_response")
    text = format(Decimal((0, tuple(map(int, str(number))), -decimals)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def utc_timestamp(value, *, milliseconds=False):
    if value in (None, "", 0, "0") and not isinstance(value, bool):
        return None
    from .chains.base import ChainDataError
    try:
        count = atomic_integer(value)
        seconds, remainder = divmod(count, 1000 if milliseconds else 1)
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds, milliseconds=remainder)
    except (OverflowError, ValueError):
        raise ChainDataError("malformed_response") from None


def public_metadata(tx):
    raw = tx.get("raw_payload", {}) if isinstance(tx, dict) else tx.raw_payload
    return raw.get("_public", {}) if isinstance(raw, dict) and isinstance(raw.get("_public", {}), dict) else {}


def execution_status(tx):
    from .chains import get_chain
    read = tx.get if isinstance(tx, dict) else lambda key, default=None: getattr(tx, key, default)
    raw = read("raw_payload", {}) or {}
    pub = public_metadata(tx)
    status = read("execution_status") or pub.get("execution_status")
    # Raw explicit failure always wins, including older stored observations.
    if str(raw.get("isError", "")) == "1" or str(raw.get("txreceipt_status", "")) == "0":
        return "failed"
    provider = raw.get("provider", raw)
    ret = provider.get("ret", []) if isinstance(provider, dict) else []
    if ret and any(isinstance(r, dict) and r.get("contractRet") not in (None, "SUCCESS") for r in ret):
        return "failed"
    if status in ("failed", "succeeded", "unknown", "unavailable"):
        return status
    if str(raw.get("isError", "")) == "0" or str(raw.get("txreceipt_status", "")) == "1":
        return "succeeded"
    if ret and all(isinstance(r, dict) and r.get("contractRet") == "SUCCESS" for r in ret):
        return "succeeded"
    if read("chain") and get_chain(read("chain")).family.value == "utxo":
        return "not_applicable"
    if read("source_api") in ("etherscan_token", "trongrid_trc20") and read("block_number"):
        return "succeeded"
    return "unknown"


def transfer_eligible(tx):
    read = tx.get if isinstance(tx, dict) else lambda key, default=None: getattr(tx, key, default)
    pub = public_metadata(tx)
    return (execution_status(tx) not in ("failed", "unavailable")
            and pub.get("asset_type") != "unsupported"
            and not ("asset_id" in pub and pub["asset_id"] is None)
            and read("value_native") not in (None, ""))


def prepare_event(tx, *, requested_chain=None, retrieved_at=None):
    """Shared manual/monitoring persistence boundary; no provider calls or DB reads."""
    from .chains import get_chain
    from .transaction_identity import build_event_key
    d = get_chain(tx.chain)
    if requested_chain is not None and requested_chain != tx.chain:
        raise ValueError("Collection chain mismatch")
    adapter = d.adapter()
    tx.tx_hash = adapter.normalize_transaction_id(tx.tx_hash)
    tx.from_address = adapter.address_key(tx.from_address) if tx.from_address else ""
    tx.to_address = adapter.address_key(tx.to_address) if tx.to_address else ""
    if tx.asset_contract:
        tx.asset_contract = adapter.address_key(tx.asset_contract)
    if tx.timestamp:
        tx.timestamp = tx.timestamp.replace(tzinfo=timezone.utc) if tx.timestamp.tzinfo is None else tx.timestamp.astimezone(timezone.utc)
    pub = dict(public_metadata(tx))
    token = bool(tx.asset_contract) or pub.get("asset_type") in ("erc20", "trc10", "trc20", "spl_token", "token2022") or tx.source_api.endswith(("_token", "_trc20"))
    asset = tx.chain + ":token:" + tx.asset_contract if tx.asset_contract else None if token or pub.get("asset_type") == "unsupported" else tx.chain + ":native"
    pub.update(asset_id=asset, execution_status=execution_status(tx))
    pub.setdefault("asset_type", "token" if token else "native")
    pub.setdefault("token_decimals", None if token else d.native_decimals)
    pub.setdefault("raw_value", None)
    status = tx.raw_payload.get("status", {})
    if d.family.value == "utxo":
        finality = "confirmed" if status.get("confirmed") is True or (status.get("confirmed") is None and tx.block_number) else "unconfirmed"
    elif tx.chain == "solana":
        finality = pub.get("finality", "confirmed" if tx.block_number else "unknown")
    else:
        finality = "confirmed" if pub.get("confirmed") is True else "included" if tx.block_number else "unknown"
    pub.setdefault("finality", finality)
    tx.raw_payload = {**tx.raw_payload, "_public": pub, "_collection": {
        "chain": tx.chain, "provider": tx.source_api,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
        "event_key": build_event_key(tx),
    }}
    return tx


def validate_collection(transactions, *, requested_chain=None):
    """Return explicit diagnostics; never silently repair questionable records."""
    from .chains import get_chain
    from .transaction_identity import build_event_key
    issues, seen = [], set()
    for index, tx in enumerate(transactions):
        codes = []
        try:
            definition = get_chain(tx.chain)
            if requested_chain and tx.chain != requested_chain: codes.append("chain_mismatch")
            if not definition.adapter().identify_transaction(tx.tx_hash): codes.append("invalid_transaction_identifier")
            identity = (tx.chain, tx.tx_hash, build_event_key(tx))
            if identity in seen: codes.append("duplicate_event_identity")
            seen.add(identity)
            pub = public_metadata(tx)
            if pub.get("asset_type") in ("erc20", "trc20", "spl_token", "token2022") and not tx.asset_contract:
                codes.append("missing_asset_identity")
            if tx.asset_contract and tx.value_native and decimals_or_none(pub.get("token_decimals")) is None:
                codes.append("missing_token_scaling")
            if tx.value_native:
                amount = Decimal(tx.value_native)
                if not amount.is_finite() or amount < 0: codes.append("invalid_amount")
            if execution_status(tx) == "succeeded" and pub.get("asset_type") != "unsupported":
                if not tx.from_address or not tx.to_address:
                    codes.append("incomplete_transfer_participants")
                else:
                    try:
                        definition.adapter().validate_address(tx.from_address)
                        definition.adapter().validate_address(tx.to_address)
                    except ValueError: codes.append("invalid_transfer_participants")
        except (ValueError, TypeError, InvalidOperation):
            codes.append("invalid_normalized_record")
        if codes: issues.append({"record": index, "issues": codes})
    return issues


def collection_summary(adapter, transactions, *, stored_new=0, reused=0):
    streams = getattr(adapter, "collection_streams", {})
    statuses = [s.get("status") for s in streams.values()]
    status = "PARTIAL" if any(s in ("PARTIAL", "UNAVAILABLE") for s in statuses) else "TRUNCATED" if "TRUNCATED" in statuses else "PROVIDER_LIMITED" if "PROVIDER_LIMITED" in statuses or not streams else "COMPLETE_WITHIN_REQUESTED_BOUND"
    return {"chain": adapter.chain, "status": status, "partial": status == "PARTIAL",
        "truncated": "TRUNCATED" in statuses, "streams": streams,
        "records_returned": len(transactions), "native_records": sum(not tx.asset_contract and not tx.source_api.endswith(("_token", "_trc20")) for tx in transactions),
        "token_records": sum(bool(tx.asset_contract) or tx.source_api.endswith(("_token", "_trc20")) for tx in transactions),
        "failed_records": sum(execution_status(tx) == "failed" for tx in transactions),
        "stored_new": stored_new, "existing_reused": reused,
        "integrity_issues": validate_collection(transactions, requested_chain=adapter.chain)}


def utxo_participants(tx):
    """Structural participants only; never allocate an input amount to an output."""
    read = tx.get if isinstance(tx, dict) else lambda key, default=None: getattr(tx, key, default)
    raw = read("raw_payload", {}) or {}
    from .chains import get_chain
    adapter = get_chain(read("chain")).adapter()
    if "vin" not in raw or "vout" not in raw:
        return ([read("from_address")] if read("from_address") else []), ([read("to_address")] if read("to_address") else [])
    inputs, outputs = [], []
    for item in raw.get("vin", []):
        previous = item.get("prevout") if isinstance(item, dict) else None
        address = previous.get("scriptpubkey_address") if isinstance(previous, dict) else None
        if isinstance(address, str) and address: inputs.append(adapter.address_key(address))
    for item in raw.get("vout", []):
        address = item.get("scriptpubkey_address") if isinstance(item, dict) else None
        if isinstance(address, str) and address: outputs.append(adapter.address_key(address))
    return sorted(set(inputs)), sorted(set(outputs))
