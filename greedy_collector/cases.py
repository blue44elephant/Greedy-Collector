"""Local Case commands and immutable report generation. No provider calls."""
from hashlib import sha256
from pathlib import Path
import json
import re
from uuid import uuid4
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, or_, Text
from sqlalchemy.orm.exc import StaleDataError
from .models import (Case, CaseEntity, AnalystNote, CaseEvent, CaseReport, SanctionsCasePin,
                     Transaction, Label, WalletAlert, utcnow)
from .attribution.handoff import safe_snapshot

GENERATOR_VERSION = "case-2.0"
SCHEMA_VERSION = 2
MEDIA = {"markdown": "text/markdown", "html": "text/html", "json": "application/json", "pdf": "application/pdf"}
EXTENSIONS = {"markdown": "md", "html": "html", "json": "json", "pdf": "pdf"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

def data(row):
    return jsonable_encoder({c.name: getattr(row, c.name) for c in row.__table__.columns})

def get_case(db, identifier):
    row = db.get(Case, identifier)
    if row is None:
        raise HTTPException(404, "Case not found")
    return row

def commit(db):
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "Case or note changed. Reload before saving.") from None

def locked(db):
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

def update_case(db, identifier, payload):
    locked(db)
    row = get_case(db, identifier)
    if row.version != payload.expected_version:
        raise HTTPException(409, "Case changed. Reload before saving.")
    values = payload.model_dump(exclude_unset=True)
    values.pop("expected_version")
    archive = values.pop("archived", None)
    for key, value in values.items():
        setattr(row, key, value)
    if archive is not None:
        row.archived_at = utcnow() if archive else None
    commit(db)
    return data(row)

def list_cases(db, q="", status=None, include_archived=False, sort="updated"):
    query = select(Case)
    if not include_archived:
        query = query.where(Case.archived_at.is_(None))
    if status:
        query = query.where(Case.status == status)
    if q.strip():
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        refs = select(CaseEntity.case_id).where(or_(CaseEntity.entity_ref.ilike(term, escape="\\"),
            CaseEntity.metadata_json.cast(Text).ilike(term, escape="\\")))
        query = query.where(or_(Case.title.ilike(term, escape="\\"), Case.id.in_(refs)))
    order = {"updated": Case.updated_at.desc(), "created": Case.created_at.desc(),
             "title": Case.title.asc(), "status": Case.status.asc()}[sort]
    return {"cases": [data(row) for row in db.scalars(query.order_by(order, Case.id))]}

def report_metadata(row):
    return jsonable_encoder({c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in ("content", "state")})

def detail(db, identifier):
    case = get_case(db, identifier)
    entities = [data(r) for r in db.scalars(select(CaseEntity).where(CaseEntity.case_id == identifier).order_by(CaseEntity.added_at, CaseEntity.id))]
    notes = [data(r) for r in db.scalars(select(AnalystNote).where(AnalystNote.case_id == identifier).order_by(AnalystNote.created_at, AnalystNote.id))]
    sanctions = [data(r) for r in db.scalars(select(SanctionsCasePin).where(SanctionsCasePin.case_id == identifier).order_by(SanctionsCasePin.captured_at, SanctionsCasePin.id))]
    reports = [report_metadata(r) for r in db.scalars(select(CaseReport).where(CaseReport.case_id == identifier).order_by(CaseReport.generated_at.desc(), CaseReport.id))]
    counts = {}
    for row in entities:
        kind = row["entity_type"]
        counts[kind] = counts.get(kind, 0) + 1
    counts.update(notes=sum(not n["archived_at"] for n in notes), attachments=counts.get("attachment", 0),
                  reports=len(reports), sanctions=len(sanctions))
    return {**data(case), "entities": entities, "notes": notes,
        "alerts": [data(r) for r in db.scalars(select(WalletAlert).where(WalletAlert.case_id == identifier).order_by(WalletAlert.timestamp, WalletAlert.id))],
        "sanctions_pins": sanctions, "reports": reports, "counts": counts,
        "timeline": [data(r) for r in db.scalars(select(CaseEvent).where(CaseEvent.case_id == identifier).order_by(CaseEvent.created_at, CaseEvent.id))]}

def add_reference(db, identifier, payload):
    get_case(db, identifier)
    metadata = dict(payload.metadata)
    reference = payload.entity_ref.strip()
    kind = payload.entity_type
    # Pin-only keys are always server-owned.
    for key in tuple(metadata):
        if key.endswith("_pin") or key in ("risk_assessment", "label_snapshot"):
            metadata.pop(key)
    if kind == "attachment":
        raise HTTPException(422, "Upload attachments through the attachment endpoint.")
    if kind in ("wallet", "transaction") and metadata.get("chain"):
        from .chains import get_chain
        adapter = get_chain(metadata["chain"]).adapter()
        try:
            canonical = adapter.normalize_address(reference) if kind == "wallet" else adapter.normalize_transaction_id(reference)
        except ValueError:
            raise HTTPException(422, "The reference does not match the selected chain.") from None
        metadata.update({"display_address" if kind == "wallet" else "display_tx_hash": reference,
                         "address" if kind == "wallet" else "tx_hash": canonical})
        reference = canonical
        existing = db.scalars(select(CaseEntity).where(CaseEntity.case_id == identifier, CaseEntity.entity_type == kind, CaseEntity.entity_ref == reference)).all()
        if any((r.metadata_json or {}).get("chain") == metadata["chain"] and
               (kind == "wallet" or (r.metadata_json or {}).get("event_key", "tx") == metadata.get("event_key", "tx")) for r in existing):
            raise HTTPException(409, "This chain-scoped reference is already in the Case.")
        if kind == "transaction":
            rows = db.scalars(select(Transaction).where(Transaction.chain == metadata["chain"], Transaction.tx_hash == canonical).order_by(Transaction.event_key)).all()
            if len(rows) > 1 and not metadata.get("event_key"):
                raise HTTPException(422, "Choose the transaction event; multiple stored events share this identifier.")
            tx = next((r for r in rows if r.event_key == metadata.get("event_key", "tx")), None)
            if tx:
                metadata["transaction_snapshot"] = safe_snapshot({k: v for k, v in data(tx).items() if k != "raw_payload"})
        else:
            # Compatibility: existing wallet additions capture the latest stored risk,
            # never calculate or fetch. A separate explicit pin can capture later revisions.
            from .router import service
            from .chains import Capability
            assessment = service.address_risk(db, metadata["chain"], reference) if Capability.RISK in get_chain(metadata["chain"]).capabilities else None
            if assessment and (assessment.get("model_version") or assessment.get("scoring_model")):
                metadata["risk_assessment"] = jsonable_encoder(assessment)
    if kind == "label":
        label = db.get(Label, reference)
        if label is None:
            raise HTTPException(422, "Stored label not found.")
        metadata["label_snapshot"] = data(label)
    row = CaseEntity(case_id=identifier, entity_type=kind, entity_ref=reference, metadata_json=safe_snapshot(metadata))
    db.add(row)
    commit(db)
    return data(row)

def pin_risk(db, identifier, chain, address):
    locked(db)
    get_case(db, identifier)
    from .chains import get_chain
    try:
        canonical = get_chain(chain).adapter().normalize_address(address)
    except ValueError:
        raise HTTPException(422, "Unsupported wallet reference.") from None
    from .router import service
    try:
        assessment = service.address_risk(db, chain, canonical)
    except ValueError:
        raise HTTPException(422, "Risk assessment is unavailable for this chain.") from None
    if not assessment:
        raise HTTPException(422, "No stored risk assessment is available. Investigate the wallet first.")
    if not assessment.get("model_version"):
        raise HTTPException(422, "Risk pin requires a model version.")
    row = CaseEntity(case_id=identifier, entity_type="risk_assessment", entity_ref=assessment["id"],
        metadata_json={"chain": chain, "address": canonical, "risk_assessment": safe_snapshot(assessment)})
    db.add(row)
    commit(db)
    return data(row)

def pin_discovery(db, identifier, run_id):
    get_case(db, identifier)
    from .discovery.service import DiscoveryService
    from .models import DiscoverySubject, DiscoveryRunItem, DiscoveryRunSource, DiscoveryResult, DiscoveryObservation, DiscoveryReview
    svc = DiscoveryService(db)
    locked(db)
    run = svc.get_run(run_id)
    if run["status"] in ("queued", "running"):
        raise HTTPException(409, "Wait for the Discovery run to finish before pinning.")
    if run.get("request_snapshot", {}).get("execution_policy", {}).get("broad"):
        from .discovery.broad.service import BroadService
        from .discovery.execution_service import ExecutionService
        return BroadService(db, ExecutionService(db)).pin(identifier, run_id)
    items = db.scalars(select(DiscoveryRunItem).join(DiscoveryRunSource, DiscoveryRunItem.run_source_id == DiscoveryRunSource.id).where(DiscoveryRunSource.run_id == run_id).order_by(DiscoveryRunSource.ordinal, DiscoveryRunItem.ordinal)).all()
    observations = [data(db.get(DiscoveryObservation, r.observation_id)) for r in items]
    result_ids = sorted({o["result_id"] for o in observations})
    snapshot = safe_snapshot({"schema_version": 1, "captured_at": utcnow(), "run": run,
        "subject": data(db.get(DiscoverySubject, run["subject_id"])), "items": [data(r) for r in items],
        "observations": observations, "results": [svc.get_result(i) for i in result_ids],
        "reviews": [data(r) for r in db.scalars(select(DiscoveryReview).where(DiscoveryReview.result_id.in_(result_ids)).order_by(DiscoveryReview.result_id, DiscoveryReview.sequence))],
        "partial": run["status"] != "completed", "truncated": any(s["coverage"] in ("provider_incomplete", "limit_reached") for s in run["sources"])})
    snapshot["source_data_fingerprint"] = digest(snapshot)
    row = CaseEntity(case_id=identifier, entity_type="discovery_run", entity_ref=run_id, metadata_json={"discovery_run_pin": snapshot})
    db.add(row)
    commit(db)
    return data(row)

def update_note(db, identifier, note_id, payload):
    locked(db)
    get_case(db, identifier)
    note = db.get(AnalystNote, note_id)
    if not note or note.case_id != identifier:
        raise HTTPException(404, "Note not found")
    if note.version != payload.expected_version:
        raise HTTPException(409, "Note changed. Reload before saving.")
    if payload.body is not None:
        note.body = payload.body
    if payload.archived is not None:
        note.archived_at = utcnow() if payload.archived else None
    commit(db)
    return data(note)

def storage_root():
    return Path("./data").resolve()

def attachment_path(identifier, reference):
    root = storage_root()
    base = (root / "greedy_collector_cases").resolve()
    if any(c in identifier for c in ("/", "\\", "\0")) or identifier in (".", ".."):
        raise HTTPException(422, "Invalid Case storage identity.")
    directory = (base / identifier).resolve()
    target = (root / reference).resolve()
    if not base.is_relative_to(root) or not directory.is_relative_to(base) or not target.is_relative_to(directory):
        raise HTTPException(422, "Attachment reference is outside Case storage.")
    return target

def store_attachment(db, identifier, filename, content_type, content, note=""):
    get_case(db, identifier)
    original = filename or "attachment"
    if any(c in original for c in ("/", "\\", "\0")) or original in (".", ".."):
        raise HTTPException(422, "Attachment filename must not contain a path.")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "Attachment exceeds the 20 MiB limit.")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", original)[:150].strip(".") or "attachment"
    reference = (Path("greedy_collector_cases") / identifier / (str(uuid4()) + "-" + name)).as_posix()
    target = attachment_path(identifier, reference)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(content)
    row = CaseEntity(case_id=identifier, entity_type="attachment", entity_ref=reference,
        metadata_json={"filename": name, "original_filename": original, "content_type": content_type or "application/octet-stream",
                       "size": len(content), "sha256": sha256(content).hexdigest(), "note": note})
    try:
        db.add(row)
        commit(db)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return data(row)

def attachment(db, identifier, attachment_id):
    get_case(db, identifier)
    row = db.get(CaseEntity, attachment_id)
    if not row or row.case_id != identifier or row.entity_type != "attachment":
        raise HTTPException(404, "Attachment not found")
    target = attachment_path(identifier, row.entity_ref)
    if not target.is_file():
        raise HTTPException(404, "Attachment bytes are unavailable")
    expected = row.metadata_json.get("sha256")
    if expected and sha256(target.read_bytes()).hexdigest() != expected:
        raise HTTPException(422, "Attachment integrity check failed.")
    return row, target

def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

def validate_state(state):
    for row in state["entities"]:
        kind, metadata = row["entity_type"], row["metadata_json"] or {}
        if not isinstance(metadata, dict):
            raise HTTPException(422, "Case reference metadata is incompatible.")
        if kind.startswith("narcotics_"):
            pin = metadata.get("narcotics_pin")
            if not isinstance(pin, dict) or not pin.get("snapshot") or digest(pin["snapshot"]) != pin.get("snapshot_fingerprint"):
                raise HTTPException(422, "Case contains an incompatible narcotics intelligence pin.")
        if kind == "attachment":
            target = attachment_path(state["case"]["id"], row["entity_ref"])
            if metadata.get("sha256") and (not target.is_file() or sha256(target.read_bytes()).hexdigest() != metadata["sha256"]):
                raise HTTPException(422, "Attachment integrity check failed.")
        risk = metadata.get("risk_assessment")
        if risk is not None and (not isinstance(risk, dict) or not (risk.get("model_version") or risk.get("scoring_model"))):
            raise HTTPException(422, "Risk assessment is missing its model version.")
        checks = {"technical_cluster": ("cluster_pin", ("id", "version")),
                  "fund_flow": ("fund_flow_pin", ("id", "algorithm_version", "source_data_fingerprint")),
                  "public_source_capture": ("public_source_capture_pin", ("capture",)),
                  "broad_discovery": ("broad_discovery_pin", ("run", "source_data_fingerprint")),
                  "discovery_run": ("discovery_run_pin", ("run", "source_data_fingerprint"))}
        if kind in checks:
            key, required = checks[kind]
            pin = metadata.get(key)
            if not isinstance(pin, dict) or any(not pin.get(k) for k in required):
                raise HTTPException(422, "Case contains an incomplete historical pin.")
            if kind == "technical_cluster" and (type(pin["version"]) is not int or pin["version"] < 1):
                raise HTTPException(422, "Cluster pin has an impossible version.")
            if kind == "public_source_capture":
                capture = pin["capture"]
                if not capture.get("id") or not capture.get("body_sha256"):
                    raise HTTPException(422, "Capture pin is missing its source identity or hash.")
    for pin in state["sanctions_pins"]:
        record = pin["record"]
        screening = record.get("screening") if isinstance(record, dict) else None
        snap = screening.get("snapshot") if isinstance(screening, dict) else None
        if not isinstance(snap, dict):
            raise HTTPException(422, "Sanctions pin is incompatible.")
        if not snap.get("id") or not snap.get("sha256"):
            raise HTTPException(422, "Sanctions pin is missing its source snapshot identity.")

def generate_report(db, identifier, format):
    if format not in MEDIA:
        raise HTTPException(422, "Unsupported report format.")
    locked(db)
    current = detail(db, identifier)
    from .narcotics.service import profile_snapshot
    narcotics_profile = profile_snapshot(db, identifier)
    from .attribution.cases import report_attribution
    attribution = report_attribution(db, identifier, historical=True)
    from .attribution.reporting import DISCLAIMER as attribution_disclaimer
    attribution["disclaimer"] = attribution_disclaimer
    # Use historical claim/entity/link state only, retaining immutable evidence bytes.
    for item in attribution["references"]:
        item.pop("current", None)
        for evidence in item["evidence"]:
            evidence.pop("current_link", None)
    attribution.pop("generated_at", None)
    state = safe_snapshot({"case": {k: v for k, v in current.items() if k not in
        ("entities", "notes", "alerts", "reports", "timeline", "counts", "sanctions_pins")},
        "entities": current["entities"], "notes": current["notes"], "alerts": current["alerts"],
        "sanctions_pins": current["sanctions_pins"], "attribution": attribution})
    if narcotics_profile:
        state["narcotics_profile"] = safe_snapshot(narcotics_profile)
    validate_state(state)
    report = CaseReport(id=str(uuid4()), case_id=identifier, format=format, generated_at=utcnow(),
        generator_version=GENERATOR_VERSION, schema_version=SCHEMA_VERSION, state_fingerprint=digest(state), state=state)
    from .case_reporting import render
    metadata = {k: jsonable_encoder(getattr(report, k)) for k in ("id", "case_id", "format", "generated_at", "generator_version", "schema_version", "state_fingerprint")}
    report.content = render(state, metadata, format)
    report.sha256 = sha256(report.content).hexdigest()
    db.add(report)
    commit(db)
    return report
