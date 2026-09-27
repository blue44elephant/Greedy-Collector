"""CL-1 policy constants and deterministic material identity."""
import hashlib
import json

HEURISTIC = "utxo_common_input_v1"
CHAINS = ("bitcoin", "litecoin")
DISCLAIMER = "Technical clustering indicates heuristic relationships, not confirmed common ownership."
LIMITATION = "PayJoin, shared control and custodial/collaborative spends can evade structural checks. Additional blockchain collection may be required; only stored records are analyzed."
MAX_ROWS = 5000
MAX_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 500
MAX_EVIDENCE = 1000
GRAPH_LIMIT = 100

class ClusteringError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def material_fingerprint(snapshot):
    # Audit capture time is retained but never changes material version identity.
    material = json.loads(json.dumps(snapshot))
    for evidence in material.get("evidence", []):
        exclusion = evidence.get("analyst_exclusion")
        if exclusion: exclusion.pop("timestamp", None)
    return fingerprint(material)
