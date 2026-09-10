import csv
from io import StringIO
import os
from pathlib import Path
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from .chains.base import ChainDataError
from .database import get_db
from .kyc import SOURCE_CATALOG
from .models import AnalystNote, Case, CaseEntity, KycMatch, Label
from .schemas import (
    AlertUpdate,
    AnalystNoteCreate,
    CaseCreate,
    CaseEntityCreate,
    KycQuery,
    KycReviewUpdate,
    LookupRequest,
    ManualLabelCreate,
    TransactionLookupRequest,
    WatchlistCreate,
)
from .services import GreedyCollectorService, row_dict


router = APIRouter(prefix="/api/greedy-collector", tags=["Greedy Collector"])
service = GreedyCollectorService()


@router.get("/status")
def status():
    from .monitoring import monitoring_status

    return {
        "enabled": True,
        "supported_chains": ["ethereum", "bitcoin"],
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


@router.post("/lookup/address")
async def lookup_address(payload: LookupRequest, db: Session = Depends(get_db)):
    try:
        return await service.lookup_address(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChainDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/lookup/tx")
async def lookup_tx(payload: TransactionLookupRequest):
    try:
        return await service.lookup_transaction(payload.chain, payload.tx_hash)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChainDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/address/{chain}/{address}")
def address(chain: str, address: str, db: Session = Depends(get_db)):
    result = service.address_record(db, chain, address)
    if not result:
        raise HTTPException(status_code=404, detail="Address has not been looked up")
    return result


@router.get("/address/{chain}/{address}/transactions")
def transactions(chain: str, address: str, db: Session = Depends(get_db)):
    return {"transactions": service.address_transactions(db, chain, address)}


@router.get("/address/{chain}/{address}/graph")
def graph(
    chain: str,
    address: str,
    hops: int = Query(default=1, ge=1, le=3),
    db: Session = Depends(get_db),
):
    return service.address_graph(db, chain, address, hops)


@router.get("/address/{chain}/{address}/risk")
def risk(chain: str, address: str, db: Session = Depends(get_db)):
    result = service.address_risk(db, chain, address)
    if not result:
        raise HTTPException(status_code=404, detail="No risk result is available")
    return result


@router.post("/watchlist")
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    return service.add_watchlist(db, payload)


@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db)):
    return {"wallets": service.watchlist(db)}


@router.delete("/watchlist/{wallet_id}")
def delete_watchlist(wallet_id: str, db: Session = Depends(get_db)):
    from .models import WatchlistWallet

    row = db.get(WatchlistWallet, wallet_id)
    if not row:
        raise HTTPException(status_code=404, detail="Watchlist wallet not found")
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
    db.commit()
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
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return service.dashboard(db)


@router.get("/kyc/sources")
def kyc_sources():
    return {
        "sources": [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "mode": item.mode,
                "credential_env": item.credential_env,
                "note": item.note,
            }
            for item in SOURCE_CATALOG
        ]
    }


@router.post("/kyc/screen")
async def kyc_screen(payload: KycQuery, db: Session = Depends(get_db)):
    return await service.kyc_screen(db, payload)


@router.patch("/kyc/matches/{match_id}")
def kyc_review(
    match_id: str, payload: KycReviewUpdate, db: Session = Depends(get_db)
):
    row = db.get(KycMatch, match_id)
    if not row:
        raise HTTPException(status_code=404, detail="KYC match not found")
    row.review_status = payload.review_status
    db.commit()
    return row_dict(row)


@router.get("/reports/{case_id}")
def report(
    case_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|html|json|pdf)$"),
    db: Session = Depends(get_db),
):
    try:
        content, media_type = service.case_report(db, case_id, format)
        return Response(content=content, media_type=media_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
