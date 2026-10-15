"""Project explicit Case facts and historical pins, never current provider results."""
from sqlalchemy import select
from ..models import CaseEntity, AnalystNote
from ..cases import data
from ..chains import get_chain
from ..attribution.handoff import safe_snapshot
from .domain import normalized, known

def wallet_key(chain, address):
    return chain + ":" + get_chain(chain).adapter().normalize_address(address)

def project(db, case, profile):
    objects = []
    def add(kind, value, provenance, *, eligible=True, metadata=None, exact=False):
        if not isinstance(value, str) or not known(value): return
        canonical = value if exact else normalized(value)
        item = {"kind": kind, "value": value, "normalized": canonical, "provenance": provenance,
            "eligible": eligible, "metadata": metadata or {}}
        if item not in objects: objects.append(item)
    def manual_provenance(p, reference):
        source = p.get("source_snapshot") or {}
        m = source.get("metadata_json") or {}
        capture = (m.get("public_source_capture_pin") or {}).get("capture") or {}
        return {**p, "case_id": case.id, "profile_id": profile["id"], "reference": reference,
                "source_identity": capture.get("final_url") or capture.get("requested_url"),
                "observed_at": capture.get("retrieved_at"),
                "verification": "analyst-entered; not automatically verified"}
    if profile:
        for key, facts in profile["fields"].items():
            for i, fact in enumerate(facts):
                # Case-derived assertions backed only by an unreviewed Discovery run stay context.
                p = fact["provenance"]
                source = p.get("source_snapshot") or {}
                pin = (source.get("metadata_json") or {}).get("broad_discovery_pin") or {}
                eligible = p["kind"] != "discovery_result" or any(c.get("status") == "relevant" and c.get("value") == fact["value"] for c in pin.get("candidates", []))
                add(key, fact["value"], manual_provenance(p, f"fields.{key}.{i}"), eligible=eligible, exact=key in ("vendor_alias", "marketplace_account"))
        for i, wallet in enumerate(profile["wallets"]):
            add("wallet", wallet_key(wallet["chain"], wallet["address"]), manual_provenance(wallet["provenance"], f"wallets.{i}"),
                metadata={"chain": wallet["chain"], "address": wallet["address"]}, exact=True)
        for row in profile["substances"]:
            add(row["kind"], row["category"] or row["source_name"], manual_provenance(row["provenance"], row["id"]), metadata=row)
        for row in profile["logistics"]:
            provenance = manual_provenance(row["provenance"], row["id"])
            add("consignment", row["id"], provenance, metadata=row, exact=True)
            for key, facts in row["fields"].items():
                for fact in facts: add(key, fact["value"], manual_provenance(fact["provenance"], row["id"]), metadata={"consignment_id": row["id"]}, exact=key in ("vendor_alias", "marketplace_account"))
            for wallet in row["wallets"]:
                add("wallet", wallet_key(wallet["chain"], wallet["address"]), manual_provenance(wallet["provenance"], row["id"]),
                    metadata={"chain": wallet["chain"], "address": wallet["address"], "consignment_id": row["id"]}, exact=True)
    references = db.scalars(select(CaseEntity).where(CaseEntity.case_id == case.id).order_by(CaseEntity.id)).all()
    for row in references:
        m = row.metadata_json or {}
        p = {"kind": "case_reference", "case_id": case.id, "reference_id": row.id,
             "reference": row.entity_ref, "recorded_at": data(row).get("added_at"),
             "observed_at": (m.get("transaction_snapshot") or {}).get("timestamp"), "verification": "stored Case reference"}
        if row.entity_type in ("wallet", "transaction") and m.get("chain"):
            try:
                chain = m["chain"]
                value = wallet_key(chain, row.entity_ref) if row.entity_type == "wallet" else chain + ":" + get_chain(chain).adapter().normalize_transaction_id(row.entity_ref)
                add(row.entity_type, value, p, metadata={"chain": chain, "address" if row.entity_type == "wallet" else "tx_hash": row.entity_ref,
                    "event_key": m.get("event_key"), "snapshot": m.get("transaction_snapshot")}, exact=True)
            except ValueError: pass  # Unknown legacy reference is not promoted into an exact identity.
        cluster = m.get("cluster_pin")
        if cluster and cluster.get("chain") in ("bitcoin", "litecoin"):
            cp = {**p, "kind": "technical_cluster", "cluster_id": cluster["id"], "version": cluster["version"], "fingerprint": cluster.get("fingerprint")}
            add("technical_cluster", f"{cluster['chain']}:{cluster['id']}:v{cluster['version']}", cp, metadata=cluster, exact=True)
            for member in cluster.get("members", []):
                add("cluster_member", wallet_key(cluster["chain"], member), cp, metadata={"chain": cluster["chain"], "address": member,
                    "cluster_key": f"{cluster['chain']}:{cluster['id']}:v{cluster['version']}"}, exact=True)
        attr = m.get("attribution_pin")
        if attr:
            claim = attr.get("claim") or {}
            # Identity is an explicit entity UUID; name resemblance is never sufficient.
            add("entity", attr["entity"]["id"], {**p, "kind": "attribution_evidence", "entity_id": attr["entity"]["id"],
                "claim": claim, "evidence_state": attr.get("links", [])}, eligible=claim.get("assessment") == "supported" and not claim.get("needs_review"),
                metadata={"label": attr["entity"]["canonical_name"], "claim": claim, "links": attr.get("links", [])}, exact=True)
        broad = m.get("broad_discovery_pin")
        if broad:
            for candidate in broad.get("candidates", []):
                if candidate.get("kind") not in ("alias", "domain", "marketplace_account", "profile", "entity"): continue
                if candidate.get("status") == "irrelevant": continue
                kind = {"alias": "vendor_alias", "profile": "public_profile", "entity": "entity_candidate"}.get(candidate["kind"], candidate["kind"])
                add(kind, candidate["value"], {**p, "kind": "discovery_result", "candidate_id": candidate["id"],
                    "review_status": candidate.get("status", "unreviewed"), "source_identity": candidate.get("canonical_url"),
                    "observation_id": candidate["observation_id"]}, eligible=candidate.get("status") == "relevant", exact=kind in ("vendor_alias", "marketplace_account"))
            for group in broad.get("groups", []):
                for observation in group.get("observations", []):
                    add("discovery_source", observation["id"], {**p, "kind": "discovery_result", "source_identity": group.get("canonical_url"),
                        "review_status": observation.get("review_status"), "observed_at": observation.get("retrieved_at")},
                        metadata={"url": group.get("canonical_url"), "provider": observation.get("provider")}, exact=True)
        discovery = m.get("discovery_run_pin")
        if discovery:
            for obs in discovery.get("observations", []):
                add("discovery_source", obs["id"], {**p, "kind": "discovery_result", "source_identity": obs.get("source_url"),
                    "observed_at": obs.get("retrieved_at")}, metadata={"url": obs.get("source_url")}, exact=True)
        capture = m.get("public_source_capture_pin")
        if capture:
            c = capture["capture"]
            add("source_capture", c["id"], {**p, "kind": "public_source_capture", "source_identity": c.get("final_url") or c.get("requested_url"),
                "sha256": c.get("body_sha256"), "observed_at": c.get("retrieved_at"), "review_status": c.get("review_status")}, metadata=c, exact=True)
        flow = m.get("fund_flow_pin")
        if flow:
            for path in flow.get("paths", []):
                for step in path.get("steps", []):
                    fp = {**p, "kind": "blockchain_observation", "flow_id": flow["id"], "algorithm_version": flow["algorithm_version"],
                        "source_identity": step.get("transaction_provenance_ref") or step.get("tx_hash"), "observed_at": step.get("timestamp")}
                    for key in ("source", "target"):
                        if step.get(key):
                            try: add("counterparty", wallet_key(flow["chain"], step[key]), fp, metadata={"chain": flow["chain"], "address": step[key], "step": step}, exact=True)
                            except ValueError: pass
    return safe_snapshot(sorted(objects, key=lambda x: (x["kind"], x["normalized"], str(x["provenance"]))))
