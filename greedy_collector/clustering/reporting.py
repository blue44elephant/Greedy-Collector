"""Render only explicit immutable case pins, never current cluster state."""
import json
from .domain import DISCLAIMER

def cluster_lines(entities):
    lines = []
    for entity in entities:
        if entity.get("entity_type") != "technical_cluster": continue
        pin = (entity.get("metadata_json") or {}).get("cluster_pin")
        if not isinstance(pin, dict):
            lines.extend(["Technical cluster pin unavailable; do not infer current membership."])
            continue
        lines.extend(["", "## Technical cluster", f"{pin['id']} / {pin['chain']} / version {pin['version']}",
            f"Heuristic: {pin['heuristic']}", DISCLAIMER, pin['limitations'],
            "These addresses are grouped by the UTXO common-input heuristic, subject to the listed exclusions and limitations.",
            "Members: " + ", ".join(pin['members']), "Direct evidence (shared-input sets; other membership is transitive):"])
        for evidence in pin['evidence']:
            lines.append(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return lines
