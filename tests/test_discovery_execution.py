"""Synthetic executors are confined to tests; all external transports are blocked."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import json
import pytest
from pydantic import ValidationError
from sqlalchemy import select,func,text
from sqlalchemy.orm import sessionmaker

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base,DiscoveryRun,DiscoveryRunSource,DiscoveryResult,DiscoveryObservation,DiscoveryRunItem,AttributionEntity,RiskResult,Case,Label,KycScreeningRun
from greedy_collector.discovery import schemas as s
from greedy_collector.discovery.registry import REGISTRY,Registry
from greedy_collector.discovery.executors import ExecutorRegistry,Binding,QuotaPolicy,ExecutionSignal,production_executors
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.execution_service import ExecutionService
from greedy_collector.discovery.domain import DiscoveryError,Conflict

ETH='0x'+'ab'*20

def material(text_value='Synthetic context',repository='123'):
    return {'kind':'candidate_relationship','predicate':'repository_contains',
        'from':{'kind':'repository','namespace':'github','value':repository},
        'to':{'kind':'blockchain_address','namespace':'ethereum','value':ETH},'fact_key':{'path':'README.md'},
        'observation':{'kind':'code_search_result','source_record_key':'blob:README.md','source_url':'https://example.invalid/code',
            'title':'Synthetic test reference','summary':text_value,'retrieved_at':datetime.now(timezone.utc),
            'source_snapshot':{'public':True,'blob_sha':'synthetic','schema_version':1}}}

class SyntheticExecutor:
    def __init__(self,mode='success',records=None):
        self.mode=mode;self.records=records;self.calls=0;self.attempts=0;self.entered=None;self.release=None
    async def execute(self,context):
        self.calls+=1
        async def operation():
            self.attempts+=1
            if self.entered:self.entered.set()
            if self.release:await self.release.wait()
            if self.mode in ('rate_limited','timeout','transport_failed','budget_exhausted'):
                raise ExecutionSignal(self.mode,{'remaining':0,'retry_after_at':datetime.now(timezone.utc)+timedelta(seconds=20)})
            if self.mode=='exception':raise RuntimeError('https://private.invalid?token=synthetic-secret traceback')
        if context.parameters.get('max_results') and self.mode!='local':await context.request(operation)
        else:await operation()
        records=[] if self.mode=='empty' else self.records if self.records is not None else [material()]
        if self.mode=='malformed':records=[material(),{'invalid':'synthetic-secret'}]
        if self.mode=='repeat_attempt':await context.request(operation)
        return {'records':records,'coverage':'provider_incomplete' if self.mode=='partial' else 'bounded'}

class Harness:
    def __init__(self,tmp_path,cost='LIMITED_FREE',mode='automated',credential=False,max_requests=1):
        self.engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'execution.db').as_posix(),connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(self.engine)
        source=REGISTRY.sources['github'].model_dump();source.update(credential_env='DISCOVERY_GITHUB_TOKEN' if credential else None,storage_allowed=True,cost_class=cost,mode=mode,rate_limit_per_minute=100)
        sources=[{**source,'id':name} for name in ('test_one','test_two')]
        transform=REGISTRY.transforms['wallet.public_code_mentions'].model_dump();transform.update(source_ids=('test_one','test_two'),cost_class=cost,mode=mode,max_requests=max_requests if mode=='automated' else 0,max_results=100,deadline_seconds=60)
        self.registry=Registry(sources,[transform]);self.executors=ExecutorRegistry(self.registry)
        self.runtime=DiscoveryRuntime(self.sessions,self.executors,metadata_only=True)
    def bind(self,source='test_one',executor=None,**policy):
        executor=executor or SyntheticExecutor()
        self.executors.register(Binding('wallet.public_code_mentions',source,1,1,executor,QuotaPolicy(daily_units=policy.pop('daily_units',1000),monthly_units=policy.pop('monthly_units',30000),**policy)))
        return executor
    def count(self,model):
        with self.sessions() as db:return db.scalar(select(func.count()).select_from(model))

@pytest.fixture
def h(tmp_path,monkeypatch):
    def prohibited(*args,**kwargs):raise AssertionError('No external requests')
    monkeypatch.setattr('httpx.HTTPTransport.handle_request',prohibited)
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request',prohibited)
    value=Harness(tmp_path)
    yield value
    asyncio.run(value.runtime.stop());value.engine.dispose()

def request(runtime,sources=('test_one',),**overrides):
    data={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.public_code_mentions','source_id':name} for name in sources],**overrides}
    plan,_=runtime.plan(s.PlanRequest.model_validate(data))
    return s.RunCreate(**data,expected_plan_fingerprint=plan.fingerprint)

async def job(h,sources=('test_one',),key=None,**options):
    row=await h.runtime.create_and_execute_run(request(h.runtime,sources,**options),key)
    task=h.runtime._tasks.get(row['id'])
    if task:await task
    with h.runtime.service() as svc:return svc.read_run(row['id'])

@pytest.mark.parametrize('mode,status,count',[('success','completed',1),('empty','completed',0),('partial','partial',1),('rate_limited','failed',0),('timeout','failed',0),('transport_failed','failed',0),('exception','failed',0),('malformed','failed',0),('repeat_attempt','failed',0)])
def test_executor_outcomes(h,mode,status,count):
    executor=h.bind(executor=SyntheticExecutor(mode));row=asyncio.run(job(h))
    assert row['status']==status and h.count(DiscoveryObservation)==count
    assert row['returned_count']==count and row['sources'][0]['requests_attempted']==1
    assert row['sources'][0]['units_consumed']==1 and executor.calls==1
    assert 'synthetic-secret' not in json.dumps(row)
    assert row['completed_at'] and row['sources'][0]['completed_at']

@pytest.mark.parametrize('mode',['exception','timeout','malformed','unimplemented'])
def test_independent_source_failure(h,mode):
    h.bind()
    if mode!='unimplemented':h.bind('test_two',SyntheticExecutor(mode))
    row=asyncio.run(job(h,('test_one','test_two')))
    assert row['status']=='partial' and row['sources'][0]['returned_count']==1
    assert row['sources'][1]['returned_count']==0
    assert h.count(DiscoveryResult)==h.count(DiscoveryObservation)==h.count(DiscoveryRunItem)==1

def test_multiple_success_and_provenance(h):
    h.bind();h.bind('test_two');row=asyncio.run(job(h,('test_one','test_two')))
    assert row['status']=='completed' and row['returned_count']==2
    assert h.count(DiscoveryResult)==1 and h.count(DiscoveryObservation)==2

def test_unimplemented_and_production_registry(h):
    production=production_executors(h.sessions)
    assert set(production._bindings)=={('wallet.local_labels','gc_labels'),('wallet.public_code_mentions','github'),('wallet.ens_primary_name','ens_ethereum'),('wallet.graphsense_public_tags','github'),('wallet.broad_web','brave_search')}
    assert set(production._manual)=={('wallet.manual_exact_web','google')}
    row=asyncio.run(job(h));assert row['status']=='failed'
    assert row['sources'][0]['status']=='unavailable'
    assert row['sources'][0]['quota_snapshot']['eligibility']=='not_implemented'
    assert row['sources'][0]['requests_attempted']==0 and h.count(DiscoveryObservation)==0

@pytest.mark.parametrize('bad',['unknown','mismatch','duplicate','arbitrary','sync'])
def test_binding_rejections(h,bad):
    binding=Binding('wallet.public_code_mentions','test_one',1,1,SyntheticExecutor(),QuotaPolicy(daily_units=10,monthly_units=100))
    if bad=='unknown':binding=replace(binding,transform_id='unknown')
    if bad=='mismatch':binding=replace(binding,transform_version=2)
    if bad=='duplicate':h.executors.register(binding)
    if bad=='arbitrary':binding={'module':'test-only'}
    if bad=='sync':binding=replace(binding,executor=lambda context:{})
    with pytest.raises(DiscoveryError):h.executors.register(binding)

@pytest.mark.parametrize('bad',[
    {'subject':{'chain':'ethereum','address':'wrong'}},
    {'subject':{'chain':'ens','address':'name.eth'}},
    {'selections':[{'transform_id':'unknown'}]},
    {'selections':[{'transform_id':'wallet.public_code_mentions','source_id':'unrelated'}]},
    {'selections':[{'transform_id':'wallet.public_code_mentions','source_id':'test_one'}]*2},
    {'selections':[{'transform_id':'wallet.public_code_mentions','source_id':'test_one','parameters':{'max_results':101}}]},
    {'selections':[{'transform_id':'wallet.public_code_mentions','source_id':'test_one','parameters':{'callback':'test'}}]},
    {'budget':{'paid_units':{'test_one':-1}}},
    {'budget':{'paid_units':{'test_one':True}}},
    {'budget':{'paid_units':{'unknown':1}}},
    {'callback_url':'https://example.invalid'},
])
def test_validation_before_execution(h,bad):
    executor=h.bind()
    with pytest.raises((DiscoveryError,ValidationError)):request(h.runtime,**bad)
    assert executor.calls==0 and h.count(DiscoveryRun)==0

def test_cache_refresh_and_history(h):
    executor=h.bind()
    async def scenario():
        first=await job(h);second=await job(h)
        assert second['sources'][0]['status']=='cache_hit' and executor.calls==1
        with h.runtime.service() as svc:
            a=svc.result_page(first['id'])['items'][0]['observation'];b=svc.result_page(second['id'])['items'][0]['observation']
            assert a['id']==b['id'] and a['retrieved_at']==b['retrieved_at']
        third=await job(h,refresh=True)
        assert third['status']=='completed' and executor.calls==2,third
        assert h.count(DiscoveryResult)==1 and h.count(DiscoveryObservation)==2
    asyncio.run(scenario())

@pytest.mark.parametrize('change',['expired','parameters','version','policy'])
def test_incompatible_cache_executes(h,change):
    executor=h.bind()
    async def scenario():
        first=await job(h)
        options={}
        if change=='expired':
            with h.sessions() as db:db.get(DiscoveryRunSource,first['sources'][0]['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        if change=='parameters':options['selections']=[{'transform_id':'wallet.public_code_mentions','source_id':'test_one','parameters':{'max_results':2}}]
        if change=='version':
            t=h.registry.transforms['wallet.public_code_mentions'];h.registry.transforms[t.id]=t.model_copy(update={'version':2})
            binding=h.executors.get(t.id,'test_one');h.executors._bindings[(t.id,'test_one')]=replace(binding,transform_version=2)
        if change=='policy':
            binding=h.executors.get('wallet.public_code_mentions','test_one');h.executors._bindings[(binding.transform_id,'test_one')]=replace(binding,quota=binding.quota.model_copy(update={'generation':'2'}))
        assert (await job(h,**options))['status']=='completed' and executor.calls==2
    asyncio.run(scenario())

@pytest.mark.parametrize('limit,count',[(1,2),(100,101)])
def test_oversized_batch_rejected_without_partial_rows(h,limit,count):
    h.bind(executor=SyntheticExecutor(records=[material(repository=str(i+1)) for i in range(count)]))
    row=asyncio.run(job(h,selections=[{'transform_id':'wallet.public_code_mentions','source_id':'test_one','parameters':{'max_results':limit}}]))
    assert row['status']=='failed' and row['sources'][0]['error_code']=='invalid_provider_response'
    assert h.count(DiscoveryResult)==h.count(DiscoveryRunItem)==0

@pytest.mark.parametrize('budget,permitted',[(None,False),({'paid_units':{'test_one':0}},False),({'paid_units':{'test_one':2}},True)])
def test_paid_budget_default_zero(tmp_path,budget,permitted):
    h=Harness(tmp_path,cost='PAID');executor=h.bind(units_per_request=2)
    try:
        row=asyncio.run(job(h,**({'budget':budget} if budget else {})))
        assert (executor.calls==1)==permitted
        assert row['sources'][0]['units_consumed']==(2 if permitted else 0)
        assert row['sources'][0]['status']==('succeeded' if permitted else 'budget_exhausted')
    finally:h.engine.dispose()

def test_free_local_has_no_remote_charge(tmp_path):
    h=Harness(tmp_path,cost='FREE_LOCAL',mode='local');executor=h.bind(executor=SyntheticExecutor('local'))
    try:
        row=asyncio.run(job(h));assert row['status']=='completed' and executor.calls==1
        assert row['sources'][0]['units_consumed']==row['sources'][0]['requests_attempted']==0
    finally:h.engine.dispose()

@pytest.mark.parametrize('cap',['daily_units','monthly_units'])
def test_persisted_quota_blocks_next_refresh(h,cap):
    executor=h.bind(**{cap:1})
    async def scenario():
        assert (await job(h))['status']=='completed'
        second=await job(h,refresh=True)
        assert second['sources'][0]['status']=='budget_exhausted' and executor.calls==1
    asyncio.run(scenario())

@pytest.mark.parametrize('configured',[False,True])
def test_configured_gate(tmp_path,monkeypatch,configured):
    h=Harness(tmp_path,credential=True);executor=h.bind()
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','synthetic-config-canary' if configured else '')
    try:
        row=asyncio.run(job(h));assert executor.calls==int(configured)
        assert 'synthetic-config-canary' not in json.dumps(row)
        if not configured:assert row['sources'][0]['error_code']=='configuration_unavailable'
    finally:h.engine.dispose()

def test_rate_limited_metadata_and_no_retry(h):
    executor=h.bind(executor=SyntheticExecutor('rate_limited'));row=asyncio.run(job(h))
    assert executor.calls==executor.attempts==1
    source=row['sources'][0];assert source['retry_after_at'] and source['quota_snapshot']['remaining']==0

def test_idempotency_and_overlap(h):
    executor=h.bind()
    async def scenario():
        executor.entered=asyncio.Event();executor.release=asyncio.Event()
        payload=request(h.runtime)
        first=await h.runtime.create_and_execute_run(payload,'same-key')
        await asyncio.wait_for(executor.entered.wait(),5)
        same=await h.runtime.create_and_execute_run(payload,'same-key');assert same['id']==first['id']
        with pytest.raises(Conflict):await h.runtime.create_and_execute_run(payload,'another-key')
        with pytest.raises(Conflict):await h.runtime.create_and_execute_run(request(h.runtime,refresh=True),'same-key')
        executor.release.set();await h.runtime._tasks[first['id']]
        assert (await h.runtime.create_and_execute_run(payload,'same-key'))['id']==first['id'] and executor.calls==1
        assert (await job(h,refresh=True))['status']=='completed'
    asyncio.run(scenario())

def test_running_cancellation_retains_charge(h):
    executor=h.bind()
    async def scenario():
        executor.entered=asyncio.Event();executor.release=asyncio.Event()
        row=await h.runtime.create_and_execute_run(request(h.runtime))
        await asyncio.wait_for(executor.entered.wait(),5)

        with h.runtime.service() as svc:version=svc.get_run(row['id'])['version']
        cancelled=await h.runtime.cancel(row['id'],version)
        assert cancelled['status']=='cancelled' and cancelled['sources'][0]['units_consumed']==1
        await asyncio.sleep(0)
        assert h.count(DiscoveryObservation)==0
        with pytest.raises(Conflict):await h.runtime.cancel(row['id'],cancelled['version'])
    asyncio.run(scenario())

def test_queued_cancel_never_executes(h):
    executor=h.bind()
    async def scenario():
        row=await h.runtime.create_and_execute_run(request(h.runtime))
        result=await h.runtime.cancel(row['id'],row['version'])
        assert result['status']=='cancelled';await asyncio.sleep(0);assert executor.calls==0
    asyncio.run(scenario())

def test_recovery_interrupts_without_replay(h):
    executor=h.bind()
    with h.runtime.service() as svc:
        subject=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
        row=svc.create_run(subject['id'],[{'transform_id':'wallet.public_code_mentions','source_id':'test_one'}],idempotency_key='orphan')
        svc.transition_run(row['id'],'running',expected_version=row['version'])
    asyncio.run(h.runtime.start())
    with h.runtime.service() as svc:assert svc.get_run(row['id'])['status']=='interrupted'
    assert executor.calls==0

def test_late_persistence_failure_rolls_back_only_one_source(h,monkeypatch):
    h.bind();h.bind('test_two');original=ExecutionService._attach
    def fail(self,source,*args,**kwargs):
        if source.source_id=='test_two':raise RuntimeError('synthetic late write failure')
        return original(self,source,*args,**kwargs)
    monkeypatch.setattr(ExecutionService,'_attach',fail)
    row=asyncio.run(job(h,('test_one','test_two')))
    assert row['status']=='partial' and row['returned_count']==1
    assert h.count(DiscoveryObservation)==h.count(DiscoveryRunItem)==1

def test_discovery_execution_and_review_boundaries(h):
    before=[h.count(model) for model in (AttributionEntity,RiskResult,Case,Label,KycScreeningRun)]
    executor=h.bind();first=asyncio.run(job(h))
    with h.runtime.service() as svc:
        item=svc.result_page(first['id'])['items'][0];result=item['result'];ob=item['observation']
        svc.review(result['id'],ob['id'],'relevant','Test review',expected_version=result['version'],expected_source_fingerprint=ob['content_sha256'])
    executor.records=[material('changed synthetic context')];asyncio.run(job(h,refresh=True))
    with h.runtime.service() as svc:
        assert svc.get_result(result['id'])['new_material_since_review']
        assert svc.list_reviews(result['id'])['total']==1
    assert before==[h.count(model) for model in (AttributionEntity,RiskResult,Case,Label,KycScreeningRun)]

def test_selection_changes_cannot_reset_source_quota(h):
    executor=h.bind(daily_units=1);h.bind('test_two')
    async def scenario():
        await job(h)
        row=await job(h,('test_one','test_two'),refresh=True)
        assert row['sources'][0]['status']=='budget_exhausted' and executor.calls==1
        assert row['sources'][1]['status']=='succeeded'
    asyncio.run(scenario())

def test_paid_allowance_shared_by_transforms_on_same_source(tmp_path):
    h=Harness(tmp_path,cost='PAID');first=h.bind()
    transform=h.registry.transforms['wallet.public_code_mentions']
    other=transform.model_copy(update={'id':'test.second_transform'})
    h.registry.transforms[other.id]=other
    second=SyntheticExecutor()
    h.executors.register(Binding(other.id,'test_one',1,1,second,QuotaPolicy(daily_units=1000,monthly_units=30000)))
    async def scenario():
        row=await job(h,selections=[{'transform_id':t,'source_id':'test_one'} for t in [transform.id,other.id]],budget={'paid_units':{'test_one':1}})
        assert row['status']=='partial' and first.calls==1 and second.calls==0
        assert row['sources'][1]['status']=='budget_exhausted'
    try:asyncio.run(scenario())
    finally:h.engine.dispose()

def test_framework_deadline_cancels_delayed_executor(h):
    transform=h.registry.transforms['wallet.public_code_mentions']
    h.registry.transforms[transform.id]=transform.model_copy(update={'deadline_seconds':1})
    executor=h.bind()
    async def scenario():
        executor.release=asyncio.Event()
        row=await job(h)
        assert row['sources'][0]['status']=='timeout' and executor.attempts==1
        assert h.count(DiscoveryObservation)==0
    asyncio.run(scenario())

def test_rolling_rate_limit_uses_prior_failed_attempts(h):
    source=h.registry.sources['test_one'];h.registry.sources[source.id]=source.model_copy(update={'rate_limit_per_minute':1})
    executor=h.bind(executor=SyntheticExecutor('exception'))
    async def scenario():
        await job(h)
        row=await job(h,refresh=True)
        assert row['sources'][0]['status']=='rate_limited' and executor.attempts==1
        assert row['sources'][0]['retry_after_at']
    asyncio.run(scenario())

@pytest.mark.parametrize('bad',['predicate','url','snapshot','title','private_code','oversize_bytes'])
def test_invalid_normalized_material_rejected_atomically(h,bad):
    record=material()
    if bad=='predicate':record['predicate']='owned_by'
    if bad=='url':record['observation']['source_url']='file:///private/test'
    if bad=='snapshot':record['observation']['source_snapshot']['value']=object()
    if bad=='title':record['observation']['title']=''
    if bad=='private_code':record['observation']['source_snapshot']['public']=False
    if bad=='oversize_bytes':
        t=h.registry.transforms['wallet.public_code_mentions'];h.registry.transforms[t.id]=t.model_copy(update={'max_bytes':100})
    h.bind(executor=SyntheticExecutor(records=[record]))
    row=asyncio.run(job(h))
    assert row['status']=='failed' and h.count(DiscoveryObservation)==h.count(DiscoveryResult)==0

@pytest.mark.parametrize('cost,flag',[('FREE_LOCAL','allow_free_local'),('FREE_REMOTE','allow_free_remote'),('LIMITED_FREE','allow_limited_free')])
def test_free_cost_permissions_are_explicit(tmp_path,cost,flag):
    h=Harness(tmp_path,cost=cost);executor=h.bind()
    try:
        row=asyncio.run(job(h,budget={flag:False}))
        assert executor.calls==0 and row['sources'][0]['status']=='budget_exhausted'
    finally:h.engine.dispose()

def test_shutdown_interrupts_inflight_without_replay(h):
    executor=h.bind()
    async def scenario():
        executor.entered=asyncio.Event();executor.release=asyncio.Event()
        row=await h.runtime.create_and_execute_run(request(h.runtime))
        await asyncio.wait_for(executor.entered.wait(),5)
        await h.runtime.stop()
        with h.runtime.service() as svc:
            interrupted=svc.get_run(row['id'])
            assert interrupted['status']=='interrupted' and interrupted['sources'][0]['units_consumed']==1
        await h.runtime.start()
        assert executor.calls==1
    asyncio.run(scenario())

def test_source_policy_registration_is_consistent(h):
    h.bind()
    t=h.registry.transforms['wallet.public_code_mentions'];other=t.model_copy(update={'id':'test.extra'})
    h.registry.transforms[other.id]=other
    with pytest.raises(DiscoveryError):h.executors.register(Binding(other.id,'test_one',1,1,SyntheticExecutor(),QuotaPolicy(daily_units=1,monthly_units=2)))

def test_creation_late_failure_rolls_back_subject_and_run(h,monkeypatch):
    h.bind();original=ExecutionService.create_run
    def fail(self,*args,**kwargs):
        original(self,*args,**kwargs)
        raise RuntimeError('synthetic late creation failure')
    monkeypatch.setattr(ExecutionService,'create_run',fail)
    with pytest.raises(RuntimeError):asyncio.run(h.runtime.create_and_execute_run(request(h.runtime)))
    from greedy_collector.models import DiscoverySubject
    assert h.count(DiscoverySubject)==h.count(DiscoveryRun)==0

def test_reservation_does_not_cross_utc_day(h):
    executor=h.bind()
    row=asyncio.run(job(h))
    created=datetime.fromisoformat(row['created_at']);deadline=datetime.fromisoformat(row['deadline_at'])
    assert deadline<=created.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    assert len(row['sources'][0]['attempt_log'])==executor.attempts==1

def test_successful_quota_report_is_atomic_and_conservative(h):
    class Reporting(SyntheticExecutor):
        async def execute(self,context):
            value=await super().execute(context)
            value['quota']={'remaining':17,'reported_units':0,'reset_at':datetime.now(timezone.utc)+timedelta(hours=1)}
            return value
    h.bind(executor=Reporting())
    row=asyncio.run(job(h));source=row['sources'][0]
    assert row['status']=='completed' and source['quota_snapshot']['remaining']==17
    assert source['quota_snapshot']['reported_units']==0 and source['units_consumed']==1

def test_retry_after_blocks_explicit_rerun(h):
    executor=h.bind(executor=SyntheticExecutor('rate_limited'))
    async def scenario():
        first=await job(h);second=await job(h,refresh=True)
        assert first['sources'][0]['status']==second['sources'][0]['status']=='rate_limited'
        assert executor.calls==1 and second['sources'][0]['requests_attempted']==0
    asyncio.run(scenario())

def test_different_subject_runs_are_independent_after_completion(h):
    executor=h.bind(executor=SyntheticExecutor('empty'))
    async def scenario():
        first=await job(h)
        second=await job(h,subject={'chain':'ethereum','address':'0x'+'cd'*20})
        assert first['subject_id']!=second['subject_id'] and executor.calls==2
        assert second['status']=='completed'
    asyncio.run(scenario())

def test_extra_selection_does_not_change_existing_logical_query(h):
    first=h.bind();second=h.bind('test_two')
    async def scenario():
        await job(h)
        row=await job(h,('test_one','test_two'))
        assert row['sources'][0]['status']=='cache_hit' and row['sources'][1]['status']=='succeeded'
        assert first.calls==second.calls==1
    asyncio.run(scenario())

def test_shutdown_before_worker_start_interrupts_queued_run(h):
    executor=h.bind()
    async def scenario():
        row=await h.runtime.create_and_execute_run(request(h.runtime))
        await h.runtime.stop()
        with h.runtime.service() as svc:assert svc.get_run(row['id'])['status']=='interrupted'
        assert executor.calls==0
    asyncio.run(scenario())
