from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from ..database import get_db
from ..chains import list_chains, Capability
from .domain import FlowError, DISCLAIMER
from .schemas import FlowQuery, FlowPin
from .service import FlowService
router=APIRouter(prefix='/fund-flow',tags=['Fund flow'])

def invoke(db,method,*args):
    try:return getattr(FlowService(db),method)(*args)
    except FlowError as exc:raise HTTPException(exc.status,str(exc)) from None
    except OperationalError:
        db.rollback();raise HTTPException(503,'Fund-flow storage unavailable or busy.') from None

@router.get('/capabilities')
def capabilities():
    return {'chains':[{'id':d.chain_id,'name':d.display_name,'family':d.family.value} for d in list_chains() if Capability.GRAPH in d.capabilities and Capability.TRANSACTION_HISTORY in d.capabilities], 'max_hops':6,'disclaimer':DISCLAIMER}

@router.post('/path')
def path(payload:FlowQuery,db:Session=Depends(get_db)):return invoke(db,'analyze',payload,'path')

@router.post('/neighborhood')
def neighborhood(payload:FlowQuery,db:Session=Depends(get_db)):return invoke(db,'analyze',payload,'neighborhood')

@router.get('/runs/{run_id}')
def run(run_id:str,db:Session=Depends(get_db)):return invoke(db,'run',run_id)

@router.post('/cases/{case_id}/pin')
def pin(case_id:str,payload:FlowPin,db:Session=Depends(get_db)):return invoke(db,'pin',case_id,payload.run_id)
