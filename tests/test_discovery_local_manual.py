"""Real ED-4A implementations via service/API; local test databases, no HTTP."""
import asyncio,csv,io,json,time
from datetime import datetime,timezone
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
import main
from greedy_collector.database import get_db
from greedy_collector.models import Label,DiscoveryResult,DiscoveryObservation,DiscoveryRun,AttributionEntity,AttributionClaim,RiskResult,Case,KycScreeningRun
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.router import get_runtime
from greedy_collector.discovery.executors import ExecutorRegistry,ManualBinding,production_executors
from greedy_collector.discovery.local import exact_web_actions
from greedy_collector.discovery.domain import DiscoveryError
from tests.test_discovery_execution import h,ETH
from tests.test_discovery_api import create,terminal,ok,PREFIX

BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
BECH='bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh'

@pytest.fixture
def live(h,monkeypatch):
    runtime=DiscoveryRuntime(h.sessions,metadata_only=True)
    monkeypatch.setattr(main,'start_monitoring',lambda:None)
    monkeypatch.setattr(main,'stop_monitoring',lambda:None)
    def blocked(*a,**k):raise AssertionError('ED-4A must not call external providers')
    monkeypatch.setattr('requests.Session.request',blocked)
    old=main.app.dependency_overrides.copy()
    def db():
        with h.sessions() as session:yield session
    main.app.dependency_overrides.update({get_runtime:lambda:runtime,get_db:db})
    try:
        with TestClient(main.app) as client:
            yield client,h,runtime
            client.portal.call(runtime.stop)
    finally:
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(old)

def label(client,chain='ethereum',address=ETH,**kw):
    return ok(client.post('/api/greedy-collector/labels/manual',json={'chain':chain,'address':address,'label':'Synthetic annotation','type':'Exchange','source':'Test analyst source','confidence':.8,**kw}))

def run(client,chain='ethereum',address=ETH,transforms=('wallet.local_labels',),refresh=False,maximum=None):
    data={'subject':{'chain':chain,'address':address},'selections':[{'transform_id':t,**({'parameters':{'max_results':maximum}} if maximum else {})} for t in transforms],'refresh':refresh}
    row=ok(create(client,data),202)
    row=terminal(client,row['id'])
    items=ok(client.get(PREFIX+'/runs/'+row['id']+'/results'))['items']
    return row,items

def counts(h):
    with h.sessions() as db:return [db.scalar(select(func.count()).select_from(m)) for m in (Label,AttributionEntity,AttributionClaim,RiskResult,Case,KycScreeningRun)]

@pytest.mark.parametrize('tid,mode,source',[('wallet.local_labels','local','gc_labels'),('wallet.manual_exact_web','manual','google')])
def test_production_capabilities(live,tid,mode,source):
    client,h,runtime=live
    row=next(t for t in ok(client.get(PREFIX+'/transforms')) if t['id']==tid)
    assert row['implemented'] and row['executable'] and row['configured']
    assert row['mode']==mode and row['cost_class']=='FREE_LOCAL' and row['max_requests']==0
    src=next(s for s in ok(client.get(PREFIX+'/sources')) if s['id']==source)
    assert src['executable'] and not src['credential_required']
    github=next(t for t in ok(client.get(PREFIX+'/transforms')) if t['id']=='wallet.public_code_mentions')
    assert not github['implemented'] and not github['executable']
    assert h.count(DiscoveryRun)==0

@pytest.mark.parametrize('chain,address,stored_chain,stored',[
    ('ethereum',ETH,'ethereum',ETH),('ethereum',ETH,'ethereum','0x'+('ab'*20).upper()),
    ('ethereum',ETH,'any',ETH),('bitcoin',BTC,'bitcoin',BTC),('bitcoin',BTC,'any',BTC),
    ('bitcoin',BECH,'bitcoin',BECH),('bitcoin',BECH,'any',BECH.upper()),
    ('ethereum',ETH,'any',' '+ETH+' '),
])
def test_label_exact_matching_and_provenance(live,chain,address,stored_chain,stored):
    client,h,_=live;record=label(client,stored_chain,stored)
    before=counts(h);original=ok(client.get('/api/greedy-collector/labels'))
    row,items=run(client,chain,address)
    assert row['status']=='completed' and len(items)==1
    source=row['sources'][0];assert source['source_id']=='gc_labels' and source['status']=='succeeded'
    assert source['requests_attempted']==source['units_consumed']==source['requests_reserved']==0
    result=items[0]['result'];assert result['predicate']=='locally_labeled_as'
    detail=ok(client.get(PREFIX+'/observations/'+items[0]['observation']['id']))
    assert detail['origin_label_id']==record['id'] and detail['source_id']=='gc_labels' and detail['transform_id']=='wallet.local_labels'
    captured=detail['source_snapshot']['record']
    assert {k:v for k,v in captured.items() if k!='last_updated'}=={k:v for k,v in record.items() if k!='last_updated'}
    assert datetime.fromisoformat(captured['last_updated'])==datetime.fromisoformat(record['last_updated']).replace(tzinfo=timezone.utc)
    assert detail['source_snapshot']['record']['confidence']==.8
    assert 'metadata' in detail['summary']
    assert counts(h)==before and ok(client.get('/api/greedy-collector/labels'))==original

@pytest.mark.parametrize('wrong_chain,wrong_address',[('bitcoin',BTC),('any','some arbitrary identifier'),('any',ETH+'aa'),('any',ETH[:20])])
def test_no_fuzzy_or_label_text_match(live,wrong_chain,wrong_address):
    client,h,_=live;label(client,wrong_chain,wrong_address,label=ETH)
    row,items=run(client);assert row['status']=='completed' and not items

def test_bitcoin_base58_case_remains_significant(live):
    client,_,_=live;label(client,'any',BTC.lower())
    row,items=run(client,'bitcoin',BTC);assert row['status']=='completed' and not items

def test_no_labels_is_success(live):
    row,items=run(live[0]);assert row['status']=='completed' and row['returned_count']==0 and not items

def test_conflicting_labels_are_preserved(live):
    client,h,_=live;a=label(client);b=label(client,label='Different service',source='Independent annotation',type='Mixer',confidence=.2)
    row,items=run(client);assert len(items)==2 and len({i['result']['id'] for i in items})==2
    details=[ok(client.get(PREFIX+'/observations/'+i['observation']['id'])) for i in items]
    assert {o['origin_label_id'] for o in details}=={a['id'],b['id']}
    assert sorted(o['source_snapshot']['record']['confidence'] for o in details)==[.2,.8]

def update_csv(client,record):
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=['chain','address','label','type','source','confidence']);writer.writeheader();writer.writerow({k:record[k] for k in writer.fieldnames})
    return ok(client.post('/api/greedy-collector/labels/import',files={'file':('test.csv',out.getvalue(),'text/csv')}))

def test_freshness_dedupe_changed_material_and_immutable_history(live):
    client,h,_=live;a=label(client)
    first,one=run(client);second,two=run(client)
    assert one[0]['result']['id']==two[0]['result']['id']
    assert one[0]['observation']['content_sha256']==two[0]['observation']['content_sha256']
    assert one[0]['observation']['id']!=two[0]['observation']['id']
    assert second['sources'][0]['cache_from_id'] is None
    result=two[0]['result'];o=two[0]['observation']
    ok(client.post(PREFIX+'/results/'+result['id']+'/review',json={'expected_version':result['version'],'observation_id':o['id'],'expected_source_fingerprint':o['content_sha256'],'status':'relevant','reason':'Synthetic review'}))
    update_csv(client,{**a,'confidence':.3,'type':'Bridge'})
    third,three=run(client)
    assert three[0]['result']['id']==result['id'] and three[0]['result']['new_material_since_review']
    assert three[0]['observation']['content_sha256']!=o['content_sha256']
    old=ok(client.get(PREFIX+'/observations/'+one[0]['observation']['id']))
    assert old['source_snapshot']['record']['confidence']==.8
    fourth,four=run(client,refresh=True)
    assert fourth['status']=='completed' and fourth['sources'][0]['expires_at'] is None
    new=ok(client.get(PREFIX+'/observations/'+four[0]['observation']['id']))
    assert new['source_snapshot']['record']['confidence']==.3
    assert h.count(DiscoveryResult)==1 and h.count(DiscoveryObservation)==4

def test_label_limit_reports_partial_without_claiming_complete_coverage(live):
    client,_,_=live
    for i in range(3):label(client,label='Synthetic '+str(i))
    row,items=run(client,maximum=2)
    assert row['status']=='partial' and len(items)==2 and row['sources'][0]['coverage']=='limit_reached'
    assert row['sources'][0]['provider_total'] is None

@pytest.mark.parametrize('source',['https://example.invalid/citation','https://user:password@example.invalid/?api_key=hidden&reference=public',r'C:\private\file.txt'])
def test_label_source_sanitization(live,source):
    client,_,_=live;label(client,source=source)
    row,items=run(client);assert row['status']=='completed'
    detail=ok(client.get(PREFIX+'/observations/'+items[0]['observation']['id']))
    text=json.dumps(detail)
    assert 'password' not in text and 'hidden' not in text and 'C:\\private' not in text
    if source.startswith('C:'):assert detail['source_url'] is None
    else:assert detail['source_url'].startswith('https://example.invalid/')

@pytest.mark.parametrize('chain,address',[('bitcoin',BTC),('bitcoin',BECH),('ethereum',ETH),('ethereum','0x'+('ab'*20).upper())])
def test_manual_generation_full_query_no_results(live,chain,address):
    client,h,_=live;before=counts(h)
    row,items=run(client,chain,address,('wallet.manual_exact_web',))
    assert row['status']=='completed' and not items and row['returned_count']==0
    source=row['sources'][0];assert source['status']=='manual_ready'
    assert source['coverage']=='unknown' and source['provider_total'] is None
    assert source['requests_attempted']==source['requests_reserved']==source['units_consumed']==0
    action=source['manual_actions'][0];canonical=row['subject']['canonical_value']
    assert action['query']=='"'+canonical+'"'
    url=urlsplit(action['url']);assert url.scheme=='https' and url.netloc=='www.google.com' and url.path=='/search'
    assert parse_qs(url.query)=={'q':['"'+canonical+'"']} and not url.fragment and not url.username
    assert 'not queried by Greedy Collector' in action['note'] and '...' not in action['query']
    assert h.count(DiscoveryResult)==h.count(DiscoveryObservation)==0 and counts(h)==before
    assert ok(client.get(PREFIX+'/runs/'+row['id']))['sources'][0]['manual_actions']==[action]

def test_mixed_local_manual_and_unimplemented(live):
    client,h,_=live;label(client)
    row,items=run(client,transforms=('wallet.local_labels','wallet.manual_exact_web','wallet.public_code_mentions'))
    assert row['status']=='partial' and len(items)==1
    assert [s['status'] for s in row['sources']]==['succeeded','manual_ready','unavailable']

def test_opening_and_planning_do_not_execute(live):
    client,h,_=live;label(client)
    for route in ['/','/health','/docs','/openapi.json','/static/js/discovery.js',PREFIX+'/sources',PREFIX+'/transforms']:
        assert client.get(route).status_code==200
    data={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.local_labels'},{'transform_id':'wallet.manual_exact_web'}]}
    planned=ok(client.post(PREFIX+'/plan',json=data));assert all(p['eligibility']=='eligible' for p in planned['selections'])
    assert h.count(DiscoveryRun)==h.count(DiscoveryObservation)==0

@pytest.mark.parametrize('bad',['wrong pair','version','duplicate','async','not binding'])
def test_manual_bindings_are_code_owned_and_bounded(h,bad):
    registry=ExecutorRegistry();binding=ManualBinding('wallet.manual_exact_web','google',1,1,exact_web_actions)
    if bad=='wrong pair':binding=ManualBinding('wallet.local_labels','gc_labels',1,1,exact_web_actions)
    if bad=='version':binding=ManualBinding('wallet.manual_exact_web','google',2,1,exact_web_actions)
    if bad=='duplicate':registry.register_manual(binding)
    if bad=='async':
        async def fn(subject):return []
        binding=ManualBinding('wallet.manual_exact_web','google',1,1,fn)
    if bad=='not binding':binding={'callback':'untrusted'}
    with pytest.raises(DiscoveryError):registry.register_manual(binding)

@pytest.mark.parametrize('value',['Manual action generation available','The search engine was not queried by Greedy Collector.','manual_actions','Manual action available — not queried by Greedy Collector','Opening this link leaves GC','Original annotation source','Annotation confidence (metadata only)','Stored Label provenance'])
def test_frontend_local_manual_contract(value):
    from pathlib import Path
    assert value in (Path(__file__).resolve().parents[1]/'static/js/discovery.js').read_text(encoding='utf8')

def test_paid_free_flag_blocks_manual_and_local(live):
    client,h,_=live
    data={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.local_labels'},{'transform_id':'wallet.manual_exact_web'}],'budget':{'allow_free_local':False}}
    plan=ok(client.post(PREFIX+'/plan',json=data))
    assert all(p['eligibility']=='budget_exhausted' for p in plan['selections'])
    row=ok(create(client,data),202);done=terminal(client,row['id'])
    assert done['status']=='failed' and all(not s['manual_actions'] for s in done['sources'])
    assert h.count(DiscoveryObservation)==0
