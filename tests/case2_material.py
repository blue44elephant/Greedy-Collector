"""CASE-2 test-only sources, normalized activity and real service commands."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from sqlalchemy.orm import Session
from greedy_collector.models import RiskResult, utcnow
from greedy_collector.risk.engine import ExplainableRiskEngine
from greedy_collector.sanctions.service import SanctionsRegistry, screen
from greedy_collector.attribution.service import AttributionService
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.broad.providers import normalize_result, DiscoveryQuery, DiscoveryObservation
from greedy_collector.discovery.capture.service import CaptureService
from greedy_collector.discovery.capture.network import Retrieved
from greedy_collector.discovery.capture.api import ReviewInput, PromoteInput
from greedy_collector.clustering.service import ClusteringService
from greedy_collector.fund_flow.service import FlowService
from greedy_collector.fund_flow.schemas import FlowQuery
from tests.test_sanctions_registry import FixtureSource, source, ETH, BTC, OTHER
from tests.test_clustering import store, address
from tests.test_fund_flow import event

def retrieved(origin, content):
    body = content.encode()
    return Retrieved(final_url=origin["requested_url"], http_status=200, content_type="text/plain",
        byte_count=len(body), body_sha256=sha256(body).hexdigest(), title="CASE2 synthetic public source",
        text=content, status="captured", body=body)

def save_risk(db):
    risk = ExplainableRiskEngine().evaluate(ETH, [], [], chain="ethereum", sanctions=screen(db, "ethereum", ETH),
        coverage={"status": "bounded", "records_returned": 0})
    risk["calculated_at"] = utcnow().isoformat()
    row = RiskResult(chain="ethereum", address=ETH, score=risk["score"], level=risk["level"],
        findings=risk["findings"], assessment=risk)
    db.add(row)
    db.commit()
    return row.id

def seed(engine):
    with Session(engine, expire_on_commit=False) as db:
        SanctionsRegistry(db, FixtureSource(source())).sync()
        risk_id = save_risk(db)
        ds = DiscoveryService(db)
        subject = ds.get_or_create_subject("blockchain_address", "ethereum", ETH)
        run = ds.create_run(subject["id"], [{"transform_id": "wallet.broad_web", "source_id": "brave_search"}],
            idempotency_key=str(uuid4()), execution_policy={"broad": True})
        run = ds.transition_run(run["id"], "running", expected_version=run["version"])
        ds.transition_source(run["sources"][0]["id"], "running", expected_run_version=run["version"])
        run = ds.get_run(run["id"])
        record = normalize_result("brave_search", DiscoveryQuery("ethereum", ETH),
            DiscoveryObservation("https://source.example/case2", "CASE2 source", ETH+"; entity: Synthetic Service;", 1),
            datetime.now(timezone.utc).isoformat())
        batch = ds.record_batch(run["sources"][0]["id"], [record], expected_run_version=run["version"])
        run = ds.get_run(run["id"])
        run = ds.transition_run(run["id"], "completed", expected_version=run["version"])
        observation_id = batch["observation_ids"][0]
        cs = CaptureService(db)
        origin = cs.origin(observation_id)
        capture = cs.store(origin, retrieved(origin, ETH+" explicit public source fixture"))
        capture = cs.review(capture["id"], ReviewInput(status="relevant", note="Test analyst reviewed preserved source", expected_version=0))
        attr = AttributionService(db)
        entity = attr.create_entity({"canonical_name": "CASE2 Synthetic Entity", "entity_type": "service"})
        claim = attr.create_claim({"entity_id": entity["id"], "chain": "ethereum", "subject_ref": ETH,
            "relationship": "controlled_by", "scope_note": "Synthetic technical-control proposition"})
        preview = cs.preview(capture["id"])
        promoted = cs.promote(capture["id"], PromoteInput(excerpt=ETH, expected_source_fingerprint=preview["source_fingerprint"],
            claim_id=claim["id"], expected_claim_version=claim["version"], confirmed=True,
            source_reliability="reliable", reliability_rationale="Exact primary fixture verified",
            link={"stance": "supports", "directness": "direct", "rationale": "Explicit technical identifier"}))
        claim = promoted["claim"]
        claim = attr.create_and_link_evidence(claim["id"],
            {"evidence_type": "public_record", "title": "CASE2 contrary record", "summary": "Contradiction retained",
             "source_name": "Synthetic counter-source", "source_locator": "fixture:contradiction", "origin": "public_osint",
             "source_reliability": "reliable", "reliability_rationale": "Counter-source explicitly checked"},
            {"stance": "contradicts", "directness": "direct", "rationale": "Scope conflict"},
            expected_version=claim["version"])["claim"]
        links = attr.list_claim_evidence(claim["id"])["items"]
        claim = attr.change_assessment(claim["id"], "supported", "Explicit analyst fixture assessment",
            expected_version=claim["version"], reviewed_link_ids=[v["id"] for v in links],
            acknowledged_contradictions=[v["id"] for v in links if v["stance"] == "contradicts"],
            conflict_discussion="Conflicting material retained and assessed")
        store(db, [BTC, address(2)])
    with Session(engine, expire_on_commit=False) as db:
        cluster = ClusteringService(db).analyze("bitcoin")["clusters"][0]
        event(db, source=ETH, target=OTHER)
    with Session(engine, expire_on_commit=False) as db:
        flow = FlowService(db).analyze(FlowQuery(chain="ethereum", source=ETH, target=OTHER))
    return {"risk_id": risk_id, "run_id": run["id"], "capture_id": capture["id"], "capture_hash": capture["body_sha256"],
        "claim_id": claim["id"], "claim_version": claim["version"], "cluster_id": cluster["id"],
        "cluster_version": cluster["version"], "flow_id": flow["id"], "origin": origin}

def mutate(engine, material):
    with Session(engine, expire_on_commit=False) as db:
        SanctionsRegistry(db, FixtureSource(source([(3, "Replacement", ["CYBER2"], [("ETH", OTHER)])]))).sync()
        save_risk(db)
        attr = AttributionService(db)
        claim = attr.get_claim(material["claim_id"])
        links = attr.list_claim_evidence(claim["id"])["items"]
        attr.change_assessment(claim["id"], "rejected", "Later explicit analyst rejection",
            expected_version=claim["version"], reviewed_link_ids=[v["id"] for v in links],
            acknowledged_contradictions=[v["id"] for v in links if v["stance"] == "contradicts"],
            conflict_discussion="Later contradiction assessment")
        cs = CaptureService(db)
        cs.store(material["origin"], retrieved(material["origin"], ETH+" changed source fixture"))
        cs.review(material["capture_id"], ReviewInput(status="irrelevant", note="Later review", expected_version=1))
        store(db, [address(2), address(3)], number=2)
    with Session(engine, expire_on_commit=False) as db:
        ClusteringService(db).analyze("bitcoin")
        event(db, source=OTHER, target="0x"+"ef"*20, number=2, second=1)
    with Session(engine, expire_on_commit=False) as db:
        FlowService(db).analyze(FlowQuery(chain="ethereum", source=ETH, target=OTHER))
