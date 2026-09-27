"""Explicit, serialized local analysis with immutable historical snapshots."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
import json
import re
from sqlalchemy import select, func, text, inspect
from ..chains import get_chain
from ..models import Transaction, Label, Case, CaseEntity
from .models import Base, Cluster, Version, Member, Evidence, Exclusion, Link
from .domain import (CHAINS, HEURISTIC, DISCLAIMER, LIMITATION, MAX_ROWS, MAX_BYTES,
                     MAX_MEMBERS, MAX_EVIDENCE, ClusteringError, fingerprint, material_fingerprint)
from .heuristics import evaluate, components

def now():
    return datetime.now(timezone.utc).isoformat()

class ClusteringService:
    def __init__(self, db):
        self.db = db

    def ready(self):
        if not set(Base.metadata.tables).issubset(inspect(self.db.get_bind()).get_table_names()):
            raise ClusteringError("Clustering storage unavailable. Explicit migration required.", 503)

    def supported(self, chain):
        get_chain(chain)
        if chain not in CHAINS:
            raise ClusteringError("Automatic clustering heuristic unavailable for this chain.")

    @contextmanager
    def writing(self):
        self.ready()
        # Route sessions are fresh; refuse to mix this transaction with caller writes.
        if self.db.in_transaction():
            raise ClusteringError("Clustering requires a separate transaction.", 409)
        try:
            self.db.execute(text("BEGIN IMMEDIATE"))
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def analyze(self, chain):
        self.supported(chain)
        with self.writing():
            return self._analyze(chain)

    def _analyze(self, chain):
        query = select(Transaction).where(Transaction.chain == chain)
        count, size = self.db.execute(select(func.count(), func.coalesce(func.sum(func.length(Transaction.raw_payload)), 0)).where(Transaction.chain == chain)).one()
        if count > MAX_ROWS or size > MAX_BYTES:
            raise ClusteringError("Stored chain data exceeds the CL-1 analysis limit (5000 rows / 16 MiB). No partial clustering was performed.")
        rows = self.db.scalars(query.order_by(Transaction.tx_hash, Transaction.event_key)).all()
        # Bound label context independently; never silently omit it from evidence.
        labels = self.db.scalars(select(Label).where(Label.chain.in_([chain, "any"])).limit(10001)).all()
        if len(labels) > 10000:
            raise ClusteringError("Stored label context exceeds the CL-1 limit (10000).")
        adapter = get_chain(chain).adapter()
        warnings = {}
        for label in labels:
            if label.type.lower() in {"exchange", "mixer", "bridge", "service", "custodian", "gambling"}:
                warnings.setdefault(adapter.address_key(label.address), set()).add("Input address " + label.address + " has stored " + label.type + " annotation (not ownership proof).")
        by_tx = {}
        for row in rows:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", row.tx_hash):
                raise ClusteringError("Stored transaction identifier is incompatible with UTXO clustering.")
            by_tx.setdefault(row.tx_hash.lower(), []).append(row.raw_payload)
        exclusions = {e.tx_hash: e for e in self.db.scalars(select(Exclusion).where(Exclusion.chain == chain))}
        all_evidence = []
        for tx_hash, payloads in sorted(by_tx.items()):
            evaluations = [evaluate(chain, tx_hash, payload) for payload in payloads]
            # Multiple wallet-relative rows must agree about the original transaction.
            signatures = {fingerprint({k: v for k, v in item.items() if k != "source_fingerprint"}) for item in evaluations}
            material = min(evaluations, key=fingerprint)
            if len(signatures) != 1:
                material["automatic_exclusions"] = sorted(set(material["automatic_exclusions"] + ["inconsistent_stored_transaction_views"]))
                material["inputs"] = sorted({a for item in evaluations for a in item["inputs"]})
            material["counter_indicators"] = sorted({warning for a in material["inputs"] for warning in warnings.get(adapter.address_key(a), ())})
            evidence_id = fingerprint(material)
            if self.db.get(Evidence, evidence_id) is None:
                self.db.add(Evidence(id=evidence_id, chain=chain, tx_hash=tx_hash, material=material, created_at=now()))
            exclusion = exclusions.get(tx_hash)
            all_evidence.append({**material, "id": evidence_id,
                "excluded": bool(material["automatic_exclusions"] or exclusion),
                "analyst_exclusion": {"reason": exclusion.reason, "timestamp": exclusion.created_at} if exclusion else None})
        self.db.flush()
        accepted = [e for e in all_evidence if not e["excluded"]]
        groups = components(accepted)
        # Index memberships once. Avoid a component x evidence scan.
        group_for = {a: i for i, group in enumerate(groups) for a in group}
        related = [dict() for _ in groups]
        for evidence in all_evidence:
            for i in {group_for[a] for a in evidence["inputs"] if a in group_for}:
                related[i][evidence["id"]] = evidence
        if sum(len(e["inputs"]) for group in related for e in group.values()) > 50000:
            raise ClusteringError("Cluster evidence disclosure exceeds 50000 memberships. No partial clustering was performed.")
        clusters = list(self.db.scalars(select(Cluster).where(Cluster.chain == chain).order_by(Cluster.id)))
        old = {}
        for cluster in clusters:
            version = self.db.scalar(select(Version).where(Version.cluster_id == cluster.id, Version.number == cluster.current_version))
            old[cluster.id] = (cluster, version)
        owners = {}
        for cluster_id, (_, version) in old.items():
            for address in version.snapshot["members"]:
                owners.setdefault(address, set()).add(cluster_id)
        old_related = {cid: {} for cid in old}
        for evidence in all_evidence:
            for cid in {cid for a in evidence["inputs"] for cid in owners.get(a, ())}:
                old_related[cid][evidence["id"]] = evidence
        used, result = set(), []
        for i, members in enumerate(groups):
            candidates = sorted({cid for a in members for cid in owners.get(a, ())} - used)
            cluster = old[candidates[0]][0] if candidates else Cluster(id=str(uuid4()), chain=chain, current_version=0, created_at=now())
            if not candidates:
                self.db.add(cluster)
                self.db.flush()
            used.add(cluster.id)
            evidence = sorted(related[i].values(), key=lambda e: (e["tx_hash"], e["id"]))
            snapshot = {"chain": chain, "heuristic": HEURISTIC, "members": members, "evidence": evidence,
                "status": "review_required" if len(members) > MAX_MEMBERS or len(evidence) > MAX_EVIDENCE else "active",
                "disclaimer": DISCLAIMER, "limitations": LIMITATION}
            result.append(self._save(cluster, snapshot))
        # Retire old merged/dissolved IDs with a new empty version, never delete history.
        for cid, (cluster, previous) in old.items():
            if cid not in used and previous.snapshot["members"]:
                evidence = list(old_related[cid].values())
                self._save(cluster, {"chain": chain, "heuristic": HEURISTIC, "members": [], "evidence": evidence,
                    "status": "superseded_or_dissolved", "disclaimer": DISCLAIMER, "limitations": LIMITATION})
        return {"chain": chain, "clusters": result, "evidence": all_evidence, "stored_rows_analyzed": count,
                "disclaimer": DISCLAIMER, "limitations": LIMITATION,
                "empty_message": "No eligible common-input cluster. Additional blockchain collection may be required." if not result else None}

    def _save(self, cluster, snapshot):
        digest = material_fingerprint(snapshot)
        previous = self.db.scalar(select(Version).where(Version.cluster_id == cluster.id, Version.number == cluster.current_version)) if cluster.current_version else None
        if previous and previous.fingerprint == digest:
            return self._view(cluster, previous)
        number = cluster.current_version + 1
        version = Version(id=str(uuid4()), cluster_id=cluster.id, number=number, fingerprint=digest, snapshot=snapshot, created_at=now())
        self.db.add(version)
        self.db.flush()
        self.db.add_all(Member(version_id=version.id, chain=cluster.chain, address=a) for a in snapshot["members"])
        self.db.add_all(Link(version_id=version.id, evidence_id=e["id"]) for e in snapshot["evidence"])
        cluster.current_version = number
        self.db.flush()
        return self._view(cluster, version)

    def _view(self, cluster, version):
        return {**version.snapshot, "id": cluster.id, "version": version.number, "fingerprint": version.fingerprint,
                "created_at": cluster.created_at, "recomputed_at": version.created_at}

    def cluster(self, cluster_id, version=None):
        self.ready()
        cluster = self.db.get(Cluster, cluster_id)
        if cluster is None: raise ClusteringError("Technical cluster not found.", 404)
        row = self.db.scalar(select(Version).where(Version.cluster_id == cluster_id, Version.number == (version or cluster.current_version)))
        if row is None: raise ClusteringError("Technical cluster version not found.", 404)
        return self._view(cluster, row)

    def wallet(self, chain, address):
        self.supported(chain)
        self.ready()
        adapter = get_chain(chain).adapter()
        try:
            adapter.validate_address(address)
            address = adapter.normalize_address(address)
        except ValueError:
            raise ClusteringError("Invalid public wallet address.") from None
        pairs = self.db.execute(select(Cluster, Version).join(Version, Version.cluster_id == Cluster.id).join(Member, Member.version_id == Version.id).where(
            Cluster.chain == chain, Member.chain == chain, Member.address == address, Version.number == Cluster.current_version)).all()
        return {"chain": chain, "address": address, "clusters": [self._view(c, v) for c, v in pairs], "disclaimer": DISCLAIMER}

    def exclude(self, evidence_id, reason):
        reason = reason.strip()
        if not reason or len(reason) > 1000: raise ClusteringError("An exclusion rationale of 1-1000 characters is required.")
        with self.writing():
            evidence = self.db.get(Evidence, evidence_id)
            if evidence is None: raise ClusteringError("Clustering evidence not found.", 404)
            previous = self.db.scalar(select(Exclusion).where(Exclusion.chain == evidence.chain, Exclusion.tx_hash == evidence.tx_hash))
            if previous is None:
                self.db.add(Exclusion(id=str(uuid4()), evidence_id=evidence.id, chain=evidence.chain, tx_hash=evidence.tx_hash, reason=reason, created_at=now()))
                self.db.flush()
            return self._analyze(evidence.chain)

    def pin(self, case_id, cluster_id, version):
        with self.writing():
            if self.db.get(Case, case_id) is None: raise ClusteringError("Case not found.", 404)
            snapshot = self.cluster(cluster_id, version)
            ref = f"{cluster_id}:v{version}"
            existing = self.db.scalar(select(CaseEntity).where(CaseEntity.case_id == case_id, CaseEntity.entity_type == "technical_cluster", CaseEntity.entity_ref == ref))
            if existing: return {"id": existing.id, "pinned": existing.metadata_json["cluster_pin"]}
            row = CaseEntity(id=str(uuid4()), case_id=case_id, entity_type="technical_cluster", entity_ref=ref,
                             metadata_json={"chain": snapshot["chain"], "cluster_pin": snapshot})
            self.db.add(row)
            self.db.flush()
            return {"id": row.id, "pinned": snapshot}
