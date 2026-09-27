from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from ..database import get_db
from .domain import CHAINS, HEURISTIC, DISCLAIMER, ClusteringError
from .service import ClusteringService
from .schemas import Analyze, Exclude, Pin
from .graph import graph_view

router = APIRouter(prefix="/clustering", tags=["Technical clustering"])

def invoke(db, method, *args):
    try: return getattr(ClusteringService(db), method)(*args)
    except ClusteringError as exc: raise HTTPException(exc.status, str(exc)) from None
    except OperationalError:
        db.rollback()
        raise HTTPException(503, "Clustering storage unavailable or busy.") from None

@router.get("/capabilities")
def capabilities():
    return {"automatic_chains": list(CHAINS), "heuristic": HEURISTIC, "disclaimer": DISCLAIMER}

@router.post("/analyze")
def analyze(payload: Analyze, db: Session = Depends(get_db)):
    return invoke(db, "analyze", payload.chain)

@router.get("/clusters/{cluster_id}")
def cluster(cluster_id: str, version: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    return invoke(db, "cluster", cluster_id, version)

@router.get("/clusters/{cluster_id}/graph")
def graph(cluster_id: str, version: int | None = Query(None, ge=1), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db)):
    return graph_view(invoke(db, "cluster", cluster_id, version), offset, limit)

@router.get("/wallet/{chain}/{address}")
def wallet(chain: str, address: str, db: Session = Depends(get_db)):
    return invoke(db, "wallet", chain, address)

@router.post("/evidence/{evidence_id}/exclude")
def exclude(evidence_id: str, payload: Exclude, db: Session = Depends(get_db)):
    return invoke(db, "exclude", evidence_id, payload.reason)

@router.post("/cases/{case_id}/pin")
def pin(case_id: str, payload: Pin, db: Session = Depends(get_db)):
    return invoke(db, "pin", case_id, payload.cluster_id, payload.version)
