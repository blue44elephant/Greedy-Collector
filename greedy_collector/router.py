import csv
from io import StringIO
import os
from pathlib import Path
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select

from .chains.base import ChainDataError
from .chains import list_chains
from .chain_types import ChainName
from .database import get_db
from .kyc import SOURCE_CATALOG
from .models import AnalystNote, Case, CaseEntity, KycMatch, Label, MonitoringRun, WatchlistWallet
from .schemas import (
    AlertUpdate,
    AnalystNoteCreate,
    CaseCreate,
    CaseUpdate, NoteUpdate, CaseRiskPin, CaseDiscoveryPin,
    CaseEntityCreate,
    KycQuery,
    KycReviewUpdate,
    LookupRequest,
    ResolveRequest,
    ManualLabelCreate,
    LabelStateUpdate,
    TransactionLookupRequest,
    WatchlistCreate,
    WatchlistUpdate,
)
from .services import GreedyCollectorService, row_dict
from .resolver import resolve_identifier


router = APIRouter(prefix="/api/greedy-collector", tags=["Greedy Collector"])
service = GreedyCollectorService()


def _provider_error(exc: ChainDataError, chain: str | None = None) -> str:
    if "ETHERSCAN_API_KEY" in str(exc):
        from .chains import get_chain
        name=get_chain(chain).display_name if chain else "Blockchain"
        return f"{name} provider configuration is unavailable."
    if "ALCHEMY_API_KEY" in str(exc):
        return "Ethereum provider configuration is unavailable."
    if "tron_configuration_unavailable" in str(exc):
        return "TRON provider configuration is unavailable."
    if "solana_configuration_unavailable" in str(exc):
        return "Solana RPC configuration is unavailable."
    if "litecoin_configuration_unavailable" in str(exc):
        return "Litecoin provider configuration is unavailable."
    return "Blockchain provider request failed. Try again later."


@router.get("/status")
def status():
    from .monitoring import monitoring_status

    return {
        "enabled": True,
        "supported_chains": [d.chain_id for d in reversed(list_chains())],
        "backends": {
            "graph": service.graph_store.status(),
            "monitoring": monitoring_status(),
        },
        "capabilities": [
            "address_lookup",
            "transaction_lookup",
            "risk_scoring",
            "graph",
            "watchlist",
            "alerts",
            "cases",
            "labels",
            "kyc_screening",
            "sanctions_screening",
            "reports",
        ],
    }


@router.get("/chains")
def chain_metadata():
    return {"chains": [d.public_metadata() for d in list_chains()]}


@router.post("/resolve")
def resolve(payload: ResolveRequest):
    return resolve_identifier(payload.input, payload.chain_hint)


@router.post("/lookup/address")
async def lookup_address(payload: LookupRequest, db: Session = Depends(get_db)):
    try:
        return await service.lookup_address(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChainDataError as exc:
        raise HTTPException(status_code=502, detail=_provider_error(exc, payload.chain)) from exc


@router.post("/lookup/tx")
async def lookup_tx(payload: TransactionLookupRequest):
    try:
        return await service.lookup_transaction(payload.chain, payload.tx_hash)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChainDataError as exc:
        raise HTTPException(status_code=502, detail=_provider_error(exc, payload.chain)) from exc


@router.get("/address/{chain}/{address}")
def address(chain: ChainName, address: str, db: Session = Depends(get_db)):
    result = service.address_record(db, chain, address)
    if not result:
        raise HTTPException(status_code=404, detail="Address has not been looked up")
    return result


@router.get("/address/{chain}/{address}/transactions")
def transactions(chain: ChainName, address: str, db: Session = Depends(get_db)):
    return {"transactions": service.address_transactions(db, chain, address)}


@router.get("/address/{chain}/{address}/graph")
def graph(
    chain: ChainName,
    address: str,
    hops: int = Query(default=1, ge=1, le=3),
    db: Session = Depends(get_db),
):
    return service.address_graph(db, chain, address, hops)


@router.get("/address/{chain}/{address}/risk")
def risk(chain: ChainName, address: str, db: Session = Depends(get_db)):
    result = service.address_risk(db, chain, address)
    if not result:
        raise HTTPException(status_code=404, detail="No risk result is available")
    return result


@router.get("/risk/observation/{chain}/{address}")
def observation_risk(chain: ChainName, address: str, db: Session = Depends(get_db)):
    """Local-only risk assessment when public address history is unavailable."""
    if chain != "monero":
        raise HTTPException(status_code=422, detail="Observation-only risk is available for Monero addresses")
    from datetime import datetime, timezone
    from .chains import get_chain_adapter
    from .sanctions.service import screen

    canonical = get_chain_adapter(chain).normalize_address(address)
    sanctions = screen(db, chain, canonical)
    labels = service._labels_for_transactions(db, [], chain, canonical)
    assessment = service.risk_engine.evaluate(
        canonical, [], labels, include_behavioral=False, chain=chain,
        sanctions=sanctions, coverage={"status": "UNAVAILABLE", "records_returned": 0},
    )
    assessment["calculated_at"] = datetime.now(timezone.utc).isoformat()
    return {"risk": assessment, "sanctions_screening": sanctions}


@router.post("/watchlist")
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    if payload.case_id and not db.get(Case, payload.case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        return service.add_watchlist(db, payload)
    except ValueError as exc:
        detail = getattr(exc, "code", None)
        if detail == "unsupported_chain_capability":
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(status_code=422, detail="Invalid public wallet address") from exc


@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db)):
    return {"wallets": service.watchlist(db)}


@router.patch("/watchlist/{wallet_id}")
def update_watchlist(wallet_id: str, payload: WatchlistUpdate, db: Session = Depends(get_db)):
    row = db.get(WatchlistWallet, wallet_id)
    if not row:
        raise HTTPException(status_code=404, detail="Watchlist wallet not found")
    data = payload.model_dump(exclude_unset=True)
    if any(value is None for key, value in data.items() if key != "case_id"):
        raise HTTPException(status_code=422, detail="Only case_id may be null")
    if data.get("case_id") is not None and not db.get(Case, data["case_id"]):
        raise HTTPException(status_code=404, detail="Case not found")
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    return row_dict(row)


def _run_response(row: MonitoringRun) -> dict:
    data = row_dict(row)
    # Persisted provider exceptions can contain credential-bearing URLs.
    if row.status == "failed":
        data["error"] = "Monitoring check failed. Verify server provider configuration and try again."
    elif row.status == "continuity_loss":
        data["error"] = "The previous transaction boundary is missing from the fetched history. Boundary preserved; ambiguous activity was not alerted."
    else:
        data["error"] = None
    return data


@router.get("/watchlist/{wallet_id}/runs")
def watchlist_runs(wallet_id: str, limit: int = Query(50, ge=1, le=200),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if not db.get(WatchlistWallet, wallet_id):
        raise HTTPException(status_code=404, detail="Watchlist wallet not found")
    rows = db.scalars(select(MonitoringRun).where(MonitoringRun.wallet_id == wallet_id)
                      .order_by(MonitoringRun.started_at.desc(), MonitoringRun.id.desc())
                      .offset(offset).limit(limit)).all()
    total = db.scalar(select(func.count(MonitoringRun.id)).where(MonitoringRun.wallet_id == wallet_id))
    return {"runs": [_run_response(row) for row in rows], "total": total}


@router.post("/watchlist/{wallet_id}/check")
async def check_watchlist(wallet_id: str, db: Session = Depends(get_db)):
    from .monitoring import monitor_chain

    row = db.get(WatchlistWallet, wallet_id)
    if not row:
        raise HTTPException(status_code=404, detail="Watchlist wallet not found")
    if not row.enabled:
        raise HTTPException(status_code=409, detail="Enable the watch before checking it")
    chain = row.chain
    # Release the read transaction before monitoring opens its own session.
    db.rollback()
    result = await monitor_chain(chain, wallet_id=wallet_id)
    if result.get("busy"):
        raise HTTPException(status_code=409, detail="A check for this chain is already running")
    if not result.get("run_ids"):
        raise HTTPException(status_code=409, detail="Watch is no longer enabled")
    db.expire_all()
    run = db.get(MonitoringRun, result["run_ids"][0])
    return {"wallet": row_dict(db.get(WatchlistWallet, wallet_id)), "run": _run_response(run)}


@router.delete("/watchlist/{wallet_id}")
def delete_watchlist(wallet_id: str, db: Session = Depends(get_db)):
    from .models import WatchlistWallet

    row = db.get(WatchlistWallet, wallet_id)
    if not row:
        raise HTTPException(status_code=404, detail="Watchlist wallet not found")
    if db.scalar(select(MonitoringRun.id).where(MonitoringRun.wallet_id == wallet_id).limit(1)):
        raise HTTPException(status_code=409, detail="Watch has monitoring history; disable it to preserve history")
    db.delete(row)
    db.commit()
    return {"deleted": wallet_id}


@router.get("/alerts")
def alerts(status: str | None = None, db: Session = Depends(get_db)):
    return {"alerts": service.alerts(db, status)}


@router.patch("/alerts/{alert_id}")
def update_alert(
    alert_id: str, payload: AlertUpdate, db: Session = Depends(get_db)
):
    from .models import WalletAlert

    row = db.get(WalletAlert, alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    data = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else payload.dict(exclude_none=True)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    return row_dict(row)


@router.post("/cases")
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    row = Case(**(payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row_dict(row)


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    result = service.case_detail(db, case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.get("/cases")
def list_cases(q: str = Query(default="", max_length=255),
    status: str | None = Query(default=None, pattern="^(Open|Paused|Closed)$"),
    include_archived: bool = False,
    sort: str = Query(default="updated", pattern="^(updated|created|title|status)$"),
    db: Session = Depends(get_db)):
    from .cases import list_cases as read
    return read(db, q, status, include_archived, sort)


@router.patch("/cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdate, db: Session = Depends(get_db)):
    from .cases import update_case
    return update_case(db, case_id, payload)


@router.post("/cases/{case_id}/entities")
def add_case_entity(
    case_id: str, payload: CaseEntityCreate, db: Session = Depends(get_db)
):
    from .cases import add_reference
    return add_reference(db, case_id, payload)


@router.post("/cases/{case_id}/notes")
def add_case_note(
    case_id: str, payload: AnalystNoteCreate, db: Session = Depends(get_db)
):
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    row = AnalystNote(case_id=case_id, body=payload.body, author=payload.author)
    db.add(row)
    from .cases import commit
    commit(db)
    db.refresh(row)
    return row_dict(row)


@router.patch("/cases/{case_id}/notes/{note_id}")
def edit_case_note(case_id: str, note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)):
    from .cases import update_note
    return update_note(db, case_id, note_id, payload)


@router.post("/cases/{case_id}/risk-pins")
def add_risk_pin(case_id: str, payload: CaseRiskPin, db: Session = Depends(get_db)):
    from .cases import pin_risk
    return pin_risk(db, case_id, payload.chain, payload.address)


@router.post("/cases/{case_id}/discovery-pins")
def add_discovery_pin(case_id: str, payload: CaseDiscoveryPin, db: Session = Depends(get_db)):
    from .cases import pin_discovery
    from .discovery.domain import DiscoveryError
    try:
        return pin_discovery(db, case_id, payload.run_id)
    except DiscoveryError:
        raise HTTPException(422, "Discovery run is unavailable for pinning.") from None


@router.post("/cases/{case_id}/attachments")
async def add_case_attachment(
    case_id: str, file: UploadFile = File(...), note: str = Form(default="", max_length=10000),
    db: Session = Depends(get_db)
):
    from .cases import store_attachment, MAX_ATTACHMENT_BYTES, get_case
    get_case(db, case_id)
    # Multipart parsing can strip Windows paths before populating file.filename.
    # Retain the raw-header check so a path is rejected rather than accepted as
    # an apparently harmless basename.
    disposition = file.headers.get("content-disposition", "")
    if re.search(r'filename\*?=[^;]*(?:[/\\\\]|[A-Za-z]:)', disposition):
        raise HTTPException(422, "Attachment filename must not contain a path.")
    content = await file.read(MAX_ATTACHMENT_BYTES + 1)
    return store_attachment(db, case_id, file.filename, file.content_type, content, note)


@router.get("/cases/{case_id}/attachments/{attachment_id}")
def download_case_attachment(case_id: str, attachment_id: str, db: Session = Depends(get_db)):
    from .cases import attachment
    row, target = attachment(db, case_id, attachment_id)
    return FileResponse(target, media_type="application/octet-stream",
        filename=row.metadata_json.get("original_filename") or row.metadata_json.get("filename") or "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/cases/{case_id}/reports")
def case_report_history(case_id: str, db: Session = Depends(get_db)):
    from .cases import detail
    return {"reports": detail(db, case_id)["reports"]}


@router.get("/cases/{case_id}/reports/{report_id}")
def stored_case_report(case_id: str, report_id: str, db: Session = Depends(get_db)):
    from .cases import get_case, MEDIA, EXTENSIONS
    from .models import CaseReport
    get_case(db, case_id)
    row = db.get(CaseReport, report_id)
    if not row or row.case_id != case_id:
        raise HTTPException(404, "Report not found")
    from hashlib import sha256
    if sha256(row.content).hexdigest() != row.sha256:
        raise HTTPException(422, "Report integrity check failed.")
    return Response(row.content, media_type=MEDIA[row.format], headers={
        "X-Report-ID": row.id, "X-Content-SHA256": row.sha256,
        "X-Case-State-Fingerprint": row.state_fingerprint,
        "Content-Disposition": f'attachment; filename="case-{row.id}.{EXTENSIONS[row.format]}"',
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.post("/labels/manual")
def manual_label(payload: ManualLabelCreate, db: Session = Depends(get_db)):
    row = Label(**(payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()))
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This label already exists for this chain, address, label name, and source. CSV import can update its type and confidence.") from exc
    db.refresh(row)
    return row_dict(row)


@router.get("/labels")
def list_labels(db: Session = Depends(get_db)):
    from sqlalchemy import select

    rows = db.scalars(select(Label).order_by(Label.last_updated.desc())).all()
    return {"labels": [row_dict(row) for row in rows]}


@router.patch("/labels/{label_id}/state")
def set_label_state(label_id: str, payload: LabelStateUpdate, db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    row = db.get(Label, label_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    row.active = payload.active
    row.archived_at = None if payload.active else datetime.now(timezone.utc)
    row.last_updated = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row_dict(row)


@router.get("/labels/export")
def export_labels(db: Session = Depends(get_db)):
    from sqlalchemy import select

    output = StringIO()
    fieldnames = [
        "chain",
        "address",
        "label",
        "type",
        "source",
        "confidence",
        "active",
        "archived_at",
        "last_updated",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in db.scalars(select(Label)).all():
        data = row_dict(row)
        writer.writerow({key: data.get(key) for key in fieldnames})
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=greedy_collector_labels.csv"},
    )


@router.post("/labels/import")
async def import_labels(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="A CSV file is required")
    try:
        content = (await file.read()).decode("utf-8-sig")
        return service.import_labels(db, content)
    except (UnicodeDecodeError, ValueError, csv.Error) as exc:
        raise HTTPException(status_code=422, detail="Invalid label CSV. Check required columns and each row: chain, address, label, type, source, confidence (0 to 1).") from exc


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return service.dashboard(db)


@router.get("/kyc/sources")
def kyc_sources():
    from .kyc.presentation import source_capabilities
    return source_capabilities()


@router.post("/kyc/screen")
async def kyc_screen(payload: KycQuery, db: Session = Depends(get_db)):
    result = await service.kyc_screen(db, payload)
    result["unavailable_sources"] = [
        {"id": row["id"], "reason": "Optional API_KEY is not configured"
         if "API_KEY is not configured" in row.get("reason", "")
         else "Source unavailable. Check server configuration or try again later."}
        for row in result["unavailable_sources"]
    ]
    return result


@router.patch("/kyc/matches/{match_id}")
def kyc_review(
    match_id: str, payload: KycReviewUpdate, db: Session = Depends(get_db)
):
    row = db.get(KycMatch, match_id)
    if not row:
        raise HTTPException(status_code=404, detail="KYC match not found")
    row.review_status = payload.review_status
    db.commit()
    from .kyc.presentation import sanitize_research
    return sanitize_research(row_dict(row))


@router.get("/reports/{case_id}")
def report(
    case_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|html|json|pdf)$"),
    db: Session = Depends(get_db),
):
    from .attribution.domain import AttributionError
    try:
        from .cases import generate_report, MEDIA, EXTENSIONS
        row = generate_report(db, case_id, format)
        return Response(content=row.content, media_type=MEDIA[format], headers={
            "X-Report-ID": row.id, "X-Content-SHA256": row.sha256,
            "X-Case-State-Fingerprint": row.state_fingerprint,
            "Content-Disposition": f'attachment; filename="case-{row.id}.{EXTENSIONS[format]}"',
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except AttributionError:
        raise HTTPException(status_code=422, detail="Attribution report material is unavailable or exceeds supported limits. Inspect the case references.") from None


# Explicit manual attribution routes; no startup service construction.
from .attribution.router import router as attribution_router

router.include_router(attribution_router)

from .discovery.router import router as discovery_router
router.include_router(discovery_router)

from .clustering.router import router as clustering_router
router.include_router(clustering_router)

from .fund_flow.router import router as fund_flow_router
router.include_router(fund_flow_router)

from .sanctions.router import router as sanctions_router
router.include_router(sanctions_router)

from .narcotics.router import router as narcotics_router
router.include_router(narcotics_router)
