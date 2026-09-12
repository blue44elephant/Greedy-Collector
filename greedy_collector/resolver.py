"""Local syntax resolution only; provider retrieval is a separate operation."""
import re

from .chains import BitcoinAdapter, EthereumAdapter

SUPPORTED = ["Bitcoin address", "Ethereum address", "Bitcoin transaction ID", "Ethereum transaction hash"]


def resolve_identifier(value: str) -> dict:
    normalized = value.strip()
    # Exact transaction syntax takes precedence over the permissive address
    # validators. In particular, bare 64-hex values are Bitcoin transaction IDs.
    for chain, pattern in [("ethereum", r"0x[0-9a-fA-F]{64}"), ("bitcoin", r"[0-9a-fA-F]{64}")]:
        if re.fullmatch(pattern, normalized):
            return {"kind": "transaction", "chain": chain, "normalized": normalized.lower(), "lookup_type": "transaction"}
    for adapter in [BitcoinAdapter(), EthereumAdapter()]:
        try:
            address = adapter.validate_address(normalized)
        except ValueError:
            continue
        return {"kind": "address", "chain": adapter.chain, "normalized": address, "lookup_type": "address"}
    # Do not echo arbitrary input (which could contain accidentally pasted secrets).
    return {"kind": "unknown", "supported": SUPPORTED,
            "message": "Greedy Collector could not identify this value as a supported wallet address or transaction hash."}
