"""Atomic local OFAC snapshot state and exact wallet screening."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_,func,or_,select,update
from sqlalchemy.exc import IntegrityError,OperationalError
from sqlalchemy.orm import Session
from ..models import (Case,SanctionsSnapshot as Snapshot,SanctionsRegistryState as State,
                      SanctionsEntity as Entity,SanctionsIdentifier as Identifier,
                      SanctionsSyncEvent as Event,SanctionsCasePin as CasePin)
from ..chains import get_chain_adapter
from .ofac import SOURCE_ID, OfacSdnSource, SanctionsError, text_key

STALE_AFTER=timedelta(hours=72)
LEASE=timedelta(minutes=5)


def _now(): return datetime.now(timezone.utc)
def _aware(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

def _row(row):
    return jsonable_encoder({column.name:getattr(row,column.name) for column in row.__table__.columns})


def current_snapshot(db:Session):
    state=db.get(State,SOURCE_ID)
    return db.get(Snapshot,state.current_snapshot_id) if state and state.current_snapshot_id else None


def registry_status(db:Session):
    snapshot=current_snapshot(db)
    lease=db.get(State,SOURCE_ID)
    latest=db.scalar(select(Event).where(Event.source_id==SOURCE_ID).order_by(Event.attempted_at.desc()).limit(1))
    stale=bool(snapshot and _now()-_aware(snapshot.retrieved_at)>STALE_AFTER)
    return {'source_id':SOURCE_ID,'source':'OFAC SDN','snapshot':_row(snapshot) if snapshot else None,
            'sync_state':'running' if lease and lease.sync_lease_until and _aware(lease.sync_lease_until)>_now() else 'idle',
            'stale':stale,'stale_after_hours':72,'last_sync':_row(latest) if latest else None,
            'message':'OFAC registry not synchronized.' if not snapshot else None}


def _changes(db,old_id,new_id):
    if not old_id:return {'added':db.scalar(select(func.count()).select_from(Identifier).where(Identifier.snapshot_id==new_id)),
                          'removed':0,'association_changed':0,'program_changed':0}
    # Entity primary keys differ by snapshot; compare official entity IDs instead.
    def identities(snapshot):
        result={}
        for identifier,entity in db.execute(select(Identifier,Entity).join(Entity,Identifier.entity_id==Entity.id)
            .where(Identifier.snapshot_id==snapshot)).all():
            key=(identifier.source_field,identifier.raw_value)
            result.setdefault(key,{})[entity.source_entity_id]=tuple(sorted(entity.programs))
        return result
    before,after=identities(old_id),identities(new_id)
    previous=set(before);current=set(after)
    return {'added':len(current-previous),'removed':len(previous-current),
            'association_changed':sum(set(before[k])!=set(after[k]) for k in previous&current),
            'program_changed':sum(any(before[k].get(e)!=after[k].get(e) for e in set(before[k])&set(after[k])) for k in previous&current)}


class SanctionsRegistry:
    def __init__(self,db:Session,source=None): self.db=db;self.source=source or OfacSdnSource()

    def _lease(self):
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        db=self.db
        db.execute(sqlite_insert(State).values(source_id=SOURCE_ID).on_conflict_do_nothing(index_elements=['source_id']))
        db.commit()
        until=_now()+LEASE
        changed=db.execute(update(State).where(State.source_id==SOURCE_ID,
             or_(State.sync_lease_until.is_(None),State.sync_lease_until<_now()))
             .values(sync_lease_until=until)).rowcount
        db.commit()
        if changed!=1:raise SanctionsError('sync_already_running')

    def sync(self,*,official_sha256=None):
        self._lease()
        db=self.db
        try:
            data,source_hash=self.source.fetch()
            parsed=self.source.parse(data)
            expected=official_sha256 or source_hash
            if expected and (len(expected)!=64 or parsed.sha256.lower()!=expected.lower()):
                raise SanctionsError('integrity_failed')
            previous=current_snapshot(db)
            snapshot=Snapshot(id=str(uuid4()),source_id=SOURCE_ID,source_url=self.source.url,
                retrieved_at=_now(),published_at=parsed.published_at,sha256=parsed.sha256,
                official_sha256=expected,integrity_status='verified' if expected else 'unavailable',
                parser_version=self.source.parser_version,entity_count=len(parsed.entities),
                identifier_count=len(parsed.identifiers),status='complete',change_counts={})
            db.add(snapshot)
            db.flush()
            entities={}
            for item in parsed.entities:
                entity=Entity(id=str(uuid4()),snapshot_id=snapshot.id,**item)
                entities[item['source_entity_id']]=entity
                db.add(entity)
            db.flush()
            for item in parsed.identifiers:
                uid=item['source_entity_id']
                db.add(Identifier(id=str(uuid4()),snapshot_id=snapshot.id,entity_id=entities[uid].id,
                                  **{k:v for k,v in item.items() if k!='source_entity_id'}))
            db.flush()
            snapshot.change_counts=_changes(db,previous.id if previous else None,snapshot.id)
            state=db.get(State,SOURCE_ID);state.current_snapshot_id=snapshot.id;state.sync_lease_until=None
            db.add(Event(source_id=SOURCE_ID,status='complete',snapshot_id=snapshot.id))
            db.commit()
            return registry_status(db)
        except Exception as exc:
            db.rollback()
            category=exc.category if isinstance(exc,SanctionsError) else 'validation_failed'
            state=db.get(State,SOURCE_ID)
            if state:state.sync_lease_until=None
            db.add(Event(source_id=SOURCE_ID,status='failed',reason=category))
            db.commit()
            if isinstance(exc,SanctionsError):raise
            raise SanctionsError(category) from exc


def _associations(db,rows,snapshot):
    result=[]
    for identifier,entity in rows:
        result.append({'identifier':_row(identifier),'entity':_row(entity),
                       'snapshot_id':snapshot.id,'snapshot_sha256':snapshot.sha256,
                       'snapshot_retrieved_at':_row(snapshot)['retrieved_at'],
                       'source':'OFAC SDN','source_id':SOURCE_ID})
    return result


def screen(db:Session,chain:str,address:str):
    try:canonical=get_chain_adapter(chain).normalize_address(address)
    except (ValueError,TypeError):raise ValueError('Invalid wallet address') from None
    snapshot=current_snapshot(db)
    base={'chain':chain,'address':canonical,'source_id':SOURCE_ID,
          'match_type':'UNAVAILABLE','listing_state':'REGISTRY_NOT_SYNCED','associations':[],
          'snapshot':_row(snapshot) if snapshot else None,'stale':False,
          'first_seen_snapshot':None,'last_seen_snapshot':None,
          'first_seen_at':None,'last_seen_at':None,'observed_removed_at':None}
    if snapshot is None:return base
    base['stale']=_now()-_aware(snapshot.retrieved_at)>STALE_AFTER
    key=text_key(canonical)
    def matching(snapshot_id):
        return list(db.execute(select(Identifier,Entity).join(Entity,Identifier.entity_id==Entity.id)
            .where(Identifier.snapshot_id==snapshot_id,
                   or_(and_(Identifier.chain==chain,Identifier.canonical_address==canonical),
                       Identifier.text_key==key)).order_by(Entity.source_entity_id,Identifier.id)).all())
    rows=matching(snapshot.id)
    chosen=snapshot
    if not rows:
        # Prefer the latest older complete snapshot with this exact text or chain match.
        historical_id=db.scalar(select(Snapshot.id).join(Identifier,Identifier.snapshot_id==Snapshot.id)
            .where(Snapshot.source_id==SOURCE_ID,Snapshot.id!=snapshot.id,
                   or_(and_(Identifier.chain==chain,Identifier.canonical_address==canonical),
                       Identifier.text_key==key))
            .order_by(Snapshot.retrieved_at.desc(),Snapshot.id.desc()).limit(1))
        if historical_id:
            chosen=db.get(Snapshot,historical_id)
            rows=matching(historical_id)
    if not rows:
        base.update(match_type='NO_MATCH',listing_state='REGISTRY_STALE' if base['stale'] else 'NOT_FOUND_IN_AVAILABLE_SNAPSHOTS')
        return base
    direct=[row for row in rows if row[0].chain==chain and row[0].canonical_address==canonical]
    unresolved=[row for row in rows if row[0].chain is None]
    if direct:match_type='DIRECT_CHAIN_MATCH'
    elif unresolved:match_type='EXACT_TEXT_MATCH_CHAIN_UNRESOLVED'
    else:match_type='TEXT_MATCH_OTHER_CHAIN'
    base.update(match_type=match_type,
                listing_state='CURRENTLY_LISTED' if chosen.id==snapshot.id else 'HISTORICALLY_LISTED',
                associations=_associations(db,rows,chosen))
    seen=db.execute(select(Snapshot.id,Snapshot.retrieved_at).join(Identifier,Identifier.snapshot_id==Snapshot.id)
        .where(Snapshot.source_id==SOURCE_ID,or_(Identifier.text_key==key,
            and_(Identifier.chain==chain,Identifier.canonical_address==canonical)))
        .order_by(Snapshot.retrieved_at,Snapshot.id)).all()
    if seen:
        base['first_seen_snapshot']=seen[0][0]
        base['last_seen_snapshot']=seen[-1][0]
        base['first_seen_at']=_aware(seen[0][1]).isoformat()
        base['last_seen_at']=_aware(seen[-1][1]).isoformat()
    if chosen.id!=snapshot.id:
        first_absent=db.scalar(select(Snapshot.retrieved_at).where(Snapshot.source_id==SOURCE_ID,
            Snapshot.retrieved_at>seen[-1][1]).order_by(Snapshot.retrieved_at).limit(1))
        base['observed_removed_at']=_aware(first_absent or snapshot.retrieved_at).isoformat()
    return base


def pin_to_case(db:Session,case_id:str,chain:str,address:str):
    if not db.get(Case,case_id):raise ValueError('Case not found')
    result=screen(db,chain,address)
    if result['match_type'] in ('NO_MATCH','UNAVAILABLE'):raise ValueError('No sanctions record to pin')
    record={'schema_version':1,'captured_at':_now().isoformat(),'screening':result}
    pin=CasePin(case_id=case_id,record=record)
    db.add(pin);db.commit();db.refresh(pin)
    return _row(pin)
