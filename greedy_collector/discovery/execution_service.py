"""ED-2 transactional ledger and paginated projections, composed with ED-1."""
from datetime import timedelta
from sqlalchemy import select,func,case,text
from .service import DiscoveryService,atomic,row_data,aware,Run,RunSource,Subject,Observation,Result,RunItem,utcnow
from .domain import Conflict,DiscoveryError,clean
from .executors import ExecutionSignal
from . import enums as e

class ExecutionService(DiscoveryService):
    def existing_intent(self,key,intent):
        row=self.db.scalar(select(Run).where(Run.idempotency_key==key))
        if row:
            if row.request_snapshot.get('execution_policy',{}).get('intent')!=intent:raise Conflict('Idempotency key already identifies another intent')
            return self.get_run(row.id)

    @atomic
    def define(self,subject,selections,key,refresh,policy,config_generation):
        existing=self.existing_intent(key,policy['intent'])
        if existing:return existing
        # The selected architecture permits one active run, even for different queries.
        if self.db.scalar(select(Run.id).where(Run.status.in_(('queued','running'))).limit(1)):raise Conflict('Another Discovery run is active')
        canonical=self.get_or_create_subject('blockchain_address',subject['chain'],subject['address'])
        return self.create_run(canonical['id'],selections,idempotency_key=key,refresh=refresh,execution_policy=policy,config_generation=config_generation)

    @atomic
    def reserve_source(self,source_id,policy,paid_allowance):
        source=self._get(RunSource,source_id);run=self._get(Run,source.run_id)
        if run.status!='running' or source.status!='queued':raise Conflict('Source is not eligible for reservation')
        now=utcnow()
        if now>=aware(run.deadline_at):raise ExecutionSignal('timeout')
        descriptor=source.descriptor_snapshot['transform'];mode=descriptor['mode']
        requests=descriptor['max_requests'] if mode=='automated' else 0
        units=requests*policy.units_per_request
        paid=descriptor['cost_class']=='PAID'
        if paid and (paid_allowance<=0 or units>paid_allowance):raise ExecutionSignal('budget_exhausted')
        # Account identity is operator-owned, independent of the selected pairs
        # and requested limits. Changing a search must never reset its quota.
        source.quota_bucket=source.source_id+':'+policy.generation
        retry_at=self.db.scalar(select(func.max(RunSource.retry_after_at)).where(RunSource.quota_bucket==source.quota_bucket))
        if retry_at and aware(retry_at)>now:raise ExecutionSignal('rate_limited',{'retry_after_at':aware(retry_at)})
        day=now.replace(hour=0,minute=0,second=0,microsecond=0);month=day.replace(day=1)
        charged=case((RunSource.status.in_(('queued','running')),RunSource.units_reserved),else_=RunSource.units_consumed)
        if paid:
            used=self.db.scalar(select(func.coalesce(func.sum(charged),0)).where(RunSource.run_id==run.id,RunSource.source_id==source.source_id))
            if used+units>paid_allowance:raise ExecutionSignal('budget_exhausted')
        for since,cap in ((day,policy.daily_units),(month,policy.monthly_units)):
            used=self.db.scalar(select(func.coalesce(func.sum(charged),0)).where(RunSource.quota_bucket==source.quota_bucket,RunSource.quota_window_start>=since))
            if used+units>cap:raise ExecutionSignal('budget_exhausted')
        source.requests_reserved=requests;source.units_reserved=units
        source.quota_window_start=day
        source.quota_snapshot={'policy':policy.model_dump(mode='json'),'eligibility':'eligible','remaining':None}
        # transition_source reloads this row with populate_existing. Preserve the
        # reservation first even when the application Session disables autoflush.
        self.db.flush()
        # The transition joins this reservation transaction.
        return self.transition_source(source.id,'running',expected_run_version=run.version)

    @atomic
    def charge_attempt(self,source_id,request_class):
        source=self._get(RunSource,source_id);run=self._get(Run,source.run_id)
        if run.status!='running' or source.status!='running':raise Conflict('Execution is no longer active')
        now=utcnow()
        if now>=aware(run.deadline_at):raise ExecutionSignal('timeout')
        units=source.quota_snapshot['policy']['units_per_request']
        if source.requests_attempted>=source.requests_reserved or source.units_consumed+units>source.units_reserved:raise ExecutionSignal('budget_exhausted')
        # Count persisted attempts, including failed/uncertain prior runs, in the rolling minute.
        recent=self.db.execute(text("SELECT COUNT(*) FROM discovery_run_sources AS s, json_each(s.attempt_log) AS a WHERE s.quota_bucket=:bucket AND json_extract(a.value,'$.at')>=:since"),
            {'bucket':source.quota_bucket,'since':(now-timedelta(seconds=60)).isoformat()}).scalar_one()
        rate=source.descriptor_snapshot['source']['rate_limit_per_minute']
        if recent>=rate:raise ExecutionSignal('rate_limited',{'retry_after_at':now+timedelta(seconds=60)})
        source.requests_attempted+=1;source.units_consumed+=units
        source.attempt_log=[*source.attempt_log,{'at':now.isoformat(),'outcome':'charged_before_attempt','request_class':request_class,'charged_units':units}]
        self._bump(run,run.version)

    @atomic
    def fail_source(self,source_id,category,*,quota=None,eligibility=None):
        source=self._get(RunSource,source_id);run=self._get(Run,source.run_id)
        if run.status!='running' or source.status in e.TERMINAL_SOURCES:return row_data(source)
        if category not in e.ERRORS:raise DiscoveryError('Unsupported execution error')
        state=category if category in ('rate_limited','timeout','budget_exhausted','cancelled','interrupted') else 'unavailable' if category in ('configuration_unavailable','retention_not_permitted','entitlement_unavailable') else 'failed'
        if source.status=='queued' and state not in ('unavailable','budget_exhausted','cancelled','interrupted'):
            self.transition_source(source.id,'running',expected_run_version=run.version)
        snapshot={**source.quota_snapshot,**(quota.model_dump(mode='json',exclude_none=True) if quota else {})}
        if eligibility:snapshot['eligibility']=eligibility
        if quota and quota.retry_after_at:source.retry_after_at=aware(quota.retry_after_at)
        # transition_source reloads with populate_existing; persist the retry
        # deadline before that reload when application autoflush is disabled.
        self.db.flush()
        return self.transition_source(source.id,state,expected_run_version=run.version,error_code=category,quota_snapshot=snapshot)

    @atomic
    def finalize(self,run_id):
        run=self._get(Run,run_id)
        if run.status in e.TERMINAL_RUNS:return self.get_run(run_id)
        sources=self.db.scalars(select(RunSource).where(RunSource.run_id==run_id)).all()
        success=sum(s.status in ('succeeded','cache_hit','manual_ready') for s in sources)
        complete=success==len(sources) and all(s.status!='succeeded' or s.coverage=='bounded' for s in sources)
        return self.transition_run(run_id,'completed' if complete else 'partial' if success else 'failed',expected_version=run.version)

    @atomic
    def record_execution_batch(self,source_id,batch,expected_run_version):
        source=self._get(RunSource,source_id)
        quota=batch.quota
        if quota and quota.reported_units is not None and quota.reported_units>source.units_reserved:raise DiscoveryError('Reported use exceeds reserved units')
        result=self.record_batch(source_id,batch.model_dump(mode='json',by_alias=True)['records'],expected_run_version=expected_run_version,coverage=batch.coverage,provider_total=batch.provider_total)
        if quota:
            source.quota_snapshot=clean({**source.quota_snapshot,**quota.model_dump(mode='json',exclude_none=True)})
            if quota.reported_units is not None:source.units_consumed=max(source.units_consumed,quota.reported_units)
            if quota.retry_after_at:source.retry_after_at=aware(quota.retry_after_at)
        self.db.flush()
        return result

    @atomic
    def interrupt_orphans(self):
        # Startup only in the supported single-process deployment; never replay.
        ids=self.db.scalars(select(Run.id).where(Run.status.in_(('queued','running')))).all()
        for identifier in ids:
            row=self._get(Run,identifier)
            self.transition_run(identifier,'interrupted',expected_version=row.version)
        return len(ids)

    def read_run(self,identifier):
        row=self.get_run(identifier)
        for source in row['sources']:
            source['manual_actions']=source['quota_snapshot'].get('manual_actions',[]) if source['status']=='manual_ready' else []
        return {**row,'subject':self.get_subject(row['subject_id']),
            'budget':row['request_snapshot'].get('execution_policy',{}).get('budget',{}),
            'returned_count':sum(s['returned_count'] for s in row['sources'])}

    def read_observation(self,identifier):
        row=self.get_observation(identifier);source=self._get(RunSource,row['execution_id'])
        return {**row,'source_id':source.source_id,'transform_id':source.transform_id}

    def observation_page(self,result_id,*,limit=20,offset=0):
        page=self.list_observations(result_id,limit=limit,offset=offset)
        page['items']=[self.read_observation(row['id']) for row in page['items']]
        return page

    def result_page(self,run_id,*,limit=20,offset=0):
        page=self.run_items(run_id,limit=limit,offset=offset)
        items=[]
        for item in page['items']:
            observation=self.read_observation(item['observation_id']);result=self.get_result(observation['result_id'])
            count=self.db.scalar(select(func.count()).select_from(Observation).where(Observation.result_id==result['id']))
            items.append({'result':result,'observation':observation,'source_run_id':item['run_source_id'],
                'inclusion_kind':item['inclusion_kind'],'ordinal':item['ordinal'],'provenance_count':count})
        return {**page,'items':items}
