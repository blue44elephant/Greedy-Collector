"""Explicit local commands. Immutable runs capture exact inputs and explanations."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, inspect, func, tuple_, case as sql_case, and_
from fastapi import HTTPException
from ..cases import get_case, commit, locked, data
from ..models import Case, CaseEntity, CaseEvent, AnalystNote, utcnow
from ..attribution.handoff import safe_snapshot
from .models import Profile, Substance, Logistics, Identifier, Fingerprint, LinkRun, Link, Review, Nexus, Priority
from .schemas import ProfileInput
from .domain import (ALGORITHM, GRAPH_ALGORITHM, PRIORITY_ALGORITHM, DISCLAIMER, WEIGHTS, digest,
    weights_for, normalized, known, compare, temporal, priority)
from .sources import project, wallet_key

def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid4())
def view(row): return {"id": row.id, "created_at": row.created_at, **row.record}

def profile_snapshot(db, case_id):
    # Optional extension: legacy Case workflows remain available before this migration.
    if not inspect(db.connection()).has_table("narcotics_case_profiles"): return None
    row = db.scalar(select(Profile).where(Profile.case_id == case_id).order_by(Profile.revision.desc()).limit(1))
    return view(row) if row else None

class NarcoticsService:
    def __init__(self, db):
        self.db = db
        from ..migration_state import supports_revision
        if not supports_revision(db.connection(), "20261013_01_narcotics_network_intelligence"):
            raise HTTPException(503, "Narcotics intelligence requires migration 20261013_01_narcotics_network_intelligence.")

    def writable_case(self, case_id):
        row = get_case(self.db, case_id)
        if row.archived_at: raise HTTPException(409, "Archived Cases are read-only for narcotics intelligence; restore the Case first.")
        return row

    def profile(self, case_id):
        get_case(self.db, case_id)
        return {"profile": profile_snapshot(self.db, case_id), "disclaimer": DISCLAIMER}

    def provenance(self, case_id, p):
        if p["kind"] == "analyst_entry":
            if p.get("reference_id"): raise HTTPException(422, "Analyst entries cannot claim a source reference; select the actual source kind.")
            return p
        identifier = p.get("reference_id")
        if not identifier: raise HTTPException(422, "Source-backed facts require a Case-scoped reference ID.")
        if p["kind"] == "case_note":
            note = self.db.get(AnalystNote, identifier)
            if not note or note.case_id != case_id: raise HTTPException(422, "Source note is not in this Case.")
            return {**p, "source_snapshot": data(note)}
        reference = self.db.get(CaseEntity, identifier)
        allowed = {"public_source_capture": {"public_source_capture"}, "discovery_result": {"discovery_observation", "broad_discovery", "discovery_run"},
            "attribution_evidence": {"entity", "attribution_claim"}, "sanctions_record": {"sanctions"}, "blockchain_observation": {"wallet", "transaction", "fund_flow"}}
        if p["kind"] == "sanctions_record":
            from ..models import SanctionsCasePin
            pin = self.db.get(SanctionsCasePin, identifier)
            if not pin or pin.case_id != case_id: raise HTTPException(422, "Sanctions source is not pinned to this Case.")
            return {**p, "source_snapshot": data(pin)}
        if not reference or reference.case_id != case_id or reference.entity_type not in allowed[p["kind"]]:
            raise HTTPException(422, "Source reference is not compatible with this Case and source kind.")
        return {**p, "source_snapshot": data(reference)}

    def save_profile(self, case_id, payload):
        locked(self.db)
        case = self.writable_case(case_id)
        previous = profile_snapshot(self.db, case_id)
        revision = previous["revision"] if previous else 0
        if revision != payload.expected_revision: raise HTTPException(409, "Profile changed. Reload before saving.")
        record = payload.model_dump(mode="json", exclude={"expected_revision"})
        def facts(fields):
            for values in fields.values():
                for fact in values: fact["provenance"] = self.provenance(case_id, fact["provenance"])
        def wallets(rows):
            for wallet in rows:
                try: wallet["address"] = wallet_key(wallet["chain"], wallet["address"]).split(":", 1)[1]
                except ValueError: raise HTTPException(422, "Unsupported chain-scoped wallet reference.") from None
                wallet["provenance"] = self.provenance(case_id, wallet["provenance"])
        facts(record["fields"]); wallets(record["wallets"])
        for substance in record["substances"]:
            substance.update(id=uid(), provenance=self.provenance(case_id, substance["provenance"]))
        for logistics in record["logistics"]:
            logistics.update(id=uid(), provenance=self.provenance(case_id, logistics["provenance"]))
            facts(logistics["fields"]); wallets(logistics["wallets"])
            for identifier in logistics["entity_reference_ids"]:
                ref = self.db.get(CaseEntity, identifier)
                if not ref or ref.case_id != case_id or ref.entity_type not in ("entity", "attribution_claim"):
                    raise HTTPException(422, "Logistics Entity reference is not in this Case.")
        record = safe_snapshot({**record, "case_id": case_id, "revision": revision+1,
            "source_case_version": case.version+1, "verification": "Analyst-controlled facts; source references do not automatically verify assertions."})
        row = Profile(id=uid(), case_id=case_id, revision=revision+1, created_at=now(), record=record)
        self.db.add(row); self.db.flush()
        self.db.add_all(Substance(id=s["id"], profile_id=row.id, case_id=case_id, category=s["category"], record=s) for s in record["substances"])
        self.db.add_all(Logistics(id=s["id"], profile_id=row.id, case_id=case_id, record=s) for s in record["logistics"])
        for obj in project(self.db, case, view(row)):
            if obj["kind"] in WEIGHTS:
                self.db.add(Identifier(id=uid(), profile_id=row.id, kind=obj["kind"], value=obj["normalized"]))
        case.updated_at = utcnow()
        self.db.add(CaseEvent(id=uid(), case_id=case_id, kind="narcotics_profile_saved", reference_id=row.id,
            created_at=utcnow(), record={"profile": view(row)}))
        commit(self.db)
        return view(row)

    def fingerprint(self, case_id, overrides=None):
        locked(self.db)
        case = self.writable_case(case_id)
        return self._fingerprint_for_case(case, overrides)

    def _fingerprint_for_case(self, case, overrides):
        case_id = case.id
        try: weights = weights_for(overrides or {})
        except ValueError as exc: raise HTTPException(422, str(exc)) from None
        profile = profile_snapshot(self.db, case_id)
        objects = project(self.db, case, profile)
        attributes = {key: [{k: obj[k] for k in ("value", "normalized", "provenance")} for obj in objects
            if obj["kind"] == key and obj["eligible"]] for key in weights}
        source = safe_snapshot({"case": data(case), "profile": profile, "objects": objects})
        record = {"case_id": case_id, "case_title": case.title, "algorithm_version": ALGORITHM, "weights": weights,
            "attributes": attributes, "source_case_version": case.version, "source_data_fingerprint": digest(source),
            "profile_id": profile["id"] if profile else None, "objects": objects,
            "period_start": profile.get("period_start") if profile else None, "period_end": profile.get("period_end") if profile else None,
            "disclaimer": DISCLAIMER}
        record["content_fingerprint"] = digest(record)
        row = Fingerprint(id=uid(), case_id=case_id, created_at=now(), record=record)
        self.db.add(row); self.db.flush()
        return view(row)

    def latest_review(self, link_id):
        rows = self.db.scalars(select(Review).where(Review.link_id == link_id).order_by(Review.sequence)).all()
        return {"status": rows[-1].status if rows else "UNREVIEWED", "sequence": rows[-1].sequence if rows else 0,
            "history": [view(r) for r in rows]}

    def link(self, identifier):
        row = self.db.get(Link, identifier)
        if not row: raise HTTPException(404, "Cross-Case link not found.")
        return {"id": row.id, **row.record, "review": self.latest_review(identifier)}

    def related(self, case_id, payload):
        locked(self.db); self.writable_case(case_id)
        origin = self.fingerprint(case_id, payload.weights)
        # Indexed current-profile identifiers prioritize exact technical matches in a bounded search.
        latest = select(Profile.case_id, func.max(Profile.revision).label("revision")).group_by(Profile.case_id).subquery()
        terms = sorted({(o["kind"], o["normalized"]) for o in origin["objects"] if o["kind"] in ("wallet", "vendor_alias", "domain", "marketplace_account")})
        candidates = self.db.scalars(select(Profile.case_id).join(Identifier, Identifier.profile_id == Profile.id).join(latest,
            and_(Profile.case_id == latest.c.case_id, Profile.revision == latest.c.revision)).where(
                tuple_(Identifier.kind, Identifier.value).in_(terms)).distinct().order_by(Profile.case_id).limit(1001)).all() if terms else []
        q = select(Case).where(Case.id != case_id)
        if not payload.include_archived: q = q.where(Case.archived_at.is_(None))
        if payload.case_ids is not None:
            ids = sorted(set(payload.case_ids) - {case_id})
            for i in ids: get_case(self.db, i)
            q = q.where(Case.id.in_(ids))
        cases = self.db.scalars(q.order_by(sql_case((Case.id.in_(candidates[:1000]), 0), else_=1), Case.id).limit(payload.max_cases+1)).all()
        # Archived Cases may be compared as immutable historical inputs, never edited.
        run_id, at = uid(), now()
        related, all_links = [], []
        for other in cases[:payload.max_cases]:
            target = self.fingerprint_readonly(other, payload.weights)
            similarity = compare(origin, target)
            links = self.make_links(origin, target, similarity, run_id, at)
            all_links.extend(links)
            related.append({"case_id": other.id, "title": other.title, "archived": bool(other.archived_at),
                "similarity": similarity, "temporal_relation": temporal(origin, target), "link_ids": [l["id"] for l in links],
                "counts": {s: sum(l["strength"] == s for l in links) for s in ("STRONG", "MODERATE", "WEAK", "CONTEXT_ONLY")},
                "compared_at": at})
        record = safe_snapshot({"case_id": case_id, "case_ids": [case_id] + [r["case_id"] for r in related],
            "algorithm_version": ALGORITHM, "origin_fingerprint": origin, "related_cases": related,
            "bounds": {"max_cases": payload.max_cases, "truncated": len(cases)>payload.max_cases,
                       "identifier_candidates_truncated": len(candidates)>1000,
                       "selection": "explicit IDs" if payload.case_ids is not None else "current indexed identifiers first, then stored Case ID order"}, "disclaimer": DISCLAIMER})
        self.db.add(LinkRun(id=run_id, case_id=case_id, created_at=at, record=record)); self.db.flush()
        for link in all_links:
            self.db.add(Link(id=link["id"], run_id=run_id, case_a=case_id, case_b=link["case_b"],
                link_type=link["link_type"], strength=link["strength"], record=link))
        self.db.flush()
        return self.run("case_comparison", run_id)

    def fingerprint_readonly(self, case, overrides):
        # Same command logic without archive write guard. Snapshot creation does not edit Case.
        return self._fingerprint_for_case(case, overrides)

    def make_links(self, a, b, similarity, run_id, at):
        links = []
        types = {"wallet": ("EXACT_WALLET_REUSE", "STRONG"), "vendor_alias": ("EXACT_ALIAS_REUSE", "MODERATE"),
            "domain": ("DOMAIN_REUSE", "MODERATE"), "marketplace_account": ("MARKETPLACE_ACCOUNT_REUSE", "MODERATE"),
            "technical_cluster": ("TECHNICAL_CLUSTER_OVERLAP", "STRONG"), "cluster_member": ("TECHNICAL_CLUSTER_OVERLAP", "MODERATE"),
            "counterparty": ("SHARED_COUNTERPARTY", "MODERATE"), "entity": ("ATTRIBUTION_ENTITY_OVERLAP", "MODERATE"),
            "origin_country": ("SHARED_ORIGIN", "WEAK"), "origin_region": ("SHARED_ORIGIN", "WEAK"),
            "destination_country": ("SHARED_DESTINATION", "WEAK"), "destination_region": ("SHARED_DESTINATION", "WEAK"),
            "concealment": ("SHARED_CONCEALMENT", "WEAK"), "logistics_method": ("SHARED_LOGISTICS_PATTERN", "WEAK"),
            "substance": ("SHARED_SUBSTANCE_PATTERN", "WEAK"), "precursor": ("SHARED_SUBSTANCE_PATTERN", "WEAK"),
            "pre_precursor": ("SHARED_SUBSTANCE_PATTERN", "WEAK")}
        for kind, (link_type, strength) in types.items():
            left = [o for o in a["objects"] if o["kind"] == kind]
            right = [o for o in b["objects"] if o["kind"] == kind]
            for value in sorted({o["normalized"] for o in left} & {o["normalized"] for o in right}):
                src = [o for o in left if o["normalized"] == value]
                dst = [o for o in right if o["normalized"] == value]
                # A shared member counts only within the SAME captured cluster version.
                if kind == "cluster_member" and not ({o["metadata"]["cluster_key"] for o in src} & {o["metadata"]["cluster_key"] for o in dst}): continue
                eligible = any(o["eligible"] for o in src) and any(o["eligible"] for o in dst)
                current_strength = strength if eligible else "CONTEXT_ONLY"
                links.append({"id": uid(), "run_id": run_id, "case_a": a["case_id"], "case_b": b["case_id"],
                    "link_type": link_type, "strength": current_strength, "matched_value": value,
                    "source_objects": {"case_a": src, "case_b": dst},
                    "provenance": [o["provenance"] for o in src+dst],
                    "algorithm_version": ALGORITHM, "generated_at": at,
                    "explanation": f"Shared {kind.replace('_', ' ')}: {value}. Potential linkage; analyst review required.",
                    "disclaimer": DISCLAIMER})
        if similarity["score"] is not None and similarity["score"] >= 50 and similarity["matched_field_count"] >= 2:
            links.append({"id": uid(), "run_id": run_id, "case_a": a["case_id"], "case_b": b["case_id"],
                "link_type": "SIMILAR_MO", "strength": "WEAK", "matched_value": "recurring MO characteristics",
                "source_objects": {"fingerprints": [a["id"], b["id"]]},
                "provenance": [{"kind": "mo_fingerprint", "reference_id": a["id"], "case_id": a["case_id"]},
                               {"kind": "mo_fingerprint", "reference_id": b["id"], "case_id": b["case_id"]}],
                "algorithm_version": ALGORITHM, "generated_at": at, "similarity": similarity,
                "explanation": f"{similarity['matched_field_count']} of {similarity['comparable_field_count']} comparable MO attributes match; weighted match fraction {similarity['score']}/100.",
                "disclaimer": DISCLAIMER})
        return links

    def review(self, identifier, payload):
        locked(self.db)
        link = self.link(identifier)
        self.writable_case(link["case_a"]); self.writable_case(link["case_b"])
        current = link["review"]["sequence"]
        if payload.expected_sequence != current: raise HTTPException(409, "Link review changed. Reload before reviewing.")
        record = safe_snapshot({"link_id": identifier, "sequence": current+1, "status": payload.status,
            "rationale": payload.rationale.strip(), "reviewer": "analyst"})
        if not record["rationale"]: raise HTTPException(422, "A review rationale is required.")
        row = Review(id=uid(), link_id=identifier, sequence=current+1, status=payload.status, created_at=now(), record=record)
        self.db.add(row); self.db.flush()
        return self.link(identifier)

    def run(self, kind, identifier):
        model = {"mo_fingerprint": Fingerprint, "case_comparison": LinkRun, "nexus": Nexus, "priority": Priority}.get(kind)
        if not model: raise HTTPException(422, "Unsupported analysis kind.")
        row = self.db.get(model, identifier)
        if not row: raise HTTPException(404, "Analysis run not found.")
        result = view(row)
        if kind == "case_comparison":
            links = [self.link(r.id) for r in self.db.scalars(select(Link).where(Link.run_id == identifier).order_by(Link.id))]
            result = {**result, "links": links}
        return result

    def history(self, case_id):
        get_case(self.db, case_id)
        result = {}
        for key, model in (("profiles", Profile), ("fingerprints", Fingerprint), ("comparisons", LinkRun)):
            result[key] = [view(r) for r in self.db.scalars(select(model).where(model.case_id == case_id).order_by(model.created_at.desc(), model.id).limit(50))]
        result["bounds"] = {"per_type": 50, "order": "newest first"}
        return result

    def nexus(self, payload):
        locked(self.db)
        ids = sorted(set(payload.case_ids))
        cases = [get_case(self.db, i) for i in ids]
        nodes, edges = {}, {}
        def node(kind, key, label, case_id, metadata=None):
            identifier = kind + ":" + digest(key)[:24]
            if identifier not in nodes:
                nodes[identifier] = {"id": identifier, "type": kind, "label": label, "key": key, "case_ids": [], "metadata": metadata or {}}
            if case_id not in nodes[identifier]["case_ids"]: nodes[identifier]["case_ids"].append(case_id)
            return identifier
        def edge(kind, source, target, case_id, provenance, metadata=None, strength=None, review_status=None):
            material = {"type": kind, "source": source, "target": target, "case_id": case_id, "provenance": provenance,
                "metadata": metadata or {}, "strength": strength, "review_status": review_status}
            identifier = "edge:" + digest(material)[:24]
            edges[identifier] = {"id": identifier, **material}
        for case in cases:
            root = node("case", case.id, case.title, case.id, {"case_id": case.id, "version": case.version, "archived": bool(case.archived_at)})
            objects = project(self.db, case, profile_snapshot(self.db, case.id))
            object_nodes = []
            type_map = {"wallet": "wallet", "counterparty": "wallet", "cluster_member": "wallet", "transaction": "transaction",
                "vendor_alias": "alias", "marketplace": "marketplace", "domain": "domain", "public_profile": "public_profile",
                "entity": "entity", "technical_cluster": "technical_cluster", "substance": "substance", "precursor": "precursor",
                "pre_precursor": "precursor", "consignment": "consignment", "logistics_method": "logistics",
                "source_capture": "source_capture", "discovery_source": "discovery_source"}
            edge_map = {"wallet": "CASE_HAS_WALLET", "counterparty": "CASE_HAS_COUNTERPARTY", "cluster_member": "CASE_HAS_CLUSTER_MEMBER",
                "transaction": "CASE_HAS_TRANSACTION", "vendor_alias": "CASE_HAS_ALIAS", "entity": "ENTITY_SUBJECT_OF_CLAIM",
                "technical_cluster": "CASE_HAS_TECHNICAL_CLUSTER", "consignment": "CASE_HAS_CONSIGNMENT",
                "logistics_method": "CASE_HAS_LOGISTICS", "source_capture": "CASE_HAS_SOURCE_CAPTURE", "discovery_source": "CASE_HAS_DISCOVERY_SOURCE"}
            for obj in objects:
                kind = obj["kind"]
                node_type = "location" if kind.startswith(("origin_", "destination_")) or kind == "seizure_location" else type_map.get(kind)
                if not node_type: continue
                # Location level and substance/precursor type remain part of identity.
                key = (kind if node_type in ("location", "substance", "precursor") else node_type) + ":" + obj["normalized"]
                label = obj["metadata"].get("label") or obj["metadata"].get("source_name") or obj["value"]
                target = node(node_type, key, label, case.id, obj["metadata"])
                edge_type = edge_map.get(kind, "CASE_INVOLVES_SUBSTANCE" if node_type in ("substance", "precursor") else
                    "CASE_HAS_LOCATION" if node_type == "location" else "CASE_HAS_" + node_type.upper())
                edge(edge_type, root, target, case.id, [obj["provenance"]], {"attribute": kind},
                     review_status=obj["provenance"].get("review_status"))
                object_nodes.append((obj, target))
            for obj, target in object_nodes:
                kind, m = obj["kind"], obj["metadata"]
                for other, other_id in object_nodes:
                    if kind == "cluster_member" and other["kind"] == "technical_cluster" and m["cluster_key"] == other["value"]:
                        edge("WALLET_IN_CLUSTER", target, other_id, case.id, [obj["provenance"]])
                    if kind == "vendor_alias" and other["kind"] == "marketplace":
                        edge("ALIAS_RECORDED_WITH_MARKETPLACE", target, other_id, case.id, [obj["provenance"], other["provenance"]], {"limitation": "Co-recorded Case facts; account ownership not established"})
                    if kind == "consignment" and m.get("id") == other["metadata"].get("consignment_id"):
                        et = "CONSIGNMENT_ORIGIN" if other["kind"].startswith("origin_") else "CONSIGNMENT_DESTINATION" if other["kind"].startswith("destination_") else "CONSIGNMENT_HAS_" + other["kind"].upper()
                        edge(et, target, other_id, case.id, [other["provenance"]])
                    if kind == "source_capture" and other["kind"] == "wallet":
                        origin = m.get("origin") or {}
                        if origin.get("wallet") == other["metadata"].get("address") and origin.get("chain") == other["metadata"].get("chain"):
                            edge("WALLET_MENTIONED_IN_SOURCE", other_id, target, case.id, [obj["provenance"]])
        for run_id in sorted(set(payload.link_run_ids)):
            run = self.run("case_comparison", run_id)
            if not set(run["case_ids"]) <= set(ids): raise HTTPException(422, "Comparison run contains Cases outside this Nexus selection.")
            for link in run["links"]:
                review = link["review"]
                source = node("case", link["case_a"], get_case(self.db, link["case_a"]).title, link["case_a"])
                target = node("case", link["case_b"], get_case(self.db, link["case_b"]).title, link["case_b"])
                edge("CASE_RELATED_TO_CASE", source, target, link["case_a"], link["provenance"],
                    {"link": link}, link["strength"], review["status"])
        # Retain deterministic Case nodes first. Explicit totals distinguish selection from truncation.
        ordered = sorted(nodes.values(), key=lambda n: (n["type"] != "case", n["type"], n["id"]))
        selected = ordered[:payload.max_nodes]; kept = {n["id"] for n in selected}
        candidate_edges = sorted((e for e in edges.values() if e["source"] in kept and e["target"] in kept), key=lambda e: e["id"])
        graph = safe_snapshot({"case_ids": ids, "nodes": selected, "edges": candidate_edges[:payload.max_edges],
            "algorithm_version": GRAPH_ALGORITHM, "link_run_ids": sorted(set(payload.link_run_ids)),
            "bounds": {"max_nodes": payload.max_nodes, "max_edges": payload.max_edges, "available_nodes": len(nodes),
                "available_edges": len(edges), "truncated": len(nodes)>payload.max_nodes or len(edges)>payload.max_edges},
            "source_case_versions": {c.id: c.version for c in cases}, "disclaimer": DISCLAIMER,
            "coverage": "Selected Case records and pins only; no complete blockchain coverage is implied."})
        graph["graph_fingerprint"] = digest(graph)
        row = Nexus(id=uid(), created_at=now(), record=graph); self.db.add(row); self.db.flush()
        return view(row)

    def priority(self, nexus_id):
        locked(self.db)
        graph = self.run("nexus", nexus_id)
        record = {"nexus_id": nexus_id, "case_ids": graph["case_ids"], "graph_fingerprint": graph["graph_fingerprint"],
            "algorithm_version": PRIORITY_ALGORITHM, "bounds": graph["bounds"], "metrics": priority(graph),
            "source_graph_created_at": graph["created_at"], "disclaimer": DISCLAIMER}
        row = Priority(id=uid(), nexus_id=nexus_id, created_at=now(), record=record)
        self.db.add(row); self.db.flush(); return view(row)

    def pin(self, case_id, payload):
        locked(self.db); self.writable_case(case_id)
        if payload.kind == "reviewed_link":
            snapshot = self.link(payload.reference_id)
            if snapshot["review"]["status"] == "UNREVIEWED": raise HTTPException(409, "Review this link before pinning it.")
            ids = [snapshot["case_a"], snapshot["case_b"]]
        else:
            snapshot = self.run(payload.kind, payload.reference_id)
            ids = snapshot.get("case_ids") or [snapshot.get("case_id")]
        if case_id not in ids: raise HTTPException(422, "Analysis does not include this Case.")
        frozen = safe_snapshot(snapshot)
        row = CaseEntity(id=uid(), case_id=case_id, entity_type="narcotics_" + payload.kind,
            entity_ref=payload.reference_id, metadata_json={"narcotics_pin": {"kind": payload.kind, "snapshot": frozen,
                "captured_at": now(), "snapshot_fingerprint": digest(frozen)}, "disclaimer": DISCLAIMER})
        self.db.add(row); self.db.flush(); return data(row)
