"""Pure deterministic comparison and bounded network metrics."""
from collections import deque
from hashlib import sha256
import json
import unicodedata
from urllib.parse import urlsplit

ALGORITHM = "narc1-mo-1"
GRAPH_ALGORITHM = "narc1-nexus-1"
PRIORITY_ALGORITHM = "narc1-priority-brandes-1"
DISCLAIMER = ("Potential cross-Case linkage requires analyst review. MO similarity is the weighted match fraction of comparable attributes, not an identity probability. "
    "Technical clusters do not establish ownership. Network Priority measures structural importance in the selected bounded network; it is not Risk, criminality, or leadership probability. "
    "Chronology does not establish causation. No enforcement recommendations are generated.")
WEIGHTS = {"wallet": 40, "vendor_alias": 20, "domain": 20, "marketplace_account": 20,
    "marketplace": 4, "platform": 2, "payment_method": 2, "logistics_method": 2,
    "origin_country": 1, "origin_region": 1, "origin_city": 1,
    "destination_country": 1, "destination_region": 1, "destination_city": 1,
    "concealment": 2, "packaging": 2, "delivery_method": 2, "drop_method": 2,
    "recipient_pattern": 2, "sender_pattern": 2, "mo_tag": 2,
    "substance": 2, "precursor": 2, "pre_precursor": 2}
STRONG_FIELDS = {"wallet", "vendor_alias", "domain", "marketplace_account"}

def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())

def known(value):
    return bool(value.strip()) and normalized(value) not in {"unknown", "not known", "n/a"}

def weights_for(overrides):
    if set(overrides) - WEIGHTS.keys() or any(type(v) is not int or not 1 <= v <= 100 for v in overrides.values()):
        raise ValueError("Weights must use supported attributes and integers from 1 to 100")
    return {**WEIGHTS, **overrides}

def compare(a, b):
    """Equal weight configuration required; generic total capped below one strong contradiction."""
    if a["weights"] != b["weights"]: raise ValueError("Fingerprint weights differ")
    rows, numerator, denominator = [], 0, 0
    comparable = []
    for key, weight in a["weights"].items():
        left, right = a["attributes"].get(key, []), b["attributes"].get(key, [])
        raw_left, raw_right = {x["value"] for x in left}, {x["value"] for x in right}
        matches = {x["normalized"] for x in left} & {x["normalized"] for x in right}
        state = "UNKNOWN" if not left or not right else "EXACT MATCH" if raw_left & raw_right else "NORMALIZED MATCH" if matches else "NO MATCH"
        row = {"field": key, "state": state, "weight": weight, "effective_weight": 0,
            "matched_weight": 0, "matched_values": sorted(matches), "case_a": left, "case_b": right}
        rows.append(row)
        if state != "UNKNOWN": comparable.append(row)
    # Weak attributes collectively have less weight than ANY comparable strong field.
    strong = [r["weight"] for r in comparable if r["field"] in STRONG_FIELDS]
    weak_sum = sum(r["weight"] for r in comparable if r["field"] not in STRONG_FIELDS)
    factor = min(1, min(strong) * .5 / weak_sum) if strong and weak_sum else 1
    for row in comparable:
        weight = row["weight"] * (1 if row["field"] in STRONG_FIELDS else factor)
        row["effective_weight"] = weight
        row["matched_weight"] = weight if row["state"] in ("EXACT MATCH", "NORMALIZED MATCH") else 0
        numerator += row["matched_weight"]; denominator += weight
    return {"score": round(100 * numerator / denominator, 2) if denominator else None,
        "comparable_field_count": len(comparable), "matched_field_count": sum(r["matched_weight"] > 0 for r in rows),
        "matched_weight": round(numerator, 6), "denominator": round(denominator, 6),
        "weak_weight_factor": factor, "contributions": rows, "algorithm_version": ALGORITHM,
        "fingerprints": [a["id"], b["id"]], "disclaimer": DISCLAIMER}

def temporal(a, b):
    if not all(a.get(k) and b.get(k) for k in ("period_start", "period_end")): return "UNKNOWN"
    if a["period_end"] < b["period_start"]: return "BEFORE"
    if b["period_end"] < a["period_start"]: return "AFTER"
    return "OVERLAPPING"

def priority(graph):
    """Undirected structural Brandes betweenness, O(VE), at most 300 nodes/1200 edges."""
    adjacency = {n["id"]: set() for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["source"] != e["target"]:
            adjacency[e["source"]].add(e["target"]); adjacency[e["target"]].add(e["source"])
    centrality = dict.fromkeys(adjacency, 0.0)
    for start in sorted(adjacency):
        stack, queue = [], deque([start])
        predecessors = {v: [] for v in adjacency}
        paths = dict.fromkeys(adjacency, 0); paths[start] = 1
        distance = dict.fromkeys(adjacency, -1); distance[start] = 0
        while queue:
            v = queue.popleft(); stack.append(v)
            for w in sorted(adjacency[v]):
                if distance[w] < 0: queue.append(w); distance[w] = distance[v] + 1
                if distance[w] == distance[v] + 1: paths[w] += paths[v]; predecessors[w].append(v)
        delta = dict.fromkeys(adjacency, 0.0)
        while stack:
            w = stack.pop()
            for v in predecessors[w]: delta[v] += paths[v] / paths[w] * (1 + delta[w])
            if w != start: centrality[w] += delta[w]
    scale = (len(adjacency) - 1) * (len(adjacency) - 2)
    output = []
    for node in graph["nodes"]:
        edges = [e for e in graph["edges"] if node["id"] in (e["source"], e["target"])]
        cases = sorted(set(node["case_ids"]))
        # Distinct preserved source identities, never repeated analyst assertions.
        def source_group(value):
            host = urlsplit(value).hostname if value.startswith(("http://", "https://")) else None
            return "public:" + host.lower() if host else "observation:" + value
        sources = sorted({source_group(p["source_identity"]) for e in edges for p in e["provenance"] if p.get("source_identity")})
        strong = sum(e.get("strength") == "STRONG" and e.get("review_status") == "RELEVANT" for e in edges)
        weight = sum({"STRONG": 4, "MODERATE": 2, "WEAK": 1, "CONTEXT_ONLY": .25}.get(e.get("strength"), 1) for e in edges)
        between = centrality[node["id"]] / scale if scale > 0 else 0
        times = sorted({p["observed_at"] for e in edges for p in e["provenance"] if p.get("observed_at")})
        score = min(100, (len(cases)-1)*20 + min(20, len(sources)*4) + min(20, between*100) + min(10,strong*2))
        output.append({"node_id": node["id"], "label": node["label"], "node_type": node["type"],
            "case_count": len(cases), "degree": len(adjacency[node["id"]]), "weighted_degree": weight,
            "independent_source_count": len(sources), "source_identities": sources,
            "betweenness": round(between, 6), "reviewed_strong_links": strong,
            "recurrence": {"first": times[0] if times else None, "last": times[-1] if times else None},
            "score": score, "category": "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW",
            "reasons": [f"Present in {len(cases)} selected Cases", f"{len(sources)} distinct preserved public/blockchain source references",
                f"Degree {len(adjacency[node['id']])}; normalized structural betweenness {between:.6f}",
                f"{strong} reviewed strong links", "Observation times unavailable" if not times else f"Observed {times[0]} through {times[-1]}"]})
    return sorted(output, key=lambda r: (-r["score"], -r["betweenness"], r["node_id"]))
