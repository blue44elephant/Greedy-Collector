"""Conservative stored-UTXO checks; no network or identity inference."""
from collections import Counter
from ..chains import get_chain
from .domain import HEURISTIC, fingerprint

CHECKS = {"complete_prevouts": True, "confirmed_only": True, "high_input_count": 20,
          "high_output_count": 20, "equal_outputs_minimum": 3, "equal_outputs_distinct_inputs": 3}

def evaluate(chain, tx_hash, payload, warnings=()):
    adapter = get_chain(chain).adapter()
    reasons, addresses = [], set()
    if not isinstance(payload, dict) or (not isinstance(payload.get("txid"), str) or payload["txid"].lower() != tx_hash):
        reasons.append("inconsistent_transaction_id")
    inputs = payload.get("vin") if isinstance(payload, dict) else None
    outputs = payload.get("vout") if isinstance(payload, dict) else None
    status = payload.get("status", {}) if isinstance(payload, dict) else {}
    status = status if isinstance(status, dict) else {}
    if not isinstance(inputs, list) or not inputs or not isinstance(outputs, list) or not outputs:
        reasons.append("incomplete_input_output_data")
    inputs = inputs if isinstance(inputs, list) else []
    outputs = outputs if isinstance(outputs, list) else []
    values = []
    for item in inputs:
        if not isinstance(item, dict) or item.get("is_coinbase"):
            reasons.append("coinbase_or_incomplete_prevout")
            continue
        prev = item.get("prevout")
        if not isinstance(prev, dict) or type(prev.get("value")) is not int or prev["value"] < 0:
            reasons.append("incomplete_prevout")
            continue
        try:
            value = prev.get("scriptpubkey_address")
            if not isinstance(value, str): raise ValueError()
            adapter.validate_address(value)
            addresses.add(adapter.normalize_address(value))
        except ValueError:
            reasons.append("unresolved_input_address")
    for output in outputs:
        value = output.get("value") if isinstance(output, dict) else None
        if type(value) is not int or value < 0:
            reasons.append("incomplete_output_value")
        else:
            values.append(value)
    if status.get("confirmed") is not True:
        reasons.append("unconfirmed_or_unknown_status")
    if len(inputs) >= CHECKS["high_input_count"] or len(outputs) >= CHECKS["high_output_count"]:
        reasons.append("collaborative_spend_possible")
    if len(addresses) >= 3 and any(value > 0 and count >= 3 for value, count in Counter(values).items()):
        reasons.append("coinjoin_like")
    if len(addresses) < 2:
        reasons.append("fewer_than_two_distinct_inputs")
    block = status.get("block_height")
    timestamp = status.get("block_time")
    material = {"chain": chain, "tx_hash": tx_hash, "heuristic": HEURISTIC,
        "inputs": sorted(addresses), "input_count": len(inputs), "output_count": len(outputs),
        "block": block if type(block) is int and block >= 0 else None,
        "timestamp": timestamp if type(timestamp) is int and timestamp >= 0 else None,
        "checks": CHECKS, "automatic_exclusions": sorted(set(reasons)),
        "counter_indicators": sorted(warnings),
        # Commit to full input/output structure without leaking arbitrary provider strings.
        "source_fingerprint": fingerprint(payload)}
    return material

def components(evidence):
    """Union hyperedges in O(input memberships * inverse Ackermann); no pair expansion."""
    parent = {}
    size = {}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for item in evidence:
        members = item["inputs"]
        for a in members:
            if a not in parent: parent[a], size[a] = a, 1
        if not members: continue
        for a in members[1:]:
            root, other = find(members[0]), find(a)
            if root == other: continue
            if size[root] < size[other]: root, other = other, root
            parent[other] = root
            size[root] += size[other]
    groups = {}
    for a in sorted(parent): groups.setdefault(find(a), []).append(a)
    return sorted((group for group in groups.values() if len(group) >= 2), key=lambda group: group[0])
