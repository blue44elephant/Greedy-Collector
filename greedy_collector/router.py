import csv
from io import StringIO
import os
from pathlib import Path
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
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
    CaseEntityCreate,
    KycQuery,
    KycReviewUpdate,
    LookupRequest,
    ResolveRequest,
    ManualLabelCreate,
    TransactionLookupRequest,
    WatchlistCreate,
    WatchlistUpdate,
)
from .services import GreedyCollectorService, row_dict
from .resolver import resolve_identifier


router = APIRouter(prefix="/api/greedy-collector", tags=["Greedy Collector"])
service = GreedyCollectorService()


def _provider_error(exc: ChainDataError) -> str:
    if "ETHERSCAN_API_KEY" in str(exc) or "ALCHEMY_API_KEY" in str(exc):
        return "Ethereum provider configuration is unavailable."
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
        raise HTTPException(status_code=502, detail=_provider_error(exc)) from exc


@router.post("/lookup/tx")
async def lookup_tx(payload: TransactionLookupRequest):
    try:
        return await service.lookup_transaction(payload.chain, payload.tx_hash)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChainDataError as exc:
        raise HTTPException(status_code=502, detail=_provider_error(exc)) from exc


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


@router.post("/watchlist")
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    if payload.case_id and not db.get(Case, payload.case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        return service.add_watchlist(db, payload)
    except ValueError as exc:
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
def list_cases(db: Session = Depends(get_db)):
    from sqlalchemy import select

    rows = db.scalars(select(Case).order_by(Case.updated_at.desc())).all()
    return {"cases": [row_dict(row) for row in rows]}


@router.post("/cases/{case_id}/entities")
def add_case_entity(
    case_id: str, payload: CaseEntityCreate, db: Session = Depends(get_db)
):
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    row = CaseEntity(
        case_id=case_id,
        entity_type=payload.entity_type,
        entity_ref=payload.entity_ref,
        metadata_json=payload.metadata,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row_dict(row)


@router.post("/cases/{case_id}/notes")
def add_case_note(
    case_id: str, payload: AnalystNoteCreate, db: Session = Depends(get_db)
):
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    row = AnalystNote(case_id=case_id, body=payload.body, author=payload.author)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row_dict(row)


@router.post("/cases/{case_id}/attachments")
async def add_case_attachment(
    case_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    if not db.get(Case, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "attachment")
    root = Path("./data").resolve()
    case_dir = (root / "greedy_collector_cases" / case_id).resolve()
    if root not in case_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid case path")
    case_dir.mkdir(parents=True, exist_ok=True)
    target = case_dir / safe_name
    target.write_bytes(await file.read())
    row = CaseEntity(
        case_id=case_id,
        entity_type="attachment",
        entity_ref=str(target.relative_to(root)),
        metadata_json={"content_type": file.content_type, "filename": safe_name},
    )
    db.add(row)
    db.commit()
    return row_dict(row)


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
        content, media_type = service.case_report(db, case_id, format)
        return Response(content=content, media_type=media_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except AttributionError:
        raise HTTPException(status_code=422, detail="Attribution report material is unavailable or exceeds supported limits. Inspect the case references.") from None


# Explicit manual attribution routes; no startup service construction.
from .attribution.router import router as attribution_router

router.include_router(attribution_router)

from .discovery.router import router as discovery_router
router.include_router(discovery_router)
