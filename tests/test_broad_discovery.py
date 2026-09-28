"""OSINT-2 real migrated API/runtime, fixed-host transport fixtures only."""
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from greedy_collector.database import create_fk_enabled_engine,get_db
from greedy_collector.discovery.router import router,get_runtime
from greedy_collector.attribution.router import router as attribution_router
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.broad import providers as p
from greedy_collector.discovery.broad.models import Candidate
from greedy_collector.models import Base,Case,CaseEntity,AttributionEvidence
from greedy_collector.attribution.service import AttributionService
from tests.test_discovery_api import ok,create,terminal,PREFIX as P
BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
ETH='0x'+'ab'*20
SECRET='osint2-test-only-key'
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def env(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'broad.db').as_posix()
    monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY',SECRET)
    monkeypatch.setenv('BRAVE_SEARCH_STORAGE_ALLOWED','true')
    monkeypatch.delenv('DISCOVERY_GITHUB_TOKEN',raising=False)
    cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'));command.upgrade(cfg,'head')
    engine=create_fk_enabled_engine(url,connect_args={'check_same_thread':False});sessions=sessionmaker(engine)
    runtime=DiscoveryRuntime(sessions)
    app=FastAPI();app.include_router(router,prefix='/api/greedy-collector');app.include_router(attribution_router,prefix='/api/greedy-collector')
    app.dependency_overrides[get_runtime]=lambda:runtime
    def db():
        with sessions() as session:yield session
    app.dependency_overrides[get_db]=db
    state=SimpleNamespace(calls=[],rows=[{'url':'https://www.justice.gov/test#section','title':'Test public notice','description':BTC+'; alias: vendor123; organization: Example Service;'}],more=False,error=None,status=200)
    def deny(*a,**k):raise AssertionError('No live requests or arbitrary result retrieval')
    monkeypatch.setattr('httpx.HTTPTransport.handle_request',deny);monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request',deny);monkeypatch.setattr('requests.Session.request',deny)
    def handler(request):
        state.calls.append(request)
        assert request.url.host=='api.search.brave.com' and request.url.path=='/res/v1/web/search'
        assert request.headers['X-Subscription-Token']==SECRET
        if state.error:raise state.error
        return httpx.Response(state.status,json={'web':{'results':state.rows},'query':{'more_results_available':state.more}})
    actual=httpx.AsyncClient
    monkeypatch.setattr(p,'httpx',SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError))
    with TestClient(app) as client:
        yield SimpleNamespace(c=client,db=sessions,state=state,engine=engine,cfg=cfg,runtime=runtime)
        client.portal.call(runtime.stop)
    engine.dispose()

def lookup(e,transforms=('wallet.broad_web',),chain='bitcoin',address=BTC,refresh=False,maximum=20):
    data={'broad':True,'subject':{'chain':chain,'address':address},'selections':[{'transform_id':t,'parameters':{'max_results': min(maximum, e.runtime.registry.transforms[t].max_results)}} for t in transforms],'refresh':refresh}
    row=terminal(e.c,ok(create(e.c,data),202)['id'])
    return row,ok(e.c.get(P+'/broad/runs/'+row['id']))

def unrelated(e):
    with e.db() as db:return {n:db.scalar(select(func.count()).select_from(t)) for n,t in Base.metadata.tables.items() if not n.startswith('discovery_')}

def review(e,o):
    result=ok(e.c.get(P+'/results/'+o['result_id']))
    return ok(e.c.post(P+'/results/'+o['result_id']+'/review',json={'observation_id':o['id'],'status':'relevant','reason':'Inspected metadata only','expected_version':result['version'],'expected_source_fingerprint':o['content_sha256']}))

def test_typed_registration_query_and_chain_scope():
    assert p.PROVIDERS.get('brave_search').id=='brave_search'
    registry=p.ProviderRegistry();registry.register(p.BraveProvider())
    with pytest.raises(ValueError):registry.register(p.BraveProvider())
    assert len(p.QueryType)==6 and p.DiscoveryQuery('bitcoin',BTC).text=='"'+BTC+'"'
    for kind in list(p.QueryType)[1:]:
        with pytest.raises(ValueError):p.DiscoveryQuery('bitcoin',BTC,query_type=kind)
    a=p.DiscoveryQuery('ethereum',ETH.upper().replace('0X','0x'));b=p.DiscoveryQuery('base',ETH)
    assert a.text==b.text and a.chain!=b.chain

@pytest.mark.parametrize('url',['http://localhost/a','https://127.0.0.1/','http://10.0.0.1/','http://[::1]/','file:///test','https://user:pass@example.org/','https://example.org/?token=private'])
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):p.canonical_url(url)

def test_canonical_metadata_candidates_and_exactness():
    q=p.DiscoveryQuery('bitcoin',BTC)
    record=p.normalize_result('brave_search',q,p.DiscoveryObservation('https://EXAMPLE.ORG:443/path#frag','Notice',BTC+'; handle: vendor123; entity: Example Service;',1),'2026-09-28T12:00:00Z')
    s=record['observation']['source_snapshot']
    assert s['canonical_url']=='https://example.org/path' and s['hostname']=='example.org' and s['registrable_domain'] is None
    assert s['exact_match'] and {v['kind'] for v in s['candidates']}=={'domain','alias','entity'}
    assert all('confidence_type' in c for c in s['candidates'])
    assert not p.exact_match(q,BTC+'a') and not p.exact_match(q,BTC.swapcase())
    assert not p.normalize_result('brave_search',q,p.DiscoveryObservation('https://example.org','Fuzzy','alias: vendor123',1),'2026-09-28T12:00:00Z')['observation']['source_snapshot']['exact_match']

def test_preflight_capabilities_no_network_and_optional_configuration(env,monkeypatch):
    e=env;caps=ok(e.c.get(P+'/transforms'));t=next(t for t in caps if t['id']=='wallet.broad_web')
    assert t['executable'] and t['cost_class']=='LIMITED_FREE' and t['max_results']==50
    data={'broad':True,'subject':{'chain':'bitcoin','address':BTC},'selections':[{'transform_id':t['id']}]}
    plan=ok(e.c.post(P+'/plan',json=data));assert plan['selections'][0]['parameters']['max_results']==20
    monkeypatch.setenv('BRAVE_SEARCH_STORAGE_ALLOWED','false')
    assert ok(e.c.post(P+'/plan',json=data))['selections'][0]['eligibility']=='retention_not_permitted'
    monkeypatch.delenv('BRAVE_SEARCH_API_KEY')
    assert ok(e.c.post(P+'/plan',json=data))['selections'][0]['eligibility']=='configuration_unavailable'
    assert not e.state.calls and SECRET not in json.dumps(caps)
    assert next(t for t in caps if t['id']=='wallet.ens_primary_name')['chains']==['ethereum']
    assert all(t['mode']=='manual' for t in caps if t['id'] in ('wallet.manual_exact_web','wallet.manual_source_observation'))

def test_real_run_candidates_graph_and_zero_unrelated_mutation(env):
    e=env;before=unrelated(e);row,s=lookup(e)
    assert row['status']=='completed' and row['broad'] and row['returned_count']==1,(row,s)
    assert len(e.state.calls)==1 and e.state.calls[0].url.params['q']=='"'+BTC+'"'
    assert len(s['candidates'])==3 and all(c['observation_id']==s['groups'][0]['observations'][0]['id'] for c in s['candidates'])
    graph=ok(e.c.get(P+'/runs/'+row['id']+'/graph'))
    assert {n['type'] for n in graph['items']}=={'web_source','alias_candidate','entity_candidate','domain_candidate'}
    assert {v['predicate'] for v in graph['edges']}=={'mentioned_at','names_alias','names_entity','references_domain'}
    assert len({n['id'] for n in graph['items']})==4
    assert unrelated(e)==before and SECRET not in json.dumps([row,s,graph])
    again=ok(e.c.get(P+'/broad/runs/'+row['id']));assert again==s

def test_federation_failure_isolation_and_manual_boundary(env):
    e=env;e.state.error=httpx.ReadTimeout('test only')
    row,s=lookup(e,('wallet.local_labels','wallet.public_code_mentions','wallet.graphsense_public_tags','wallet.broad_web'))
    assert row['status']=='partial'
    states={s['transform_id']:s['status'] for s in row['sources']}
    assert states['wallet.local_labels']=='succeeded' and states['wallet.broad_web']=='timeout'
    assert s['partial'] and len(e.state.calls)==1

def test_cache_refresh_ordering_dedupe_and_fuzzy_boundary(env):
    e=env;e.state.rows += [dict(e.state.rows[0],url='https://www.justice.gov/test#different'),{'url':'https://example.org/other','title':'Fuzzy result','description':'alias: unrelated'}]
    row,s=lookup(e);assert len(s['groups'])==2 and row['returned_count']==2
    assert [g['canonical_url'] for g in s['groups']]==sorted(g['canonical_url'] for g in s['groups'])
    cached,c=lookup(e);assert cached['sources'][0]['status']=='cache_hit' and len(e.state.calls)==1
    assert {o['cache_state'] for g in c['groups'] for o in g['observations']}=={'cache'}
    fuzzy=next(o for g in s['groups'] for o in g['observations'] if not o['source_snapshot']['exact_match'])
    review(e,fuzzy)
    assert not ok(e.c.get(P+'/observations/'+fuzzy['id']+'/promotion-preview'))['eligible']
    lookup(e,refresh=True);assert len(e.state.calls)==2
    assert ok(e.c.get(P+'/broad/runs/'+row['id']))['groups'][0]['observations'][0]['id']==s['groups'][0]['observations'][0]['id']

def test_bounds_no_recursive_or_arbitrary_fetch(env):
    e=env;e.state.rows=[{'url':f'https://hidden.onion/{i}','title':str(i),'description':BTC} for i in range(20)];e.state.more=True
    row,s=lookup(e,maximum=50)
    assert len(e.state.calls)==3 and row['returned_count']==20 and s['truncated']
    assert all(r.url.host=='api.search.brave.com' for r in e.state.calls)
    assert row['sources'][0]['quota_snapshot']['diagnostic']=='result_cap'
    data={'broad':True,'subject':{'chain':'bitcoin','address':BTC},'selections':[{'transform_id':'wallet.broad_web','parameters':{'max_results':51}}]}
    assert e.c.post(P+'/plan',json=data).status_code==422

def test_review_promotion_and_immutable_case_snapshot(env):
    e=env;row,s=lookup(e);o=s['groups'][0]['observations'][0];c=s['candidates'][0]
    before=unrelated(e)
    reviewed=ok(e.c.post(P+'/broad/candidates/'+c['id']+'/review',json={'status':'relevant','note':'Explicit source text only','expected_version':1}))
    assert reviewed['version']==2 and unrelated(e)==before
    assert e.c.post(P+'/broad/candidates/'+c['id']+'/review',json={'status':'irrelevant','note':'stale','expected_version':1}).status_code==409
    assert not ok(e.c.get(P+'/observations/'+o['id']+'/promotion-preview'))['eligible']
    review(e,o);preview=ok(e.c.get(P+'/observations/'+o['id']+'/promotion-preview'));assert preview['eligible']
    assert preview['evidence']['origin']=='public_osint' and preview['evidence']['metadata_json']['analyst_review_note']=='Inspected metadata only'
    with e.db() as db:
        svc=AttributionService(db);entity=svc.create_entity({'canonical_name':'Explicit analyst test entity'})
        claim=svc.create_claim({'entity_id':entity['id'],'chain':'bitcoin','subject_ref':BTC,'relationship':'operated_by','scope_note':'Explicit analyst test claim'})
        db.add(Case(id='test-case',title='Test Case'));db.commit()
    result=ok(e.c.post(P+'/observations/'+o['id']+'/promote',json={'result_id':o['result_id'],'claim_id':claim['id'],'expected_claim_version':claim['version'],'expected_source_fingerprint':preview['source_fingerprint'],'link':{'stance':'context','directness':'context','rationale':'Metadata only'}}),201)
    pin=ok(e.c.post(P+'/broad/cases/test-case/pin',json={'run_id':row['id']}))
    saved=pin['metadata_json']['broad_discovery_pin'];assert saved['candidate_reviews'] and saved['source_data_fingerprint']
    e.state.rows[0]['description']=BTC+'; alias: changed';lookup(e,refresh=True)
    with e.db() as db:
        assert db.get(CaseEntity,pin['id']).metadata_json['broad_discovery_pin']==saved
        ev=db.get(AttributionEvidence,result['promotion']['evidence_id']);assert ev.metadata_json['observation']['source_snapshot']['snippet']==o['excerpt']
    for sql in ["UPDATE discovery_broad_candidates SET value='changed'","DELETE FROM discovery_broad_candidates","UPDATE discovery_broad_candidate_reviews SET note='changed'","UPDATE case_entities SET metadata_json='{}' WHERE entity_type='broad_discovery'"]:
        with e.engine.connect() as db:
            with pytest.raises(IntegrityError,match='immutable'):db.execute(text(sql))
            db.rollback()
    with e.engine.connect() as db:assert db.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    with pytest.raises(RuntimeError,match='Retained'):command.downgrade(e.cfg,'20260927_02')


def test_empty_cache_and_unavailable_retention_gate(env,monkeypatch):
    e=env;e.state.rows=[]
    row,s=lookup(e);assert not s['groups'] and not s['candidates']
    again,_=lookup(e);assert again['sources'][0]['status']=='cache_hit' and len(e.state.calls)==1
    from datetime import datetime
    source=row['sources'][0]
    assert (datetime.fromisoformat(source['expires_at'])-datetime.fromisoformat(source['completed_at'])).total_seconds()<=3601
    monkeypatch.setenv('BRAVE_SEARCH_STORAGE_ALLOWED','false')
    blocked,_=lookup(e);assert blocked['sources'][0]['status']=='unavailable' and len(e.state.calls)==1


def test_chain_scope_and_missing_schema(env):
    e=env;e.state.rows[0]['description']=ETH
    a,x=lookup(e,chain='ethereum',address=ETH);b,y=lookup(e,chain='base',address=ETH)
    assert x['groups'][0]['result_ids']!=y['groups'][0]['result_ids']
    with e.engine.begin() as c:c.exec_driver_sql("UPDATE alembic_version SET version_num='20260927_02'")
    response=e.c.post(P+'/plan',json={'broad':True,'subject':{'chain':'bitcoin','address':BTC},'selections':[{'transform_id':'wallet.broad_web'}]})
    assert response.status_code==503 and len(e.state.calls)==2


@pytest.mark.parametrize('mode',['timeout','http','malformed'])
def test_later_page_failure_retains_successful_observations(env,monkeypatch,mode):
    e=env;actual=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(request)
        if len(calls)==1:return httpx.Response(200,json={'web':{'results':e.state.rows},'query':{'more_results_available':True}})
        if mode=='timeout':raise httpx.ReadTimeout('test-only')
        if mode=='malformed':return httpx.Response(200,content=b'not json')
        return httpx.Response(503)
    monkeypatch.setattr(p,'httpx',SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError))
    row,s=lookup(e)
    assert row['returned_count']==1 and row['status']=='partial' and s['truncated'] and len(calls)==2


def test_metadata_secret_redaction_and_private_url_omission(env):
    e=env;e.state.rows[0]['description']+=' '+SECRET
    e.state.rows.append({'url':'http://127.0.0.1/private','description':BTC})
    row,s=lookup(e);assert row['returned_count']==1 and s['truncated']
    assert SECRET not in json.dumps(s) and '[redacted]' in json.dumps(s)


def test_empty_migration_downgrade_and_legacy_data(env):
    e=env
    with e.db() as db:db.add(Case(id='legacy-case',title='Preserve'));db.commit()
    command.downgrade(e.cfg,'20260927_02');command.upgrade(e.cfg,'head')
    with e.db() as db:assert db.get(Case,'legacy-case').title=='Preserve'


def test_url_grouping_preserves_distinct_provider_observations(env):
    e=env
    from greedy_collector.discovery.executors import Binding,QuotaPolicy
    from greedy_collector.discovery.schemas import Batch
    class TestCode:
        async def execute(self,context):
            return Batch(records=[{'kind':'candidate_relationship','predicate':'repository_contains','from':{'kind':'repository','namespace':'github','value':'123'},'to':{'kind':'blockchain_address','namespace':'bitcoin','value':BTC},'fact_key':{'path':'README'},'observation':{'kind':'code_search_result','source_record_key':'test:README','source_url':'https://www.justice.gov/test','title':'Code reference','summary':BTC,'retrieved_at':'2026-09-28T12:00:00Z','source_snapshot':{'public':True}}}])
    import os
    old=os.environ.get('DISCOVERY_GITHUB_TOKEN');os.environ['DISCOVERY_GITHUB_TOKEN']='test-only'
    binding=Binding('wallet.public_code_mentions','github',1,1,TestCode(),QuotaPolicy(daily_units=100,monthly_units=3000))
    e.runtime.executors._bindings[('wallet.public_code_mentions','github')]=binding
    try:
        row,s=lookup(e,('wallet.broad_web','wallet.public_code_mentions'))
        assert len(s['groups'])==1 and {o['provider'] for o in s['groups'][0]['observations']}=={'github','brave_search'}
    finally:
        if old is None:os.environ.pop('DISCOVERY_GITHUB_TOKEN',None)
        else:os.environ['DISCOVERY_GITHUB_TOKEN']=old


def test_last_page_cap_and_malformed_shape_preserve_bounds(env,monkeypatch):
    e=env;actual=httpx.AsyncClient;calls=[]
    def handler(request):
        page=int(request.url.params['offset']);calls.append(page)
        return httpx.Response(200,json={'web':{'results':[{'url':f'https://example.org/{page}/{i}','description':BTC} for i in range(20)]},'query':{'more_results_available':page<2}})
    monkeypatch.setattr(p,'httpx',SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError))
    row,s=lookup(e,maximum=50)
    assert row['returned_count']==50 and s['truncated'] and calls==[0,1,2]
