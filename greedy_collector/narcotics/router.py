from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from ..database import get_db
from ..cases import commit
from .service import NarcoticsService
from .schemas import ProfileInput, FingerprintInput, RelatedInput, ReviewInput, NexusInput, PriorityInput, PinInput
from .domain import WEIGHTS, DISCLAIMER

router = APIRouter(prefix="/narcotics", tags=["Narcotics network intelligence"])
def invoke(db, method, *args, write=False):
    try:
        value = getattr(NarcoticsService(db), method)(*args)
        if write: commit(db)
        return value
    except (OperationalError, IntegrityError):
        db.rollback(); raise HTTPException(409, "Narcotics storage unavailable or changed; reload and try again.") from None

@router.get("/capabilities")
def capabilities():
    from .schemas import COURIERS, PLATFORMS, FIELD_NAMES
    return {"weights": WEIGHTS, "fields": sorted(FIELD_NAMES), "courier_methods": COURIERS,
            "platforms": PLATFORMS, "max_cases": 20, "max_nodes": 300, "max_edges": 1200, "disclaimer": DISCLAIMER}

@router.get("/cases/{case_id}/profile")
def profile(case_id: str, db: Session = Depends(get_db)): return invoke(db, "profile", case_id)
@router.put("/cases/{case_id}/profile")
def save_profile(case_id: str, payload: ProfileInput, db: Session = Depends(get_db)): return invoke(db, "save_profile", case_id, payload)
@router.get("/cases/{case_id}/history")
def history(case_id: str, db: Session = Depends(get_db)): return invoke(db, "history", case_id)
@router.post("/cases/{case_id}/fingerprints")
def fingerprint(case_id: str, payload: FingerprintInput, db: Session = Depends(get_db)): return invoke(db, "fingerprint", case_id, payload.weights, write=True)
@router.post("/cases/{case_id}/related")
def related(case_id: str, payload: RelatedInput, db: Session = Depends(get_db)): return invoke(db, "related", case_id, payload, write=True)
@router.get("/runs/{kind}/{run_id}")
def analysis(kind: str, run_id: str, db: Session = Depends(get_db)): return invoke(db, "run", kind, run_id)
@router.get("/links/{link_id}")
def link(link_id: str, db: Session = Depends(get_db)): return invoke(db, "link", link_id)
@router.post("/links/{link_id}/reviews")
def review(link_id: str, payload: ReviewInput, db: Session = Depends(get_db)): return invoke(db, "review", link_id, payload, write=True)
@router.post("/nexus")
def nexus(payload: NexusInput, db: Session = Depends(get_db)): return invoke(db, "nexus", payload, write=True)
@router.post("/priority")
def priority(payload: PriorityInput, db: Session = Depends(get_db)): return invoke(db, "priority", payload.nexus_id, write=True)
@router.post("/cases/{case_id}/pins")
def pin(case_id: str, payload: PinInput, db: Session = Depends(get_db)): return invoke(db, "pin", case_id, payload, write=True)
