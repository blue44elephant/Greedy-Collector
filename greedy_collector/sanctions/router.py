"""Explicit local authoritative sanctions API; sync is the only network operation."""
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import String, and_, exists, func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import SanctionsEntity as Entity,SanctionsIdentifier as Identifier,SanctionsCasePin as CasePin,SanctionsSnapshot as Snapshot
from .ofac import SanctionsError,SOURCE_ID
from .service import SanctionsRegistry,current_snapshot,registry_status,screen,pin_to_case,_row

router=APIRouter(prefix='/sanctions',tags=['Sanctions Screening'])

@router.get('/status')
def status(db:Session=Depends(get_db)):
    return registry_status(db)

@router.post('/sync')
def sync(db:Session=Depends(get_db)):
    try:return SanctionsRegistry(db).sync()
    except SanctionsError as exc:
        raise HTTPException(status_code=409 if exc.category=='sync_already_running' else 502,
                            detail=exc.category) from None

@router.get('/screen/{chain}/{address}')
def wallet_screen(chain:str,address:str,db:Session=Depends(get_db)):
    try:return screen(db,chain,address)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from None

@router.get('/summary')
def summary(db:Session=Depends(get_db)):
    snapshot=current_snapshot(db)
    if not snapshot:return {**registry_status(db),'by_asset':{},'by_chain':{},'unresolved_count':0}
    rows=db.execute(select(Identifier.source_asset,Identifier.chain,func.count())
        .where(Identifier.snapshot_id==snapshot.id).group_by(Identifier.source_asset,Identifier.chain)).all()
    assets,chains={},{}
    for asset,chain,count in rows:
        assets[asset]=assets.get(asset,0)+count
        chains[chain or 'unresolved']=chains.get(chain or 'unresolved',0)+count
    return {**registry_status(db),'by_asset':assets,'by_chain':chains,
            'unresolved_count':chains.get('unresolved',0)}

@router.get('/search')
def search(q:str='',program:str='',asset:str='',chain:str='',state:str='current',
           limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db)):
    snapshot=current_snapshot(db)
    if not snapshot:return {'items':[],'total':0,'registry_status':'REGISTRY_NOT_SYNCED'}
    if state not in ('current','historical'):raise HTTPException(422,'Invalid status filter')
    query=select(Identifier,Entity,Snapshot).join(Entity,Identifier.entity_id==Entity.id).join(Snapshot,Identifier.snapshot_id==Snapshot.id)
    query=query.where(Snapshot.source_id==SOURCE_ID)
    query=query.where(Identifier.snapshot_id==snapshot.id if state=='current' else Identifier.snapshot_id!=snapshot.id)
    if q:
        key=q.strip()
        if len(key)>512:raise HTTPException(422,'Search value too long')
        query=query.where((Identifier.text_key==key)|(Entity.source_entity_id==key)|
                          Entity.name.ilike('%'+key.replace('%','\\%').replace('_','\\_')+'%',escape='\\')|
                          Entity.aliases.cast(String).ilike('%'+key.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    if program:
        values=func.json_each(Entity.programs).table_valued('value').alias('program_values')
        query=query.where(exists(select(1).select_from(values).where(values.c.value==program)))
    if asset:query=query.where(Identifier.source_asset==asset)
    if chain:query=query.where(Identifier.chain==chain)
    if state=='historical':
        # Only identifiers absent from the current complete snapshot are historical.
        current=Identifier.__table__.alias('current_identifier')
        query=query.where(~exists(select(1).select_from(current).where(and_(current.c.snapshot_id==snapshot.id,
            current.c.source_field==Identifier.source_field,current.c.raw_value==Identifier.raw_value))))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.execute(query.order_by(Snapshot.retrieved_at.desc(),Entity.name,Identifier.id).offset(offset).limit(limit)).all()
    return {'items':[{'identifier':_row(i),'entity':_row(e),'snapshot':_row(s)} for i,e,s in rows],
            'total':total,'registry_status':'REGISTRY_STALE' if registry_status(db)['stale'] else 'CURRENT'}

@router.get('/entities/{source_entity_id}')
def entity_detail(source_entity_id:str,snapshot_id:str|None=None,db:Session=Depends(get_db)):
    snapshot=db.get(Snapshot,snapshot_id) if snapshot_id else current_snapshot(db)
    if snapshot and snapshot.source_id!=SOURCE_ID:raise HTTPException(404,'Snapshot not found')
    if not snapshot:raise HTTPException(404,'Registry not synchronized')
    entities=db.scalars(select(Entity).where(Entity.snapshot_id==snapshot.id,
        Entity.source_entity_id==source_entity_id)).all()
    if not entities:raise HTTPException(404,'Entity not found in current snapshot')
    entity=entities[0]
    identifiers=db.scalars(select(Identifier).where(Identifier.entity_id==entity.id).order_by(Identifier.id)).all()
    return {'entity':_row(entity),'identifiers':[_row(i) for i in identifiers],
            'snapshot':_row(snapshot)}

@router.post('/cases/{case_id}/pins/{chain}/{address}')
def create_pin(case_id:str,chain:str,address:str,db:Session=Depends(get_db)):
    try:return pin_to_case(db,case_id,chain,address)
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from None

@router.get('/cases/{case_id}/pins')
def case_pins(case_id:str,db:Session=Depends(get_db)):
    return {'items':[_row(row) for row in db.scalars(select(CasePin).where(CasePin.case_id==case_id)
        .order_by(CasePin.captured_at.desc())).all()]}
