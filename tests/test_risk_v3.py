"""Synthetic risk calibration and isolated API tests; no production fixture data."""
from unittest.mock import AsyncMock
from io import StringIO
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, inspect

from greedy_collector.chains import EthereumAdapter
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import RiskResult
from greedy_collector.risk import ExplainableRiskEngine
from greedy_collector.risk.engine import SCORING_MODEL
from greedy_collector.router import service
from tests.risk_controls import FOCUS, controls, label, transfer
from tests.test_sanctions_integration import api_db  # isolated TestClient + SQLite
from tests.test_sanctions_registry import ETH, source
from tests.test_litecoin_monero import MONERO_STANDARD


def assess(txs=(), labels=(), paths=(), *, state="NOT_FOUND_IN_AVAILABLE_SNAPSHOTS",
           match="NO_MATCH", coverage="COMPLETE_WITHIN_REQUESTED_BOUND", behavioral=True):
    return ExplainableRiskEngine().evaluate(
        FOCUS, list(txs), list(labels), list(paths), chain="ethereum",
        sanctions={"listing_state": state, "match_type": match,
                   "snapshot": {"id": "fixture-snapshot", "sha256": "a" * 64}},
        coverage={"status": coverage, "records_returned": len(txs)},
        include_behavioral=behavioral,
    )


CURRENT = ("CURRENTLY_LISTED", "DIRECT_CHAIN_MATCH")
CALIBRATION = [
    ("ordinary-new", (), (), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 0, "LOW"),
    ("ordinary-busy", controls()["Busy 778 records"][0], (), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 0, "LOW"),
    ("exchange-like", controls()["Exchange-like fan-in/out"][0], (), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 5, "LOW"),
    ("direct-current-low-behavior", (), (), (), *CURRENT, 95, "CRITICAL"),
    ("direct-current-high-behavior", controls()["Mixed strong exposure"][0], controls()["Mixed strong exposure"][1], (), *CURRENT, 95, "CRITICAL"),
    ("historical", (), (), (), "HISTORICALLY_LISTED", "DIRECT_CHAIN_MATCH", 0, "LOW"),
    ("unresolved-text", (), (), (), "CURRENTLY_LISTED", "EXACT_TEXT_MATCH_CHAIN_UNRESOLVED", 0, "LOW"),
    ("other-chain", (), (), (), "CURRENTLY_LISTED", "TEXT_MATCH_OTHER_CHAIN", 0, "LOW"),
    ("manual-sanctioned", (), (label("Sanctioned", FOCUS),), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 35, "MODERATE"),
    ("direct-mixer", (transfer(1, cp="0x" + "2" * 40),), (label("Mixer"),), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 25, "LOW"),
    ("direct-scam", (transfer(1, cp="0x" + "2" * 40),), (label("Scam"),), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 30, "LOW"),
    ("direct-labelled-sanctioned", (transfer(1, cp="0x" + "2" * 40),), (label("Sanctioned"),), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 40, "MODERATE"),
    ("two-hop", (), (), ({"hops": 2, "terminal_type": "Sanctioned", "confidence": .8},), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 10, "LOW"),
    ("three-hop", (), (), ({"hops": 3, "terminal_type": "Sanctioned", "confidence": .8},), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 5, "LOW"),
    ("bridge-context", (transfer(1, cp="0x" + "2" * 40),), (label("Bridge"),), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 0, "LOW"),
    ("archived-label", (), ({**label("Sanctioned", FOCUS), "active": False},), (), "NOT_FOUND_IN_AVAILABLE_SNAPSHOTS", "NO_MATCH", 0, "LOW"),
    ("direct-current-manual-label", (), (label("Sanctioned", FOCUS),), (), *CURRENT, 95, "CRITICAL"),
]


@pytest.mark.parametrize("name,txs,labels,paths,state,match,score,tier", CALIBRATION,
                         ids=[row[0] for row in CALIBRATION])
def test_synthetic_calibration_corpus(name, txs, labels, paths, state, match, score, tier):
    result = assess(txs, labels, paths, state=state, match=match)
    assert (result["overall_score"], result["overall_tier"]) == (score, tier)
    assert result == assess(txs, labels, paths, state=state, match=match)
    assert result["model_version"] == SCORING_MODEL
    assert result["behavioral_exposure_score"] == sum(
        item["score_contribution"] for item in result["findings"])
    assert bool(result["overrides"]) == ((state, match) == CURRENT)


@pytest.mark.parametrize("state,match", [
    ("REGISTRY_NOT_SYNCED", "UNAVAILABLE"), ("REGISTRY_STALE", "NO_MATCH"),
    ("SCREENING_UNRESOLVED", "UNAVAILABLE")])
def test_unavailable_registry_is_never_presented_as_clean(state, match):
    result = assess(state=state, match=match)
    assert result["overall_score"] == 0 and not result["overrides"]
    assert any("unavailable or stale" in item for item in result["limitations"])


@pytest.mark.parametrize("coverage", ["PARTIAL", "TRUNCATED", "PROVIDER_LIMITED"])
def test_bounded_coverage_is_explicit(coverage):
    result = assess(coverage=coverage)
    assert result["data_coverage"]["status"] == coverage
    assert any("absence of observed behavior" in item for item in result["limitations"])


def test_failed_and_duplicate_transfer_do_not_inflate_risk():
    tx = transfer(1, cp="0x" + "2" * 40)
    failed = transfer(2, cp="0x" + "2" * 40)
    failed.raw_payload = {"isError": "1"}
    result = assess([tx, tx, failed], [label("Scam")])
    finding = next(item for item in result["findings"] if item["rule_id"] == "direct_scam")
    assert result["overall_score"] == 30
    assert "observations" not in finding["evidence"]


def test_scope_conflicts_and_provenance():
    btc_label = {**label("Sanctioned", FOCUS), "chain": "bitcoin"}
    any_label = {**label("Scam", FOCUS), "chain": "any"}
    unknown = {**label("Unknown", FOCUS), "chain": "ethereum"}
    result = assess(labels=[btc_label, any_label, unknown])
    assert result["overall_score"] == 30
    assert result["findings"][0]["evidence"]["labels"][0]["source"] == "Synthetic calibration fixture"


def test_self_transfer_does_not_count_wallet_label_twice():
    tx = transfer(1, cp=FOCUS)
    result = assess([tx], [label("Sanctioned", FOCUS)])
    assert result["overall_score"] == 35
    assert {item["rule_id"] for item in result["findings"]} == {"wallet_sanctioned_label"}


def test_monero_behavior_unavailable_but_current_direct_status_critical():
    result = ExplainableRiskEngine().evaluate(
        "synthetic-only", [], [], chain="monero", include_behavioral=False,
        sanctions={"listing_state": CURRENT[0], "match_type": CURRENT[1]},
        coverage={"status": "UNAVAILABLE"},
    )
    assert result["overall_score"] == 95 and result["overall_tier"] == "CRITICAL"
    assert result["behavioral_score"] is None and result["behavioral_exposure_score"] is None


def test_original_low_behavior_current_match_case_snapshot_and_history(api_db, monkeypatch):
    client, sessions, fixture = api_db
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("No provider request")))
    monkeypatch.setattr(EthereumAdapter, "lookup_address", AsyncMock(return_value={"balance_native": "0", "source_api": "test-only"}))
    monkeypatch.setattr(EthereumAdapter, "transactions", AsyncMock(return_value=[]))
    monkeypatch.setattr(service.graph_store, "store_transactions", lambda rows: None)
    uri = "/api/greedy-collector"
    assert client.post(uri + "/sanctions/sync").status_code == 200
    result = client.post(uri + "/lookup/address", json={"chain": "ethereum", "address": ETH})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["risk"]["behavioral_exposure_score"] == 0
    assert data["risk"]["overall_score"] == 95 and data["risk"]["overall_tier"] == "CRITICAL"
    assert data["risk"]["overrides"][0]["reason"] == "Overall score elevated by current direct authoritative sanctions match."
    assert len(data["sanctions_screening"]["associations"]) == 3
    assert len(data["risk"]["authoritative_status"][0]["associations"]) == 3
    saved = client.get(uri + f"/address/ethereum/{ETH}/risk").json()
    assert saved["model_version"] == SCORING_MODEL and saved["authoritative_status"][0]["snapshot_sha256"]
    case = client.post(uri + "/cases", json={"title": "Synthetic risk case"}).json()
    added = client.post(uri + f"/cases/{case['id']}/entities", json={"entity_type": "wallet", "entity_ref": ETH,
                  "metadata": {"chain": "ethereum", "address": ETH}})
    assert added.status_code == 200, added.text
    assert added.json()["metadata_json"]["risk_assessment"]["overall_score"] == 95
    report = client.get(uri + f"/reports/{case['id']}?format=markdown")
    assert report.status_code == 200 and "deterministic-v3" in report.text and "CURRENTLY_LISTED" in report.text
    fixture.data = source([(3, "Replacement", ["CYBER2"], [("ETH", "0x" + "cd" * 20)])])
    assert client.post(uri + "/sanctions/sync").status_code == 200
    fresh = client.post(uri + "/lookup/address", json={"chain": "ethereum", "address": ETH}).json()
    assert fresh["sanctions_screening"]["listing_state"] == "HISTORICALLY_LISTED"
    assert fresh["risk"]["overall_score"] == 0 and fresh["risk"]["overrides"] == []
    with sessions() as db:
        rows = db.scalars(select(RiskResult).where(RiskResult.address == ETH).order_by(RiskResult.calculated_at)).all()
        assert len(rows) == 2 and rows[0].assessment["overall_score"] == 95
    assert client.get(uri + f"/cases/{case['id']}").json()["entities"][0]["metadata_json"]["risk_assessment"]["overall_score"] == 95


def test_label_archive_changes_only_fresh_assessment(api_db, monkeypatch):
    client, _, _ = api_db
    monkeypatch.setattr(EthereumAdapter, "lookup_address", AsyncMock(return_value={"balance_native": "0", "source_api": "test-only"}))
    monkeypatch.setattr(EthereumAdapter, "transactions", AsyncMock(return_value=[]))
    monkeypatch.setattr(service.graph_store, "store_transactions", lambda rows: None)
    uri = "/api/greedy-collector"
    label_row = client.post(uri + "/labels/manual", json={"chain": "ethereum", "address": ETH,
        "label": "Source assertion", "type": "Sanctioned", "source": "Synthetic analyst", "confidence": .7}).json()
    first = client.post(uri + "/lookup/address", json={"chain": "ethereum", "address": ETH}).json()["risk"]
    assert first["overall_score"] == 35 and first["authoritative_status"][0]["listing_state"] == "REGISTRY_NOT_SYNCED"
    assert first["findings"][0]["evidence"]["labels"][0]["source"] == "Synthetic analyst"
    assert client.patch(uri + f"/labels/{label_row['id']}/state", json={"active": False}).json()["active"] is False
    second = client.post(uri + "/lookup/address", json={"chain": "ethereum", "address": ETH}).json()["risk"]
    assert second["overall_score"] == 0 and second["findings"] == []
    assert client.patch(uri + f"/labels/{label_row['id']}/state", json={"active": True}).json()["active"] is True


def test_case_wallet_metadata_cannot_forge_gc_risk_snapshot(api_db):
    client, _, _ = api_db
    uri = "/api/greedy-collector"
    case = client.post(uri + "/cases", json={"title": "Unassessed fixture"}).json()
    result = client.post(uri + f"/cases/{case['id']}/entities", json={
        "entity_type": "wallet", "entity_ref": ETH,
        "metadata": {"chain": "ethereum", "address": "wrong", "risk_assessment": {"overall_score": 100}},
    })
    assert result.status_code == 200
    assert result.json()["metadata_json"]["address"] == ETH
    assert "risk_assessment" not in result.json()["metadata_json"]


def test_monero_local_direct_match_has_no_behavioral_claim(api_db):
    client, _, fixture = api_db
    fixture.data = source([(9, "Synthetic XMR listing", ["CYBER2"], [("XMR", MONERO_STANDARD)])])
    uri = "/api/greedy-collector"
    assert client.post(uri + "/sanctions/sync").status_code == 200
    response = client.get(uri + f"/risk/observation/monero/{MONERO_STANDARD}")
    assert response.status_code == 200, response.text
    risk = response.json()["risk"]
    assert risk["overall_tier"] == "CRITICAL" and risk["overall_score"] == 95
    assert risk["behavioral_score"] is None and risk["behavioral_exposure_score"] is None
    assert risk["data_coverage"]["status"] == "UNAVAILABLE"
    assert client.get(uri + f"/risk/observation/ethereum/{ETH}").status_code == 422


def test_v3_migration_isolated_database(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    url = "sqlite:///" + (tmp_path / "risk-v3.db").as_posix()
    monkeypatch.setenv("GREEDY_COLLECTOR_DATABASE_URL", url)
    cfg = Config(str(root / "alembic.ini"), stdout=StringIO())
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")
    engine = create_fk_enabled_engine(url)
    try:
        labels = {column["name"] for column in inspect(engine).get_columns("labels")}
        risk = {column["name"] for column in inspect(engine).get_columns("risk_results")}
        assert {"active", "archived_at"} <= labels
        assert "assessment" in risk
    finally:
        engine.dispose()
