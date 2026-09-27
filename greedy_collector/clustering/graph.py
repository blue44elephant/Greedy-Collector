"""Bounded membership/hyperedge view; never fabricate transitive transaction edges."""
from .domain import GRAPH_LIMIT

def graph_view(snapshot, offset=0, limit=GRAPH_LIMIT):
    members = snapshot["members"]
    visible = set(members[offset:offset + limit])
    return {"cluster_id": snapshot["id"], "version": snapshot["version"], "chain": snapshot["chain"],
        "members": sorted(visible), "total_members": len(members), "offset": offset,
        "next_offset": offset + limit if offset + limit < len(members) else None,
        "review_required": snapshot["status"] == "review_required",
        # Each hyperedge states exactly which inputs co-occurred. No O(n^2) clique.
        "direct_evidence": [{"id": e["id"], "tx_hash": e["tx_hash"], "inputs": sorted(visible.intersection(e["inputs"])),
                             "total_inputs": len(e["inputs"])} for e in snapshot["evidence"] if not e["excluded"] and visible.intersection(e["inputs"])][:GRAPH_LIMIT],
        "evidence_total": sum(not e["excluded"] for e in snapshot["evidence"]),
        "evidence_detail": "All underlying records are available in the version endpoint.",
        "disclaimer": snapshot["disclaimer"]}
