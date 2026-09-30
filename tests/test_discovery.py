"""ED-1 real service/SQLite tests; all observations and sources here are test-only."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone,date
import json
import pytest
from pydantic import ValidationError
from sqlalchemy import select,text,func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base,Label,AttributionEntity,RiskResult,Case,KycScreeningRun,DiscoveryRun,DiscoveryResult,DiscoveryObservation,DiscoveryRunItem,DiscoveryReview,DiscoverySubject
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.domain import DiscoveryError,Conflict,NotFound,canonical_subject,query_fingerprint,result_identity,observation_fingerprint,ObservationInput,clean
from greedy_collector.discovery.registry import REGISTRY,Registry,SourceDescriptor,TransformDescriptor

ETH='0x'+'aB'*20
BTC='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
BECH='bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'

@pytest.fixture
def svc(tmp_path,monkeypatch):
    def no_network(*args,**kwargs):raise AssertionError('ED-1 must not call providers')
    monkeypatch.setattr('httpx.AsyncClient.request',no_network);monkeypatch.setattr('httpx.Client.request',no_network)
    sources=[s.model_dump() for s in REGISTRY.sources.values()]
    for source in sources:source['storage_allowed']=True
    sources.append({**sources[-1],'id':'github_second'})
    transforms=[t.model_dump() for t in REGISTRY.transforms.values()]
    transforms[-1]['source_ids']=('github','github_second')
    registry=Registry(sources,transforms)
    engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'discovery.db').as_posix())
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:yield DiscoveryService(db,metadata_only=True,registry=registry)
    finally:engine.dispose()

def subject(svc):return svc.get_or_create_subject('blockchain_address','ethereum',ETH)
def run(svc,key='test-run',source='github',refresh=False):
    return svc.create_run(subject(svc)['id'],[{'transform_id':'wallet.public_code_mentions','source_id':source}],idempotency_key=key,refresh=refresh)
def start(svc,row):
    row=svc.transition_run(row['id'],'running',expected_version=row['version'])
    svc.transition_source(row['sources'][0]['id'],'running',expected_run_version=row['version'])
    return svc.get_run(row['id'])
def record(content='Synthetic public context',**overrides):
    return {'kind':'candidate_relationship','predicate':'repository_contains',
        'from':{'kind':'repository','namespace':'github','value':'123'},
        'to':{'kind':'blockchain_address','namespace':'ethereum','value':ETH},'fact_key':{'path':'README.md'},
        'observation':{'kind':'code_search_result','source_record_key':'README.md:blob-one','source_url':'https://example.invalid/repo/README.md',
        'title':'Synthetic repository reference','summary':content,'retrieved_at':datetime.now(timezone.utc),
        'source_snapshot':{'public':True,'path':'README.md','blob_sha':'test-blob','metadata':{'source_date':date(2026,9,13)}},**overrides}}
def batch(svc,row,records=None,**kwargs):return svc.record_batch(row['sources'][0]['id'],records if records is not None else [record()],expected_run_version=row['version'],**kwargs)
def saved(svc):
    row=start(svc,run(svc));data=batch(svc,row);ob=svc.get_observation(data['observation_ids'][0]);return row,ob
def counts(svc):return [svc.db.scalar(select(func.count()).select_from(m)) for m in (DiscoverySubject,DiscoveryResult,DiscoveryObservation,DiscoveryRunItem,DiscoveryReview)]

@pytest.mark.parametrize('chain,address',[('bitcoin',BTC),('bitcoin',BECH),('ethereum',ETH)])
def test_subject_creation_and_reuse(svc,chain,address):
    a=svc.get_or_create_subject('blockchain_address',chain,address);b=svc.get_or_create_subject('blockchain_address',chain,' '+address+' ')
    assert a['id']==b['id'];assert len(a['identity_sha256'])==64
    assert svc.get_subject(a['id'])==a

def test_ethereum_case_equivalence_and_bitcoin_case_distinction(svc):
    assert subject(svc)['id']==svc.get_or_create_subject('blockchain_address','ethereum',ETH.lower())['id']
    assert svc.get_or_create_subject('blockchain_address','bitcoin',BTC)['canonical_value']==BTC
    with pytest.raises(DiscoveryError):
        svc.get_or_create_subject('blockchain_address','bitcoin',BTC.replace('A','a',1))

@pytest.mark.parametrize('chain,address',[('ethereum','0xwrong'),('bitcoin','invalid'),('any',ETH),('ethereum',ETH[:10]+'\u200b'+ETH[10:]),('ethereum',ETH+' secret')])
def test_bad_subjects_are_local(svc,chain,address):
    with pytest.raises(DiscoveryError):svc.get_or_create_subject('blockchain_address',chain,address)

@pytest.mark.parametrize('kind,namespace,value',[('url','https','https://Example.invalid:443'),('domain','dns','EXAMPLE.invalid.'),('repository','github','123'),('annotation','gc-label','test-id')])
def test_output_types_are_not_executable_inputs(svc,kind,namespace,value):
    row=svc.get_or_create_subject(kind,namespace,value)
    with pytest.raises(DiscoveryError):svc.create_run(row['id'],[],idempotency_key='unsupported')

@pytest.mark.parametrize('kind',['ens_name','transaction_hash','person','tracking_id','shell'])
def test_reserved_types_are_not_enabled(svc,kind):
    with pytest.raises(DiscoveryError):svc.get_or_create_subject(kind,'x','test')

def test_run_definition_idempotency_and_paging(svc):
    first=run(svc);assert first['status']=='queued' and first['started_at'] is None
    assert first['request_snapshot']['paid_budget_units']==0
    assert run(svc)['id']==first['id'];run(svc,'second')
    page=svc.list_runs(limit=1);assert page['total']==2 and page['next_offset']==1
    assert svc.list_runs(limit=1,offset=1)['next_offset'] is None
    with pytest.raises(Conflict):run(svc,refresh=True)
    assert svc.db.scalar(select(func.count()).select_from(DiscoveryObservation))==0

@pytest.mark.parametrize('status',['cancelled','interrupted'])
def test_cancellation_and_interruption(svc,status):
    row=start(svc,run(svc));row=svc.transition_run(row['id'],status,expected_version=row['version'])
    assert row['completed_at'] and row['sources'][0]['status']==status
    with pytest.raises(Conflict):svc.transition_run(row['id'],'running',expected_version=row['version'])

def test_valid_completion_and_archive(svc):
    row=start(svc,run(svc));batch(svc,row,[]);row=svc.get_run(row['id'])
    row=svc.transition_run(row['id'],'completed',expected_version=row['version']);assert row['completed_at']
    row=svc.archive_run(row['id'],expected_version=row['version']);assert svc.list_runs()['total']==0
    assert svc.list_runs(include_archived=True)['total']==1
    assert svc.archive_run(row['id'],expected_version=row['version'],restore=True)['archived_at'] is None

@pytest.mark.parametrize('status',['completed','partial','failed','pending','anything'])
def test_invalid_initial_transitions(svc,status):
    row=run(svc)
    with pytest.raises(DiscoveryError):svc.transition_run(row['id'],status,expected_version=row['version'])

def test_source_failure_is_independent_and_safe(svc):
    s=subject(svc);row=svc.create_run(s['id'],[{'transform_id':'wallet.public_code_mentions','source_id':x} for x in ['github','github_second']],idempotency_key='two')
    row=svc.transition_run(row['id'],'running',expected_version=row['version'])
    svc.transition_source(row['sources'][0]['id'],'unavailable',expected_run_version=row['version'],error_code='configuration_unavailable',quota_snapshot={'remaining':3,'client_secret':'synthetic-secret'})
    row=svc.get_run(row['id']);svc.transition_source(row['sources'][1]['id'],'running',expected_run_version=row['version'])
    row=svc.get_run(row['id']);svc.record_batch(row['sources'][1]['id'],[record()],expected_run_version=row['version'])
    row=svc.get_run(row['id']);row=svc.transition_run(row['id'],'partial',expected_version=row['version'])
    assert row['sources'][0]['quota_snapshot']=={'remaining':3,'client_secret':'[redacted]'}
    assert row['sources'][1]['returned_count']==1

@pytest.mark.parametrize('error',['secret raw exception','HTTP key=secret','traceback'])
def test_unregistered_errors_rejected(svc,error):
    row=svc.transition_run(run(svc)['id'],'running',expected_version=1)
    with pytest.raises(DiscoveryError):svc.transition_source(row['sources'][0]['id'],'unavailable',expected_run_version=row['version'],error_code=error)

def test_dedup_same_execution_and_new_retrieval(svc):
    first=record();row=start(svc,run(svc));data=batch(svc,row,[first,deepcopy(first)])
    assert len(data['observation_ids'])==1;ob=svc.get_observation(data['observation_ids'][0]);rid=ob['result_id']
    second=start(svc,run(svc,'second'));later=batch(svc,second,[record()]);ob2=svc.get_observation(later['observation_ids'][0])
    assert ob2['id']!=ob['id'] and ob2['result_id']==rid and ob2['content_sha256']==ob['content_sha256']
    assert svc.get_result(rid)['material_revision']==1
    assert svc.run_items(row['id'])['total']==1 and svc.run_items(second['id'])['total']==1

def test_changed_content_and_two_provider_provenance(svc):
    _,ob=saved(svc)
    row=start(svc,run(svc,'second',source='github_second'));data=batch(svc,row,[record('Contradictory synthetic context')]);ob2=svc.get_observation(data['observation_ids'][0])
    assert ob2['result_id']==ob['result_id'] and ob2['content_sha256']!=ob['content_sha256']
    assert svc.list_observations(ob['result_id'])['total']==2
    assert ob2['execution_id']!=ob['execution_id']

@pytest.mark.parametrize('predicate',['owned_by','controlled_by','operated_by','resolves_to','unknown'])
def test_bounded_predicates(svc,predicate):
    row=start(svc,run(svc));value=record();value['predicate']=predicate;before=counts(svc)
    with pytest.raises(DiscoveryError):batch(svc,row,[value])
    assert counts(svc)==before

def test_json_sanitization_and_dates(svc,monkeypatch):
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','synthetic-token-only')
    value=record();value['observation']['source_snapshot']['metadata'].update({'nested':{'api_key':'synthetic-token-only','debug':{'path':'C:/private/db'}},'at':datetime(2026,9,13,tzinfo=timezone.utc)})
    row=start(svc,run(svc));data=batch(svc,row,[value]);ob=svc.get_observation(data['observation_ids'][0])
    output=json.dumps(ob);assert 'synthetic-token-only' not in output and 'C:/private' not in output
    assert ob['source_snapshot']['metadata']['source_date']=='2026-09-13'
    assert ob['source_snapshot']['metadata']['at'].endswith('+00:00')

@pytest.mark.parametrize('operation',['UPDATE','DELETE','REPLACE_ID','REPLACE_UNIQUE'])
def test_database_observation_immutability(svc,operation):
    _,ob=saved(svc);db=svc.db;table=DiscoveryObservation.__table__
    with pytest.raises(IntegrityError):
        if operation=='UPDATE':db.execute(text('UPDATE discovery_observations SET summary=:value WHERE id=:id'),{'value':'rewrite','id':ob['id']})
        elif operation=='DELETE':db.execute(text('DELETE FROM discovery_observations WHERE id=:id'),{'id':ob['id']})
        else:
            values=dict(db.execute(select(table).where(table.c.id==ob['id'])).mappings().one())
            if operation=='REPLACE_UNIQUE':values['id']='different-id'
            db.execute(table.insert().prefix_with('OR REPLACE').values(**values))
    db.rollback();assert svc.get_observation(ob['id'])['summary']==ob['summary']

def test_orm_immutability(svc):
    _,ob=saved(svc);row=svc.db.get(DiscoveryObservation,ob['id']);row.summary='rewrite'
    with pytest.raises(ValueError,match='immutable'):svc.db.flush()
    svc.db.rollback()

@pytest.mark.parametrize('state',['unreviewed','relevant','irrelevant'])
def test_review_history_and_actor(svc,state):
    _,ob=saved(svc);row=svc.get_result(ob['result_id'])
    reviewed=svc.review(row['id'],ob['id'],state,'Synthetic review reason',expected_version=row['version'],expected_source_fingerprint=ob['content_sha256'])
    assert reviewed['review']['actor_ref']=='local_analyst' and reviewed['result']['review_status']==state
    assert not reviewed['result']['new_material_since_review']
    assert svc.list_reviews(row['id'])['total']==1
    with pytest.raises(DiscoveryError):svc.review(row['id'],ob['id'],'promoted','reason',expected_version=reviewed['result']['version'],expected_source_fingerprint=ob['content_sha256'])

def test_new_material_preserves_but_invalidates_old_review(svc):
    _,ob=saved(svc);row=svc.get_result(ob['result_id']);svc.review(row['id'],ob['id'],'irrelevant','Synthetic false positive',expected_version=row['version'],expected_source_fingerprint=ob['content_sha256'])
    row2=start(svc,run(svc,'same'));batch(svc,row2)
    assert not svc.get_result(row['id'])['new_material_since_review']
    row3=start(svc,run(svc,'changed'));batch(svc,row3,[record('Changed material')])
    current=svc.get_result(row['id']);assert current['new_material_since_review'] and current['review_status']=='irrelevant'
    assert svc.list_reviews(row['id'])['items'][0]['material_revision']==1

def test_review_stale_scope_and_reason(svc):
    _,ob=saved(svc);r=svc.get_result(ob['result_id'])
    with pytest.raises(Conflict):svc.review(r['id'],ob['id'],'relevant','reason',expected_version=999,expected_source_fingerprint=ob['content_sha256'])
    with pytest.raises(Conflict):svc.review(r['id'],ob['id'],'relevant','reason',expected_version=r['version'],expected_source_fingerprint='wrong')
    with pytest.raises(DiscoveryError):svc.review(r['id'],ob['id'],'relevant',' ',expected_version=r['version'],expected_source_fingerprint=ob['content_sha256'])

def test_fingerprints_are_distinct_and_deterministic():
    subj=canonical_subject('blockchain_address','ethereum',ETH);t,s=REGISTRY.pair('wallet.public_code_mentions','github')
    q=query_fingerprint(subj,t,s,{'max_results':100});assert q==query_fingerprint({**subj,'created_at':'ignored'},t,s,{'max_results':100})
    assert q!=query_fingerprint(subj,t.model_copy(update={'version':2}),s,{'max_results':100})
    assert q!=query_fingerprint(subj,t,s,{'max_results':50})
    material=record()['observation'];a=observation_fingerprint(material,'github');assert a==observation_fingerprint({**material,'retrieved_at':datetime.now(timezone.utc)},'github')
    assert a!=observation_fingerprint({**material,'summary':'changed'},'github')
    assert a!=observation_fingerprint(material,'second-provider')

def test_url_normalization_and_result_identity():
    query=canonical_subject('blockchain_address','ethereum',ETH)
    a=canonical_subject('url','https','https://EXAMPLE.invalid:443');b=canonical_subject('url','https','https://example.invalid/')
    assert a['identity_sha256']==b['identity_sha256']
    args=(query,'candidate_relationship','mentioned_at',query)
    assert result_identity(*args,a,{})==result_identity(*args,b,{})
    c=canonical_subject('url','http','http://example.invalid/')
    assert result_identity(*args,c,{})!=result_identity(*args,a,{})

def test_cache_reuse_preserves_observation_and_history(svc):
    first,ob=saved(svc);row=svc.get_run(first['id']);svc.transition_run(row['id'],'completed',expected_version=row['version'])
    second=run(svc,'second');sid=second['sources'][0]['id'];assert svc.cache_candidate(sid)
    assert svc.cache_candidate(sid,refresh=True) is None
    assert svc.cache_candidate(sid,now=datetime.now(timezone.utc)+timedelta(days=2)) is None
    second=svc.transition_run(second['id'],'running',expected_version=second['version'])
    source=svc.reuse_cache(sid,expected_run_version=second['version'])
    assert source['status']=='cache_hit' and source['requests_attempted']==0 and source['units_consumed']==0
    assert svc.run_items(second['id'])['items'][0]['observation_id']==ob['id']
    assert svc.get_observation(ob['id'])['retrieved_at']==ob['retrieved_at']
    assert svc.db.scalar(select(func.count()).select_from(DiscoveryObservation))==1

@pytest.mark.parametrize('coverage',['provider_incomplete','limit_reached','unknown'])
def test_incomplete_result_not_cached(svc,coverage):
    row=start(svc,run(svc));batch(svc,row,coverage=coverage)
    assert svc.cache_candidate(run(svc,'second')['sources'][0]['id']) is None

def test_batch_late_failure_rolls_back_all_material(svc,monkeypatch):
    row=start(svc,run(svc));before=counts(svc)
    def fail(*args):raise RuntimeError('late test-only failure')
    monkeypatch.setattr(svc,'_attach',fail)
    with pytest.raises(RuntimeError):batch(svc,row)
    assert counts(svc)==before and svc.get_run(row['id'])['sources'][0]['status']=='running'

def test_invalid_fk_and_history_rows_immutable(svc):
    _,ob=saved(svc)
    with pytest.raises(IntegrityError):svc.db.execute(DiscoveryRunItem.__table__.insert().values(run_source_id='missing',observation_id=ob['id'],ordinal=1,inclusion_kind='retrieved'))
    svc.db.rollback()
    with pytest.raises(IntegrityError):svc.db.execute(text('DELETE FROM discovery_run_items'))
    svc.db.rollback()
    r=svc.get_result(ob['result_id']);svc.review(r['id'],ob['id'],'relevant','Test review',expected_version=r['version'],expected_source_fingerprint=ob['content_sha256'])
    with pytest.raises(IntegrityError):svc.db.execute(text('UPDATE discovery_reviews SET reason=\'rewrite\''))
    svc.db.rollback();assert svc.db.execute(text('PRAGMA foreign_key_check')).all()==[]

def test_existing_subsystem_boundaries(svc):
    before=[svc.db.scalar(select(func.count()).select_from(m)) for m in (AttributionEntity,RiskResult,Case,Label,KycScreeningRun)]
    saved(svc)
    assert [svc.db.scalar(select(func.count()).select_from(m)) for m in (AttributionEntity,RiskResult,Case,Label,KycScreeningRun)]==before

def test_registry_capabilities_do_not_execute_or_leak(monkeypatch):
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','test-only-credential')
    values=REGISTRY.capabilities();assert len(values['transforms'])==8
    assert all(not t['implemented'] and not t['executable'] for t in values['transforms'])
    assert next(s for s in values['sources'] if s['id']=='github')['configured'] is True
    assert 'test-only-credential' not in json.dumps(values)
    assert next(t for t in values['transforms'] if t['id']=='wallet.manual_exact_web')['mode']=='manual'
    assert not hasattr(REGISTRY,'execute')

@pytest.mark.parametrize('field,value',[('id','shell command'),('version',0),('input_types',('domain',)),('output_types',('unknown',)),('cost_class','FREE'),('source_ids',('missing',)),('implemented',True),('callback_url','https://example.invalid')])
def test_bad_descriptors_rejected(field,value):
    values=REGISTRY.transforms['wallet.public_code_mentions'].model_dump();values[field]=value
    with pytest.raises((DiscoveryError,ValidationError)):Registry(list(REGISTRY.sources.values()),[values])

def test_duplicate_registry_entries_rejected():
    with pytest.raises(DiscoveryError):Registry(list(REGISTRY.sources.values())*2,[])
    with pytest.raises(DiscoveryError):Registry(list(REGISTRY.sources.values()),list(REGISTRY.transforms.values())*2)

@pytest.mark.parametrize('payload',[{'x':float('nan')},{'raw':'x'*17000},{'x':object()}])
def test_unsafe_json_rejected(payload):
    with pytest.raises(DiscoveryError):clean(payload)

@pytest.mark.parametrize('value',['https://user:password@example.invalid/path','file:///private/file','https://example.invalid/?api_key=secret','https://example.invalid/\nsecret'])
def test_unsafe_urls_rejected(value):
    with pytest.raises(DiscoveryError):canonical_subject('url','https',value)
