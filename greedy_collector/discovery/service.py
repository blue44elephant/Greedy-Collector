"""Transactional local Discovery foundations. No provider, worker, scheduler or HTTP."""
from datetime import datetime,timedelta,timezone
from functools import wraps
from sqlalchemy import select,func,inspect,text,update
from sqlalchemy.exc import IntegrityError,OperationalError
from pydantic import ValidationError
from ..models import (DiscoverySubject as Subject,DiscoveryRun as Run,DiscoveryRunSource as RunSource,
    DiscoveryResult as Result,DiscoveryObservation as Observation,DiscoveryRunItem as RunItem,
    DiscoveryReview as Review,DISCOVERY_TRIGGER_SQL,Label,KycMatch,utcnow)
from ..migration_state import supports_revision
from ..attribution.domain import json_safe,fingerprint,AttributionError
from .domain import (DiscoveryError,Conflict,NotFound,SchemaUnavailable,canonical_subject,subject_identity,
    clean,query_fingerprint,result_identity,observation_fingerprint,ObservationInput,choice)
from .registry import REGISTRY
from . import enums as e

REVISION='20260913_01'
ENS_REVISION='20260916_01'
MODELS=(Subject,Run,RunSource,Result,Observation,RunItem,Review)
TABLES=tuple(m.__table__.name for m in MODELS)

def row_data(row):return json_safe({c.name:getattr(row,c.name) for c in row.__table__.columns})
def aware(value):return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def positive(value):
    if type(value) is not int or value<1:raise DiscoveryError('A positive version is required')

def atomic(method):
    @wraps(method)
    def command(self,*args,**kwargs):
        # Nested domain commands join the caller's transaction; only the outer
        # boundary commits. ED-2 composes creation without orphan subjects/runs.
        if getattr(self,'_atomic_active',False):return method(self,*args,**kwargs)
        if self.db.new or self.db.dirty or self.db.deleted:raise DiscoveryError('Use a dedicated clean Discovery session')
        try:
            self._atomic_active=True
            connection=self.db.connection()
            if not connection.connection.driver_connection.in_transaction:connection.exec_driver_sql('BEGIN IMMEDIATE')
            result=method(self,*args,**kwargs);self.db.flush();self.db.commit();return result
        except IntegrityError:
            self.db.rollback();raise Conflict('Discovery reference or uniqueness conflict') from None
        except OperationalError:
            self.db.rollback();raise Conflict('Discovery storage is busy or unavailable') from None
        except (ValidationError,AttributionError):
            self.db.rollback();raise DiscoveryError('Invalid Discovery material') from None
        except Exception:self.db.rollback();raise
        finally:self._atomic_active=False
    return command

class DiscoveryService:
    def __init__(self,session,*,metadata_only=False,registry=None):
        self.db=session;self.registry=registry or REGISTRY;self._metadata_only=metadata_only
        connection=session.connection();view=inspect(connection)
        if connection.dialect.name!='sqlite' or not set(TABLES)<=set(view.get_table_names()):raise SchemaUnavailable('Discovery storage is not initialized')
        if connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one()!=1:raise SchemaUnavailable('Discovery requires foreign keys')
        for model in MODELS:
            if {c['name'] for c in view.get_columns(model.__table__.name)}!=set(model.__table__.columns.keys()):raise SchemaUnavailable('Discovery schema is incompatible')
        installed=dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all())
        normalized=lambda sql:' '.join(sql.strip().rstrip(';').split()).lower()
        if any(normalized(installed.get(name,''))!=normalized(sql) for name,sql in DISCOVERY_TRIGGER_SQL.items()):raise SchemaUnavailable('Discovery immutability protection is unavailable')
        if not metadata_only and not supports_revision(connection,REVISION):raise SchemaUnavailable('Discovery migration is required')

    def _get(self,model,identifier):
        row=self.db.get(model,identifier,populate_existing=True)
        if row is None:raise NotFound('Discovery record not found')
        return row

    def _version(self,row,expected):
        positive(expected)
        if row.version!=expected:raise Conflict('Discovery record changed; reload before writing')

    def _bump(self,row,expected,**changes):
        self._version(row,expected)
        result=self.db.execute(update(type(row)).where(type(row).id==row.id,type(row).version==expected).values(**changes,version=expected+1).execution_options(synchronize_session=False))
        if result.rowcount!=1:raise Conflict('Discovery record changed')
        self.db.expire(row)

    def _page(self,model,query,limit=20,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:raise DiscoveryError('Invalid pagination')
        total=self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        rows=self.db.scalars(query.limit(limit).offset(offset)).all()
        return {'items':[row_data(r) for r in rows],'total':total,'limit':limit,'offset':offset,'next_offset':offset+limit if offset+limit<total else None}

    def _subject(self,kind,namespace,value):
        values=canonical_subject(kind,namespace,value)
        if kind=='ens_name':
            connection=self.db.connection()
            checks={c['name']:' '.join(c['sqltext'].split()).lower() for c in inspect(connection).get_check_constraints('discovery_subjects')}
            required={c.name:' '.join(str(c.sqltext).split()).lower() for c in Subject.__table__.constraints if c.name in ('ck_discovery_subjects_1','ck_discovery_subjects_8')}
            if any(checks.get(name)!=sql for name,sql in required.items()) or (not self._metadata_only and not supports_revision(connection,ENS_REVISION)):
                raise SchemaUnavailable('Typed ENS endpoint storage requires the ED-8A0 migration')
        row=self.db.scalar(select(Subject).where(Subject.identity_sha256==values['identity_sha256']))
        if row:
            if subject_identity(row_data(row))!=subject_identity(values):raise Conflict('Subject identity collision')
        else:row=Subject(**values);self.db.add(row);self.db.flush()
        return row

    @atomic
    def get_or_create_subject(self,kind,namespace,value):return row_data(self._subject(kind,namespace,value))
    def get_subject(self,identifier):return row_data(self._get(Subject,identifier))
    def capabilities(self):return self.registry.capabilities()

    @atomic
    def create_run(self,subject_id,selections,*,idempotency_key,refresh=False,config_generation='1',execution_policy=None):
        subject=self._get(Subject,subject_id)
        if subject.kind!='blockchain_address':raise DiscoveryError('Only wallet subjects can define V1 runs')
        if not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=128 or clean(idempotency_key)!=idempotency_key:raise DiscoveryError('Invalid idempotency key')
        if type(refresh) is not bool or not isinstance(config_generation,str) or not config_generation.isalnum() or len(config_generation)>64:raise DiscoveryError('Invalid run options')
        if not isinstance(selections,list) or not 1<=len(selections)<=(6 if execution_policy and execution_policy.get('broad') else 3):raise DiscoveryError('Select one to three transform/source pairs')
        plans=[];seen=set()
        for selected in selections:
            if not isinstance(selected,dict) or set(selected)-{'transform_id','source_id','parameters'}:raise DiscoveryError('Invalid transform selection')
            transform,source=self.registry.pair(selected.get('transform_id'),selected.get('source_id'))
            if subject.namespace not in transform.chains:raise DiscoveryError('Transform does not support this chain')
            from ..chains import get_chain,Capability
            get_chain(subject.namespace).require(Capability.DISCOVERY,transform.required_capability)
            pair=(transform.id,source.id)
            if pair in seen:raise DiscoveryError('Duplicate selected pair')
            seen.add(pair)
            parameters=selected.get('parameters',{})
            if not isinstance(parameters,dict) or set(parameters)-{'max_results'}:raise DiscoveryError('Unsupported transform parameters')
            maximum=parameters.get('max_results',transform.max_results)
            if type(maximum) is not int or not 1<=maximum<=transform.max_results:raise DiscoveryError('Invalid result cap')
            parameters={'max_results':maximum}
            plans.append((transform,source,parameters,query_fingerprint(row_data(subject),transform,source,parameters,config_generation=config_generation)))
        snapshot={'schema_version':1,'subject':subject_identity(row_data(subject)),'selections':[{'transform_id':t.id,'transform_version':t.version,'source_id':s.id,'source_version':s.version,'parameters':p,'query_fingerprint':q} for t,s,p,q in plans],'refresh':refresh,'config_generation':config_generation,'paid_budget_units':0}
        if execution_policy is not None:
            snapshot.pop('paid_budget_units')
            snapshot['execution_policy']=clean(execution_policy)
        digest=fingerprint(snapshot)
        existing=self.db.scalar(select(Run).where(Run.idempotency_key==idempotency_key))
        if existing:
            if existing.request_sha256!=digest:raise Conflict('Idempotency key already identifies another run')
            return self.get_run(existing.id)
        now=utcnow()
        # Do not carry reservations across the UTC quota-window boundary.
        deadline=min(now+timedelta(seconds=60),now.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))
        run=Run(subject_id=subject.id,idempotency_key=idempotency_key,request_sha256=digest,request_snapshot=snapshot,deadline_at=deadline,created_at=now)
        self.db.add(run);self.db.flush()
        for ordinal,(transform,source,parameters,q) in enumerate(plans,1):
            self.db.add(RunSource(run_id=run.id,ordinal=ordinal,transform_id=transform.id,transform_version=transform.version,source_id=source.id,source_version=source.version,config_generation=config_generation,
                descriptor_snapshot={'schema_version':1,'transform':transform.model_dump(mode='json'),'source':source.model_dump(mode='json')},parameters=parameters,query_fingerprint=q,
                retention_policy_id=source.retention_policy_id,cost_unit=source.cost_unit,quota_bucket=source.id+':'+config_generation,quota_window_start=now.replace(hour=0,minute=0,second=0,microsecond=0)))
        self.db.flush();return self.get_run(run.id)

    def get_run(self,identifier):
        row=self._get(Run,identifier)
        return {**row_data(row),'sources':[row_data(s) for s in self.db.scalars(select(RunSource).where(RunSource.run_id==identifier).order_by(RunSource.ordinal))]}

    def list_runs(self,*,subject_id=None,status=None,include_archived=False,limit=20,offset=0):
        query=select(Run).order_by(Run.created_at,Run.id)
        if subject_id:query=query.where(Run.subject_id==subject_id)
        if status:choice(status,e.RUN_STATES);query=query.where(Run.status==status)
        if not include_archived:query=query.where(Run.archived_at.is_(None))
        return self._page(Run,query,limit,offset)

    @atomic
    def transition_run(self,identifier,status,*,expected_version):
        choice(status,e.RUN_STATES);run=self._get(Run,identifier);self._version(run,expected_version)
        allowed={'queued':{'running','cancelled','interrupted'},'running':e.TERMINAL_RUNS}
        if status not in allowed.get(run.status,set()):raise Conflict('Invalid run lifecycle transition')
        sources=self.db.scalars(select(RunSource).where(RunSource.run_id==run.id)).all();now=utcnow()
        if status=='running' and now>=aware(run.deadline_at):raise Conflict('Run definition expired; create a new run')
        if status in ('completed','partial','failed'):
            if any(s.status not in e.TERMINAL_SOURCES for s in sources):raise Conflict('Source work is not terminal')
            success=sum(s.status in ('succeeded','cache_hit','manual_ready') for s in sources)
            complete=success==len(sources) and all(s.status!='succeeded' or s.coverage=='bounded' for s in sources)
            derived='completed' if complete else 'partial' if success else 'failed'
            if status!=derived:raise Conflict('Run outcome does not match source outcomes')
        if status in ('cancelled','interrupted'):
            for source in sources:
                if source.status not in e.TERMINAL_SOURCES:source.status=status;source.error_code=status;source.completed_at=now
        changes={'status':status}
        if status=='running':changes['started_at']=now
        else:changes['completed_at']=now
        if status=='cancelled':changes['cancel_requested_at']=now
        self._bump(run,expected_version,**changes);self.db.flush();return self.get_run(run.id)

    @atomic
    def archive_run(self,identifier,*,expected_version,restore=False):
        row=self._get(Run,identifier)
        if row.status not in e.TERMINAL_RUNS:raise Conflict('Only terminal runs can be archived')
        self._bump(row,expected_version,archived_at=None if restore else utcnow());return self.get_run(row.id)

    def _active_source(self,identifier,expected_version):
        source=self._get(RunSource,identifier);run=self._get(Run,source.run_id);self._version(run,expected_version)
        if run.status!='running' or source.status in e.TERMINAL_SOURCES:raise Conflict('Run/source does not accept new material')
        return source,run

    @atomic
    def transition_source(self,identifier,status,*,expected_run_version,error_code=None,quota_snapshot=None):
        choice(status,e.SOURCE_STATES);source,run=self._active_source(identifier,expected_run_version)
        allowed={'queued':{'running','manual_ready','unavailable','budget_exhausted','cancelled','interrupted'},'running':{'unavailable','rate_limited','budget_exhausted','timeout','failed','cancelled','interrupted'}}
        if status not in allowed.get(source.status,set()):raise Conflict('Invalid source lifecycle transition')
        if status=='manual_ready' and source.descriptor_snapshot['source']['mode']!='manual':raise DiscoveryError('Source is not manual')
        if error_code:choice(error_code,e.ERRORS)
        source.status=status;source.error_code=error_code
        if quota_snapshot is not None:
            if not isinstance(quota_snapshot,dict):raise DiscoveryError('Quota snapshot must be an object')
            source.quota_snapshot=clean(quota_snapshot)
        if status=='running':source.started_at=utcnow()
        else:source.completed_at=utcnow()
        self._bump(run,expected_run_version);self.db.flush();return row_data(source)

    def _attach(self,source,observation,kind,rank=None):
        existing=self.db.get(RunItem,(source.id,observation.id))
        if existing:return existing
        ordinal=(self.db.scalar(select(func.max(RunItem.ordinal)).where(RunItem.run_source_id==source.id)) or 0)+1
        item=RunItem(run_source_id=source.id,observation_id=observation.id,ordinal=ordinal,rank=rank,inclusion_kind=kind)
        self.db.add(item);self.db.flush();return item

    @atomic
    def record_batch(self,source_id,records,*,expected_run_version,coverage='bounded',provider_total=None):
        """Record trusted normalized adapter material atomically; never invokes an adapter."""
        source,run=self._active_source(source_id,expected_run_version)
        if source.status!='running':raise Conflict('Source must be running before material is recorded')
        descriptor=source.descriptor_snapshot['transform'];source_descriptor=source.descriptor_snapshot['source']
        if source_descriptor['mode']=='manual' and not descriptor.get('capture_only'):raise DiscoveryError('Manual navigation is not a finding')
        if not source_descriptor['storage_allowed']:raise DiscoveryError('Source retention is not approved')
        choice(coverage,e.COVERAGE)
        if not isinstance(records,list) or len(records)>source.parameters['max_results']:raise DiscoveryError('Batch exceeds declared result limit')
        if provider_total is not None and (type(provider_total) is not int or provider_total<0):raise DiscoveryError('Invalid provider count')
        query=self._get(Subject,run.subject_id);written=[]
        for record in records:
            if not isinstance(record,dict) or set(record)!={'kind','predicate','from','to','fact_key','observation'}:raise DiscoveryError('Invalid normalized result record')
            if record['kind'] not in descriptor['result_kinds'] or record['predicate'] not in descriptor['predicates']:raise DiscoveryError('Result exceeds transform contract')
            endpoints=[]
            for endpoint in (record['from'],record['to']):
                if not isinstance(endpoint,dict) or set(endpoint)!={'kind','namespace','value'}:raise DiscoveryError('Invalid result endpoint')
                candidate=self._subject(**endpoint)
                if candidate.kind!='blockchain_address' and candidate.kind not in descriptor['output_types']:raise DiscoveryError('Output subject exceeds transform contract')
                endpoints.append(candidate)
            start,end=endpoints
            if query.id not in (start.id,end.id):raise DiscoveryError('Result must relate to the queried subject')
            fact,digest=result_identity(row_data(query),record['kind'],record['predicate'],row_data(start),row_data(end),record['fact_key'])
            values=ObservationInput.model_validate(clean(record['observation'])).model_dump()
            if values['kind'] not in descriptor['observation_kinds']:raise DiscoveryError('Observation exceeds transform contract')
            for model,key in ((Label,'origin_label_id'),(KycMatch,'origin_match_id')):
                if values[key]:self._get(model,values[key])
            if values['kind']=='code_search_result' and values['source_snapshot'].get('public') is not True:raise DiscoveryError('Only public code observations are eligible')
            now=values['retrieved_at']
            if now>utcnow()+timedelta(seconds=5):raise DiscoveryError('Retrieval time is in the future')
            result=self.db.scalar(select(Result).where(Result.identity_sha256==digest))
            fresh=result is None
            if fresh:
                result=Result(query_subject_id=query.id,kind=record['kind'],predicate=record['predicate'],from_subject_id=start.id,to_subject_id=end.id,fact_key=fact,identity_sha256=digest,first_seen_at=now,last_seen_at=now)
                self.db.add(result);self.db.flush()
            elif (result.query_subject_id,result.kind,result.predicate,result.from_subject_id,result.to_subject_id,result.fact_key)!=(query.id,record['kind'],record['predicate'],start.id,end.id,fact):raise Conflict('Result identity collision')
            content_hash=observation_fingerprint(values,{'source_id':source.source_id,'source_version':source.source_version,'transform_id':source.transform_id,'transform_version':source.transform_version})
            observation=self.db.scalar(select(Observation).where(Observation.execution_id==source.id,Observation.result_id==result.id,Observation.source_record_key==values['source_record_key'],Observation.content_sha256==content_hash))
            if observation is None:
                known=self.db.scalar(select(Observation.id).where(Observation.result_id==result.id,Observation.content_sha256==content_hash).limit(1))
                if not fresh:
                    self._bump(result,result.version,material_revision=result.material_revision+(0 if known else 1),first_seen_at=min(aware(result.first_seen_at),now),last_seen_at=max(aware(result.last_seen_at),now))
                observation=Observation(result_id=result.id,execution_id=source.id,content_sha256=content_hash,**values)
                self.db.add(observation);self.db.flush()
            from .broad import is_web_source
            if is_web_source(source.transform_id,source.source_id):
                from .broad.service import capture_candidates
                capture_candidates(self.db,observation,source,query)
            self._attach(source,observation,'local' if source_descriptor['mode']=='local' or descriptor.get('capture_only') else 'retrieved')
            written.append(observation.id)
        source.status='succeeded';source.completed_at=utcnow();source.coverage=coverage;source.provider_total=provider_total
        source.returned_count=self.db.scalar(select(func.count()).select_from(RunItem).where(RunItem.run_source_id==source.id))
        ttl=descriptor['cache_seconds']
        if source_descriptor['mode']=='automated' and ttl and coverage=='bounded':source.expires_at=source.completed_at+timedelta(seconds=min(ttl,3600) if not written else ttl)
        self._bump(run,expected_run_version);self.db.flush();return {'source':row_data(source),'observation_ids':list(dict.fromkeys(written))}

    def get_result(self,identifier):
        result=self._get(Result,identifier)
        return {**row_data(result),'new_material_since_review':result.material_revision>result.reviewed_material_revision}
    def get_observation(self,identifier):return row_data(self._get(Observation,identifier))
    def list_observations(self,result_id,*,limit=20,offset=0):
        self._get(Result,result_id)
        return self._page(Observation,select(Observation).where(Observation.result_id==result_id).order_by(Observation.retrieved_at,Observation.id),limit,offset)
    def run_items(self,run_id,*,limit=20,offset=0):
        self._get(Run,run_id)
        query=select(RunItem).join(RunSource,RunItem.run_source_id==RunSource.id).where(RunSource.run_id==run_id).order_by(RunSource.ordinal,RunItem.ordinal)
        return self._page(RunItem,query,limit,offset)

    @atomic
    def review(self,result_id,observation_id,status,reason,*,expected_version,expected_source_fingerprint):
        choice(status,e.REVIEWS)
        if not isinstance(reason,str) or not reason.strip() or len(reason)>4000:raise DiscoveryError('A review reason is required')
        result=self._get(Result,result_id);observation=self._get(Observation,observation_id);self._version(result,expected_version)
        if observation.result_id!=result.id or observation.content_sha256!=expected_source_fingerprint:raise Conflict('Review observation does not match the selected material')
        sequence=(self.db.scalar(select(func.max(Review.sequence)).where(Review.result_id==result.id)) or 0)+1
        review=Review(result_id=result.id,observation_id=observation.id,sequence=sequence,material_revision=result.material_revision,status=status,reason=clean(reason.strip()))
        self.db.add(review);self._bump(result,expected_version,review_status=status,reviewed_material_revision=result.material_revision)
        self.db.flush();return {'result':self.get_result(result.id),'review':row_data(review)}

    def list_reviews(self,result_id,*,limit=20,offset=0):
        self._get(Result,result_id)
        return self._page(Review,select(Review).where(Review.result_id==result_id).order_by(Review.sequence),limit,offset)

    def cache_candidate(self,source_id,*,refresh=False,now=None):
        source=self._get(RunSource,source_id);run=self._get(Run,source.run_id)
        if refresh or run.request_snapshot['refresh']:return None
        now=aware(now or utcnow())
        row=self.db.scalar(select(RunSource).where(RunSource.id!=source.id,RunSource.query_fingerprint==source.query_fingerprint,
            RunSource.status=='succeeded',RunSource.cache_from_id.is_(None),RunSource.coverage=='bounded',RunSource.expires_at>now).order_by(RunSource.completed_at.desc(),RunSource.id).limit(1))
        if row is None:return None
        descriptor=row.descriptor_snapshot['source']
        current_source=self.registry.sources.get(source.source_id)
        if not descriptor['storage_allowed'] or not current_source or not current_source.storage_allowed or current_source.retention_policy_id!=row.retention_policy_id:return None
        current_transform=self.registry.transforms.get(source.transform_id)
        if not current_transform or (current_source.version,current_transform.version)!=(source.source_version,source.transform_version):return None
        return row_data(row)

    @atomic
    def reuse_cache(self,source_id,*,expected_run_version):
        source,run=self._active_source(source_id,expected_run_version)
        if source.status!='queued':raise Conflict('Cache reuse must precede source work')
        cached=self.cache_candidate(source_id)
        if not cached:raise Conflict('No eligible fresh cache entry')
        for item in self.db.scalars(select(RunItem).where(RunItem.run_source_id==cached['id']).order_by(RunItem.ordinal)):
            self._attach(source,self._get(Observation,item.observation_id),'cache',item.rank)
        source.status='cache_hit';source.cache_from_id=cached['id'];source.completed_at=utcnow();source.expires_at=cached['expires_at'] and datetime.fromisoformat(cached['expires_at']);source.coverage=cached['coverage'];source.returned_count=cached['returned_count'];source.provider_total=cached['provider_total']
        self._bump(run,expected_run_version);self.db.flush();return row_data(source)
