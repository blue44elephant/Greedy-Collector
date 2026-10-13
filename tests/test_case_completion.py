"""CASE-2 contracts through real API/storage paths, using isolated SQLite only."""
import hashlib
import json
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from tests.test_attribution_api import api, migrated_template, API, ETH, BTC, ok
from tests.case2_material import seed, mutate, ETH as CANONICAL_ETH

@pytest.fixture
def case_material(api):
    import main
    from sqlalchemy.orm import sessionmaker
    from greedy_collector.discovery.router import get_runtime
    from greedy_collector.discovery.runtime import DiscoveryRuntime
    client, engine = api
    material = seed(engine)
    main.app.dependency_overrides[get_runtime] = lambda: DiscoveryRuntime(sessionmaker(engine, expire_on_commit=False))
    return client, engine, material

def pin_all(client, case_id, material):
    path = API + "/cases/" + case_id
    ok(client.post(path + "/entities", json={"entity_type": "wallet", "entity_ref": CANONICAL_ETH.upper().replace("0X", "0x"),
        "metadata": {"chain": "ethereum"}}))
    ok(client.post(path + "/risk-pins", json={"chain": "ethereum", "address": CANONICAL_ETH}))
    ok(client.post(API + "/sanctions/cases/" + case_id + "/pins/ethereum/" + CANONICAL_ETH))
    ok(client.post(API + "/attribution/cases/" + case_id + "/references", json={
        "reference_type": "attribution_claim", "target_id": material["claim_id"], "expected_version": material["claim_version"]}), 201)
    ok(client.post(path + "/discovery-pins", json={"run_id": material["run_id"]}))
    preview = ok(client.get(API + "/discovery/public-captures/" + material["capture_id"] + "/promotion-preview"))
    ok(client.post(API + "/discovery/public-captures/" + material["capture_id"] + "/cases/" + case_id + "/pin",
        json={"excerpt": CANONICAL_ETH, "expected_source_fingerprint": preview["source_fingerprint"]}), 201)
    ok(client.post(API + "/clustering/cases/" + case_id + "/pin", json={
        "cluster_id": material["cluster_id"], "version": material["cluster_version"]}))
    ok(client.post(API + "/fund-flow/cases/" + case_id + "/pin", json={"run_id": material["flow_id"]}))

@pytest.mark.parametrize("format", ["markdown", "html", "json", "pdf"])
def test_all_material_historical_reports_provenance_and_later_changes(case_material, format, tmp_path, monkeypatch):
    client, engine, material = case_material
    monkeypatch.chdir(tmp_path)
    row = create(client)
    path = API + "/cases/" + row["id"]
    pin_all(client, row["id"], material)
    before = ok(client.get(path))
    first = client.get(API + "/reports/" + row["id"] + "?format=" + format)
    assert first.status_code == 200, first.text if format != "pdf" else first.status_code
    mutate(engine, material)
    after = ok(client.get(path))
    assert after["entities"] == before["entities"] and after["sanctions_pins"] == before["sanctions_pins"]
    second = client.get(API + "/reports/" + row["id"] + "?format=" + format)
    assert second.status_code == 200
    assert second.headers["x-case-state-fingerprint"] == first.headers["x-case-state-fingerprint"]
    assert second.headers["x-report-id"] != first.headers["x-report-id"]
    assert client.get(path + "/reports/" + first.headers["x-report-id"]).content == first.content
    if format == "json":
        state = first.json()
        assert state["attribution"]["references"][0]["pinned"]["claim"]["assessment"] == "supported"
        assert "current" not in state["attribution"]["references"][0]
        assert material["capture_hash"] in first.text
    elif format != "pdf":
        for value in ["deterministic-v3", "CURRENTLY_LISTED", "Contradicting evidence", material["capture_hash"],
                      material["run_id"], material["cluster_id"], material["flow_id"], "not probabilities", "bounded", "UTXO"]:
            assert value in first.text, value
        assert "CASE2 contrary record" in first.text
        assert "Current assessment: rejected" not in second.text
    events = [e["kind"] for e in ok(client.get(path))["timeline"]]
    assert {"wallet_added", "risk_assessment_pinned", "sanctions_pinned", "attribution_claim_pinned",
            "broad_discovery_pinned", "public_source_capture_pinned", "technical_cluster_pinned", "fund_flow_pinned", "report_generated"} <= set(events)
    shared_tables = ["attribution_evidence", "discovery_observations", "sanctions_snapshots", "transactions"]
    with Session(engine) as db:
        counts = {t: db.scalar(text("SELECT count(*) FROM " + t)) for t in shared_tables}
    assert client.delete(path).status_code == 405
    latest = ok(client.get(path))
    ok(client.patch(path, json={"expected_version": latest["version"], "archived": True}))
    with Session(engine) as db:
        assert counts == {t: db.scalar(text("SELECT count(*) FROM " + t)) for t in shared_tables}

def test_chain_scoped_refs_and_transaction_event_identity(api):
    from greedy_collector.models import Transaction
    client, engine = api
    row = create(client)
    path = API + "/cases/" + row["id"]
    for chain in ["ethereum", "base"]:
        entry = ok(client.post(path + "/entities", json={"entity_type": "wallet", "entity_ref": ETH, "metadata": {"chain": chain}}))
        assert entry["entity_ref"] == ETH.lower() and entry["metadata_json"]["display_address"] == ETH
    assert client.post(path + "/entities", json={"entity_type": "wallet", "entity_ref": ETH.lower(),
        "metadata": {"chain": "ethereum"}}).status_code == 409
    txid = "0x" + "c"*64
    with Session(engine) as db:
        for index in range(2):
            db.add(Transaction(chain="ethereum", tx_hash=txid, event_key="erc20:"+str(index),
                event_index=str(index), token_symbol="TEST", value_native=str(index+1), source_api="test-only"))
        db.commit()
    assert client.post(path + "/entities", json={"entity_type": "transaction", "entity_ref": txid,
        "metadata": {"chain": "ethereum"}}).status_code == 422
    for index in range(2):
        entry = ok(client.post(path + "/entities", json={"entity_type": "transaction", "entity_ref": txid,
            "metadata": {"chain": "ethereum", "event_key": "erc20:"+str(index), "source_wallet": ETH}}))
        assert entry["metadata_json"]["transaction_snapshot"]["value_native"] == str(index+1)
        assert entry["metadata_json"]["source_wallet"] == ETH

def test_versioned_notes_archival_and_no_read_noise(api):
    client, _ = api
    path = API + "/cases/" + create(client)["id"]
    note = ok(client.post(path + "/notes", json={"body": "Earlier analyst decision"}))
    changed = ok(client.patch(path + "/notes/" + note["id"], json={"expected_version": note["version"], "body": "Revised decision"}))
    assert changed["version"] == 2 and changed["updated_at"] >= changed["created_at"]
    assert client.patch(path + "/notes/" + note["id"], json={"expected_version": 1, "body": "Stale"}).status_code == 409
    archived = ok(client.patch(path + "/notes/" + note["id"], json={"expected_version": 2, "archived": True}))
    assert archived["archived_at"]
    timeline = ok(client.get(path))["timeline"]
    event = next(e for e in timeline if e["kind"] == "note_updated")
    assert event["record"]["previous_body"] == "Earlier analyst decision"
    assert timeline == ok(client.get(path))["timeline"]
    assert [(e["created_at"], e["id"]) for e in timeline] == sorted((e["created_at"], e["id"]) for e in timeline)
    assert client.delete(path + "/notes/" + note["id"]).status_code == 405

@pytest.mark.parametrize("filename", ["../x", "..\\x", "C:\\evil.exe", "/tmp/x", ".."])
def test_attachment_traversal_names_are_rejected(api, filename, tmp_path, monkeypatch):
    client, _ = api
    monkeypatch.chdir(tmp_path)
    path = API + "/cases/" + create(client)["id"] + "/attachments"
    assert client.post(path, files={"file": (filename, b"fixture", "text/html")}).status_code == 422

def test_attachment_active_content_size_and_integrity(api, tmp_path, monkeypatch):
    client, engine = api
    monkeypatch.chdir(tmp_path)
    path = API + "/cases/" + create(client)["id"]
    row = ok(client.post(path + "/attachments", files={"file": ("unusual <> name.html", b"<script>bad()</script>", "text/html")}))
    assert "<" not in row["metadata_json"]["filename"] and row["metadata_json"]["original_filename"] == "unusual <> name.html"
    response = client.get(path + "/attachments/" + row["id"])
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["content-security-policy"] == "sandbox"
    from greedy_collector import cases
    monkeypatch.setattr(cases, "MAX_ATTACHMENT_BYTES", 3)
    assert client.post(path + "/attachments", files={"file": ("big.txt", b"1234")}).status_code == 413
    target = tmp_path / "data" / row["entity_ref"]
    target.write_bytes(b"Changed outside application")
    assert client.get(path + "/attachments/" + row["id"]).status_code == 422

@pytest.mark.parametrize("kind,metadata", [
    ("risk_assessment", {"risk_assessment": {"score": 1}}),
    ("technical_cluster", {"cluster_pin": {"id": "cluster"}}),
    ("fund_flow", {"fund_flow_pin": {"id": "run"}}),
    ("public_source_capture", {"public_source_capture_pin": {}}),
    ("attachment", {})])
def test_impossible_historical_pin_and_external_attachment_report_rejected(api, kind, metadata):
    from greedy_collector.models import CaseEntity
    client, engine = api
    row = create(client)
    with Session(engine) as db:
        db.add(CaseEntity(case_id=row["id"], entity_type=kind, entity_ref="../../outside-file", metadata_json=metadata))
        db.commit()
    response = client.get(API + "/reports/" + row["id"] + "?format=json")
    assert response.status_code == 422 and "outside-file" not in response.text

def test_reports_redact_configured_secrets_and_safe_names(api, monkeypatch):
    from greedy_collector.config import get_settings
    client, _ = api
    monkeypatch.setattr(get_settings(), "etherscan_api_key", "case2-secret-canary")
    row = create(client, title="../../unsafe <script> name")
    path = API + "/cases/" + row["id"]
    ok(client.post(path + "/notes", json={"body": "Source URL https://example.org/?api_key=case2-secret-canary and case2-secret-canary"}))
    response = client.get(API + "/reports/" + row["id"] + "?format=json")
    assert response.status_code == 200 and "case2-secret-canary" not in response.text
    assert "unsafe" not in response.headers["content-disposition"]
    assert "/" not in response.headers["content-disposition"]

def test_case_search_sort_literal_and_stored_label(api):
    from greedy_collector.models import Label
    client, engine = api
    a, b = create(client, title="Alpha %"), create(client, title="Beta")
    with Session(engine) as db:
        label = Label(chain="ethereum", address=ETH, label="Stored entity name", source="Fixture", type="Exchange", confidence=.7)
        db.add(label);db.commit();identifier=label.id
    ok(client.post(API + "/cases/" + b["id"] + "/entities", json={"entity_type": "label", "entity_ref": identifier}))
    assert client.get(API + "/cases?q=%25").json()["cases"][0]["id"] == a["id"]
    assert client.get(API + "/cases?q=Stored%20entity%20name").json()["cases"][0]["id"] == b["id"]
    assert [r["id"] for r in client.get(API + "/cases?sort=title").json()["cases"]] == [a["id"], b["id"]]

def test_sql_and_orm_history_protection_and_conflict_rollback(api):
    from greedy_collector.models import Case, CaseEntity, CaseEvent
    from sqlalchemy.orm.exc import StaleDataError
    client, engine = api
    row = create(client)
    with Session(engine) as first, Session(engine) as second:
        a, b = first.get(Case, row["id"]), second.get(Case, row["id"])
        a.title = "First";first.commit()
        b.title = "Lost edit"
        with pytest.raises(StaleDataError):second.commit()
        second.rollback()
    assert ok(client.get(API+"/cases/"+row["id"]))["title"] == "First"
    entry = ok(client.post(API+"/cases/"+row["id"]+"/entities", json={"entity_type":"wallet","entity_ref":BTC,"metadata":{"chain":"bitcoin"}}))
    with Session(engine) as db:
        db.get(CaseEntity, entry["id"]).metadata_json = {"forged": True}
        with pytest.raises(ValueError):db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text("DELETE FROM case_events WHERE case_id=:id"), {"id":row["id"]});db.commit()

def test_pdf_long_source_unicode_and_source_script_escaping(api, monkeypatch):
    from reportlab.platypus import Paragraph
    client, _ = api
    row = create(client, title="Unicode Ελληνικά 中文")
    body = "<script>bad()</script>\n" + "https://source.example/" + "a"*3000 + "\n" + "Contradiction retained " * 500
    ok(client.post(API+"/cases/"+row["id"]+"/notes", json={"body":body}))
    paragraphs=[]
    original=Paragraph.__init__
    def record(self, value, *args, **kwargs):
        if isinstance(value, str):paragraphs.append(value)
        original(self,value,*args,**kwargs)
    monkeypatch.setattr(Paragraph,"__init__",record)
    response=client.get(API+"/reports/"+row["id"]+"?format=pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert all("<script>" not in value for value in paragraphs)
    assert any("a"*3000 in value for value in paragraphs)
    assert any("Ελληνικά" in value for value in paragraphs)
    html=client.get(API+"/reports/"+row["id"]+"?format=html")
    assert "<script>" not in html.text and "&lt;script&gt;" in html.text

def test_non_broad_run_pin_preserves_terminal_sources_and_results(case_material):
    from greedy_collector.discovery.service import DiscoveryService
    from uuid import uuid4
    client, engine, _ = case_material
    with Session(engine) as db:
        svc = DiscoveryService(db)
        subject = svc.get_or_create_subject("blockchain_address", "ethereum", CANONICAL_ETH)
        run = svc.create_run(subject["id"], [{"transform_id": "wallet.local_labels", "source_id": "gc_labels"}],
            idempotency_key=str(uuid4()))
        run = svc.transition_run(run["id"], "running", expected_version=run["version"])
        svc.transition_source(run["sources"][0]["id"], "running", expected_run_version=run["version"])
        run = svc.get_run(run["id"])
        svc.record_batch(run["sources"][0]["id"], [], expected_run_version=run["version"])
        run = svc.get_run(run["id"])
        svc.transition_run(run["id"], "completed", expected_version=run["version"])
    row = create(client)
    entry = ok(client.post(API+"/cases/"+row["id"]+"/discovery-pins", json={"run_id":run["id"]}))
    pin = entry["metadata_json"]["discovery_run_pin"]
    assert pin["run"]["id"] == run["id"] and pin["run"]["status"] == "completed"
    assert pin["results"] == [] and pin["observations"] == [] and pin["source_data_fingerprint"]
    assert pin["run"]["sources"][0]["source_id"] == "gc_labels"
    assert pin["partial"] is False

def test_case2_migration_preserves_legacy_case_note_and_reference_times(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from io import StringIO
    from pathlib import Path
    from greedy_collector.database import create_fk_enabled_engine
    root = Path(__file__).resolve().parents[1]
    url = "sqlite:///" + (tmp_path/"legacy.db").as_posix()
    monkeypatch.setenv("GREEDY_COLLECTOR_DATABASE_URL", url)
    cfg = Config(str(root/"alembic.ini"), stdout=StringIO())
    cfg.set_main_option("script_location", str(root/"migrations"))
    command.upgrade(cfg, "20261012_01_risk_labels_v3")
    engine = create_fk_enabled_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cases (id,title,description,status,created_at,updated_at) VALUES ('legacy','Legacy','Known description','Closed','2026-01-01','2026-01-02')"))
        connection.execute(text("INSERT INTO analyst_notes (id,case_id,body,author,created_at) VALUES ('note','legacy','Known body','analyst','2026-01-01')"))
        connection.execute(text("INSERT INTO case_entities (id,case_id,entity_type,entity_ref,metadata_json) VALUES ('ref','legacy','graph_snapshot','reference','{}')"))
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT title,status,version,summary FROM cases WHERE id='legacy'")).one()
        assert row[:3] == ("Legacy", "Closed", 1) and json.loads(row[3]) == {}
        assert connection.scalar(text("SELECT body FROM analyst_notes WHERE id='note'")) == "Known body"
        assert connection.scalar(text("SELECT updated_at FROM analyst_notes WHERE id='note'")) == "2026-01-01"
        assert connection.scalar(text("SELECT added_at FROM case_entities WHERE id='ref'")) is None
        assert connection.scalar(text("SELECT kind FROM case_events WHERE case_id='legacy'")) == "case_created"
    engine.dispose()

def test_case_completion_assets_and_controls(api):
    client, _ = api
    source=client.get("/static/js/cases.js").text + client.get("/static/js/case_completion.js").text
    for token in ["case-search", "case-lifecycle", "case-summary", "case-counts", "case-timeline", "case-report-history",
                  "View pinned risk assessment", "Pin stored risk assessment", "Archive case", "Restore case",
                  "Save note", "Archive note", "Download attachment", "Download stored report", "Open live Discovery run",
                  "Open current cluster", "Open stored Fund Flow run"]:
        assert token in source, token
    assert "innerHTML" not in source

def create(client, **values):
    return ok(client.post(API + "/cases", json={"title": "Historical case", **values}))

def test_lifecycle_summary_stale_write_and_archive(api):
    client, _ = api
    original = create(client)
    path = API + "/cases/" + original["id"]
    changed = ok(client.patch(path, json={"expected_version": original.get("version", 1),
        "title": "Renamed", "status": "Paused", "summary": {"scope": "Analyst scope", "limitations": "Bounded"}}))
    assert changed["id"] == original["id"] and changed["version"] > original.get("version", 1)
    assert client.patch(path, json={"expected_version": 1, "title": "Lost edit"}).status_code == 409
    archived = ok(client.patch(path, json={"expected_version": changed["version"], "archived": True}))
    assert archived["archived_at"]
    assert not client.get(API + "/cases").json()["cases"]
    assert client.get(API + "/cases?include_archived=true&q=Renamed").json()["cases"][0]["id"] == original["id"]
    restored = ok(client.patch(path, json={"expected_version": archived["version"], "archived": False}))
    assert restored["status"] == "Paused" and restored["archived_at"] is None
    detail = ok(client.get(path))
    assert [e["kind"] for e in detail["timeline"]] == ["case_created", "case_updated", "case_archived", "case_restored"]
    before = detail["timeline"]
    assert ok(client.get(path))["timeline"] == before

def test_duplicate_attachment_hash_and_safe_download(api, tmp_path, monkeypatch):
    client, _ = api
    monkeypatch.chdir(tmp_path)
    row = create(client)
    path = API + "/cases/" + row["id"]
    first = ok(client.post(path + "/attachments", files={"file": ("same.txt", b"first", "text/plain")}))
    second = ok(client.post(path + "/attachments", files={"file": ("same.txt", b"second", "text/plain")}))
    assert first["entity_ref"] != second["entity_ref"]
    assert first["metadata_json"]["sha256"] == hashlib.sha256(b"first").hexdigest()
    assert first["metadata_json"]["original_filename"] == "same.txt"
    response = client.get(path + "/attachments/" + first["id"])
    assert response.content == b"first" and "attachment;" in response.headers["content-disposition"]
    assert client.post(path + "/attachments", files={"file": ("../escape.txt", b"x")}).status_code == 422

@pytest.mark.parametrize("format", ["markdown", "html", "json", "pdf"])
def test_report_history_hash_exact_state_and_immutable_bytes(api, format):
    client, engine = api
    row = create(client, title="Literal <script>alert(1)</script>")
    path = API + "/cases/" + row["id"]
    ok(client.post(path + "/notes", json={"body": "Analyst note [bad](javascript:alert(1))"}))
    response = client.get(API + "/reports/" + row["id"] + "?format=" + format)
    assert response.status_code == 200
    report_id = response.headers["x-report-id"]
    digest = hashlib.sha256(response.content).hexdigest()
    history = ok(client.get(path + "/reports"))["reports"]
    assert history[0]["sha256"] == digest and history[0]["state_fingerprint"]
    old = client.get(path + "/reports/" + report_id)
    assert old.content == response.content
    current = ok(client.get(path))
    ok(client.patch(path, json={"expected_version": current["version"], "title": "Later title"}))
    new = client.get(API + "/reports/" + row["id"] + "?format=" + format)
    assert new.status_code == 200 and new.headers["x-report-id"] != report_id
    assert client.get(path + "/reports/" + report_id).content == old.content
    if format == "html":
        assert "<script>" not in response.text and "&lt;script&gt;" in response.text
    if format == "json":
        assert response.json()["report"]["schema_version"] and response.json()["case"]["title"] != "Later title"
    with Session(engine) as db:
        with pytest.raises(Exception):
            db.execute(text("UPDATE case_reports SET sha256='changed' WHERE id=:id"), {"id": report_id})
            db.commit()

