"""Real ENS executor -> mocked HTTP -> real normalizer -> API/storage/graph/ED6."""
import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import json
import pytest
import httpx
from sqlalchemy import select,func
from greedy_collector.chains import base
from greedy_collector.discovery import ens
from greedy_collector.discovery.ens_normalization import EnsNormalizationError
from greedy_collector.discovery.executors import ExecutionSignal
from greedy_collector.discovery.registry import REGISTRY
from greedy_collector.models import DiscoverySubject,DiscoveryObservation,DiscoveryRunSource,AttributionEvidence
from tests.test_discovery_execution import h,ETH
from tests.test_discovery_local_manual import live as _existing_live,run,counts,BTC
from tests.test_discovery_api import ok,PREFIX,create
from tests.ens_rpc_fixture import encoded_reverse,reply

TOKEN='ed8a-test-only-secret'
A='/api/greedy-collector/attribution'

@pytest.fixture
def live(h,monkeypatch):
    # The legacy HTTP fixture overrides route dependencies, but app lifespan
    # separately constructs a runtime. Bind that startup runtime to this same
    # temporary database too; never open the operator's configured database.
    from greedy_collector.discovery.runtime import DiscoveryRuntime
    async def start(app):
        app.state.discovery=DiscoveryRuntime(h.sessions,metadata_only=True)
        await app.state.discovery.start()
    monkeypatch.setattr('main.start_discovery',start)
    yield from _existing_live.__wrapped__(h,monkeypatch)

@pytest.fixture
def rpc(live,monkeypatch):
    client,h,runtime=live
    with h.engine.begin() as c:
        c.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)')
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260916_01')")
    settings=SimpleNamespace(alchemy_api_key=TOKEN,request_timeout=1)
    monkeypatch.setattr(base,'get_settings',lambda:settings)
    monkeypatch.setattr(ens,'get_settings',lambda:settings)
    state=SimpleNamespace(calls=[],body=reply(),status=200,error=None,raw=None,headers={})
    def handler(request):
        state.calls.append(request)
        assert request.method=='POST'
        assert request.url.host=='eth-mainnet.g.alchemy.com' and request.url.path=='/v2/'+TOKEN
        payload=json.loads(request.content)
        assert payload['method']=='eth_call' and payload['params'][1]=='latest'
        assert payload['params'][0]['to']==ens.UNIVERSAL_RESOLVER
        if state.error:raise state.error
        return httpx.Response(state.status,**({'content':state.raw} if state.raw is not None else {'json':state.body}),headers=state.headers)
    actual=httpx.AsyncClient
    monkeypatch.setattr(base,'httpx',SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError))
    return client,h,runtime,state,settings

def execute(rpc,**kw):return run(rpc[0],transforms=(ens.TRANSFORM_ID,),**kw)
def graph(rpc,row):return ok(rpc[0].get(PREFIX+'/runs/'+row['id']+'/graph'))
def observation(rpc,item):return ok(rpc[0].get(PREFIX+'/observations/'+item['observation']['id']))

def test_exact_calldata_and_return_abi():
    expected='0x5d78a217'+'0'*62+'40'+'0'*62+'3c'+'0'*62+'14'+'ab'*20+'0'*24
    assert ens.reverse_calldata(ETH)==expected
    assert ens.UNIVERSAL_RESOLVER=='0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe'
    assert ens.decode_reverse(encoded_reverse())==('alice.eth','0x'+'11'*20,'0x'+'22'*20)

def test_capability_plan_has_no_network_or_automatic_run(rpc):
    c,h,runtime,state,_=rpc
    cap=next(t for t in ok(c.get(PREFIX+'/transforms')) if t['id']==ens.TRANSFORM_ID)
    assert cap['implemented'] and cap['configured'] and cap['executable']
    assert cap['chains']==['ethereum'] and cap['cost_class']=='LIMITED_FREE'
    assert cap['cache_seconds']==3600 and cap['max_results']==cap['max_requests']==1
    sources=ok(c.get(PREFIX+'/sources'));src=next(s for s in sources if s['id']==ens.SOURCE_ID)
    assert src['configured'] and src['executable'] and src['storage_allowed']
    assert TOKEN not in json.dumps([cap,sources]) and 'credential_env' not in src
    assert not state.calls and ok(c.get(PREFIX+'/runs'))['total']==0

@pytest.mark.parametrize('missing',['rpc','normalizer'])
def test_missing_capability_unavailable_safe_startup(rpc,monkeypatch,missing):
    c,_,runtime,state,settings=rpc
    if missing=='rpc':settings.alchemy_api_key=''
    else:monkeypatch.setattr(ens,'probe_ens_normalizer',lambda:SimpleNamespace(usable=False))
    cap=next(t for t in runtime.capabilities()['transforms'] if t['id']==ens.TRANSFORM_ID)
    assert cap['implemented'] and not cap['configured'] and not cap['executable']
    row,items=execute(rpc)
    assert not items and not state.calls and row['sources'][0]['error_code']=='configuration_unavailable'
    assert c.get('/health').status_code==200

@pytest.mark.parametrize('subject',[{'chain':'bitcoin','address':BTC},{'chain':'ens','address':'alice.eth'}])
def test_incompatible_root_never_requests_rpc(rpc,subject):
    c,_,_,state,_=rpc
    response=c.post(PREFIX+'/plan',json={'subject':subject,'selections':[{'transform_id':ens.TRANSFORM_ID}]})
    assert response.status_code==422 and not state.calls

@pytest.mark.parametrize('name',['alice.eth','é.eth','🦊.eth','👩\u200d💻.eth'])
def test_normalized_positive_real_api_storage_graph(rpc,monkeypatch,name):
    c,h,_,state,_=rpc;state.body=reply(name);before=counts(h)
    actual=ens.normalize_ens_name;normalized=[]
    def normalize(value):normalized.append(value);return actual(value)
    monkeypatch.setattr(ens,'normalize_ens_name',normalize)
    row,items=execute(rpc)
    assert row['status']=='completed' and len(items)==1,(row,items)
    assert normalized==[name] and len(state.calls)==1
    assert row['sources'][0]['requests_attempted']==row['sources'][0]['units_consumed']==1
    r=items[0]['result'];o=observation(rpc,items[0]);snap=o['source_snapshot']
    assert r['kind']=='candidate_relationship' and r['predicate']=='resolves_to' and r['review_status']=='unreviewed'
    with h.sessions() as db:
        start=db.get(DiscoverySubject,r['from_subject_id']);end=db.get(DiscoverySubject,r['to_subject_id'])
        assert (start.kind,start.namespace,start.canonical_value)==('ens_name','ethereum',name)
        assert (end.kind,end.namespace,end.canonical_value)==('blockchain_address','ethereum',ETH)
    assert o['kind']=='name_service_record' and o['verification']=='technical_verified'
    assert snap['primary_name']==name and snap['wallet']==ETH and snap['coin_type']==60
    assert snap['verification']=='forward_verified' and snap['verification_method']=='universal_resolver_reverse'
    assert snap['provider']=='alchemy' and 'confidence' not in snap
    assert counts(h)==before
    g=graph(rpc,row);node=g['items'][0];edge=g['edges'][0]
    assert node['type']=='ens_name' and node['title']==name and node['wallet']==ETH
    assert node['verification']=='forward_verified' and node['current_review_status']=='unreviewed'
    assert node['run_observation_count']==node['current_observation_count']==1 and node['promotion_count']==0
    assert edge['source']==node['id'] and edge['target']==g['root']['id'] and edge['predicate']=='resolves_to'
    assert 'transaction' not in edge and TOKEN not in json.dumps([row,o,g]) and '/v2/' not in json.dumps([row,o,g])
    p=ok(c.get(PREFIX+'/observations/'+o['id']+'/promotion-preview'));assert not p['eligible']

@pytest.mark.parametrize('name',['','alice.eth'])
def test_cache_refresh_expiry_original_time_and_history(rpc,name):
    c,h,_,state,_=rpc;state.body=reply(name)
    first,a=execute(rpc);second,b=execute(rpc)
    assert second['sources'][0]['status']=='cache_hit' and len(state.calls)==1
    assert a==b if not a else a[0]['observation']==b[0]['observation']
    expires=datetime.fromisoformat(first['sources'][0]['expires_at']);completed=datetime.fromisoformat(first['sources'][0]['completed_at'])
    assert 3590<(expires-completed).total_seconds()<=3601
    state.body=reply('alice2.eth');third,changed=execute(rpc,refresh=True)
    assert len(state.calls)==2 and third['status']=='completed'
    if a:
        assert changed[0]['result']['id']!=a[0]['result']['id']
        assert graph(rpc,first)['items'][0]['title']=='alice.eth'
    else:assert graph(rpc,first)['items']==[]
    with h.sessions() as db:
        for source in db.scalars(select(DiscoveryRunSource)):source.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    execute(rpc);assert len(state.calls)==3

@pytest.mark.parametrize('selector,diagnostic',list(ens._REVERTS.items()))
def test_reverts_never_create_positive_or_follow_ccip(rpc,selector,diagnostic):
    c,h,_,state,_=rpc
    state.body={'jsonrpc':'2.0','id':1,'error':{'code':3,'message':'https://private.invalid/'+TOKEN,'data':selector+'00'*64}}
    row,items=execute(rpc)
    assert not items and row['status']=='partial'
    assert row['sources'][0]['quota_snapshot']['diagnostic']==diagnostic
    assert graph(rpc,row)['items']==[] and h.count(DiscoveryObservation)==0
    with h.sessions() as db:assert db.scalar(select(func.count()).select_from(DiscoverySubject).where(DiscoverySubject.kind=='ens_name'))==0
    assert len(state.calls)==1 and TOKEN not in json.dumps(row)
    execute(rpc);assert len(state.calls)==2 # incomplete resolutions are not cached

@pytest.mark.parametrize('name',['ALICE.eth','e\u0301.eth','a b.eth','a\u200b.eth','xn--bcher-kva.eth','a..eth'])
def test_invalid_or_changed_normalization_never_persisted(rpc,name):
    rpc[3].body=reply(name);row,items=execute(rpc)
    assert not items and row['status']=='failed'
    assert row['sources'][0]['quota_snapshot']['diagnostic']=='invalid_ens_name'
    assert rpc[1].count(DiscoveryObservation)==0

@pytest.mark.parametrize('error',['normalizer_unavailable','normalizer_timeout','normalizer_protocol_error'])
def test_normalizer_execution_failure_safe(rpc,monkeypatch,error):
    def fail(_):raise EnsNormalizationError(error)
    monkeypatch.setattr(ens,'normalize_ens_name',fail)
    row,items=execute(rpc);assert not items
    assert row['sources'][0]['quota_snapshot']['diagnostic']==error

@pytest.mark.parametrize('value',[None,{},'0x','0x00','0xgg',encoded_reverse()[:-2],encoded_reverse()+'00'*32,'0x'+'00'*128,'0x'+'ff'*2300])
def test_malformed_abi_safe(rpc,value):
    rpc[3].body={'jsonrpc':'2.0','id':1,'result':value};row,items=execute(rpc)
    assert not items and row['sources'][0]['quota_snapshot']['diagnostic']=='malformed_abi'

@pytest.mark.parametrize('body',[[],{}, {'jsonrpc':'2.0','id':2,'result':'0x'}, {'jsonrpc':'2.0','id':True,'result':'0x'}, {'jsonrpc':'2.0','id':1,'error':{'code':-32000,'message':TOKEN}}, {'jsonrpc':'2.0','id':1,'error':None}, {'jsonrpc':'2.0','id':1,'error':{},'result':'0x'}])
def test_bad_rpc_envelope_safe(rpc,body):
    rpc[3].body=body;row,items=execute(rpc)
    assert not items and row['sources'][0]['error_code']=='invalid_provider_response' and TOKEN not in json.dumps(row)

@pytest.mark.parametrize('status,category',[(429,'rate_limited'),(401,'configuration_unavailable'),(403,'configuration_unavailable'),(500,'transport_failed'),(302,'transport_failed')])
def test_http_failures_no_retry_no_redirect(rpc,status,category):
    rpc[3].status=status;rpc[3].headers={'location':'https://untrusted.invalid/'+TOKEN}
    row,items=execute(rpc);assert not items and row['sources'][0]['error_code']==category and len(rpc[3].calls)==1

@pytest.mark.parametrize('error,category',[(httpx.ReadTimeout(TOKEN),'timeout'),(httpx.ConnectError(TOKEN),'transport_failed')])
def test_transport_failures_safe(rpc,error,category):
    rpc[3].error=error;row,items=execute(rpc)
    assert not items and row['sources'][0]['error_code']==category and TOKEN not in json.dumps(row)

@pytest.mark.parametrize('raw',[b'x'*16385,b'{invalid json',b'\xff'])
def test_bounded_invalid_http_body(rpc,raw):
    rpc[3].raw=raw;row,items=execute(rpc)
    assert not items and row['sources'][0]['error_code']=='invalid_provider_response'

def test_explicit_review_promotion_immutable_history_and_boundaries(rpc):
    c,h,_,state,_=rpc;row,items=execute(rpc);o=observation(rpc,items[0]);r=items[0]['result'];before=counts(h)
    entity=ok(c.post(A+'/entities',json={'canonical_name':'Explicit ENS test entity'}),201)
    claim=ok(c.post(A+'/claims',json={'entity_id':entity['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'operated_by','scope_note':'Explicit test context'}),201)
    baseline=counts(h)
    for status in ['irrelevant','relevant']:
        r=ok(c.get(PREFIX+'/results/'+r['id']))
        ok(c.post(PREFIX+'/results/'+r['id']+'/review',json={'expected_version':r['version'],'observation_id':o['id'],'expected_source_fingerprint':o['content_sha256'],'status':status,'reason':'Explicit test review'}))
        p=ok(c.get(PREFIX+'/observations/'+o['id']+'/promotion-preview'))
        assert p['eligible']==(status=='relevant')
    payload={'result_id':r['id'],'claim_id':claim['id'],'expected_claim_version':claim['version'],'expected_source_fingerprint':p['source_fingerprint'],'link':{'directness':'context','rationale':'Explicit context'}}
    assert c.post(PREFIX+'/observations/'+o['id']+'/promote',json=payload).status_code==422
    payload['link']['stance']='context'
    promoted=ok(c.post(PREFIX+'/observations/'+o['id']+'/promote',json=payload),201)
    assert promoted['claim']['assessment']=='unassessed' and counts(h)==baseline
    capture=ok(c.get(A+'/evidence/'+promoted['promotion']['evidence_id']))
    assert capture['origin']=='public_osint' and capture['metadata_json']['observation']['source_snapshot']==o['source_snapshot']
    assert graph(rpc,row)['items'][0]['promotion_count']==1 and graph(rpc,row)['items'][0]['current_review_status']=='relevant'
    state.body=reply('alice2.eth');new,_=execute(rpc,refresh=True)
    assert graph(rpc,new)['items'][0]['title']=='alice2.eth' and graph(rpc,row)['items'][0]['title']=='alice.eth'
    assert ok(c.get(A+'/evidence/'+capture['id']))==capture and counts(h)==baseline
