"""Real executor/service/API with mocked GitHub and isolated SQLite."""
import json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from sqlalchemy import select,func
from greedy_collector.discovery import github,graphsense as gs
from greedy_collector.discovery.domain import canonical_subject,Conflict
from greedy_collector.discovery import runtime as runtime_module
from greedy_collector.models import DiscoverySubject,DiscoveryRunSource,DiscoveryObservation,Base
from tests.test_discovery_execution import h
from tests.test_discovery_local_manual import live,run,BTC,BECH,counts
from tests.test_discovery_api import ok,PREFIX
from tests.graphsense_fixture import pack,material,search,ETH,REPO

TOKEN='ed9b-only-fixture-token'
A='/api/greedy-collector/attribution'

@pytest.fixture
def remote(live,monkeypatch):
    c,h,runtime=live
    with h.engine.begin() as db:
        db.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)')
        db.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260922_02')")
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN',TOKEN)
    state=SimpleNamespace(calls=[],files=[material(pack())],total=None,incomplete=False,
        status=200,blob_status=200,headers={},blob_headers={},error=None,raw=None)
    def handler(request):
        state.calls.append(request)
        assert request.url.host=='api.github.com' and request.method=='GET'
        assert request.headers['authorization']=='Bearer '+TOKEN
        if state.error:raise state.error
        if request.url.path=='/search/code':
            assert dict(request.url.params)=={'q':'"'+state.wallet+'" repo:'+REPO+' path:packs in:file','per_page':'9','page':'1'}
            return httpx.Response(state.status,json=search([v[0] for v in state.files],state.incomplete,state.total),headers=state.headers)
        assert request.url.path.startswith('/repos/'+REPO+'/git/blobs/') and not request.url.query
        sha=request.url.path.rsplit('/',1)[1]
        value=next(blob for item,blob in state.files if item['sha']==sha)
        return httpx.Response(state.blob_status,**({'json':value} if state.raw is None else {'content':state.raw}),headers=state.blob_headers or state.headers)
    state.wallet=ETH
    actual=httpx.AsyncClient
    monkeypatch.setattr(github,'httpx',SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError))
    return c,h,runtime,state

def execute(remote,**kw):return run(remote[0],transforms=(gs.TRANSFORM_ID,),**kw)
def detail(remote,item):return ok(remote[0].get(PREFIX+'/observations/'+item['observation']['id']))
def graph(remote,row):return ok(remote[0].get(PREFIX+'/runs/'+row['id']+'/graph'))
def unrelated(h):
    with h.sessions() as db:return {n:db.scalar(select(func.count()).select_from(t)) for n,t in Base.metadata.tables.items() if not n.startswith('discovery_')}

def test_capabilities_and_shared_account(remote):
    c,h,runtime,state=remote
    cap=next(t for t in ok(c.get(PREFIX+'/transforms')) if t['id']==gs.TRANSFORM_ID)
    assert cap['implemented'] and cap['executable'] and cap['configured']
    assert cap['cost_class']=='LIMITED_FREE' and cap['chains']==['bitcoin','ethereum']
    assert cap['source_ids']==['github'] and cap['cache_seconds']==86400 and cap['max_requests']==10
    bindings=runtime.executors
    assert bindings.get(gs.TRANSFORM_ID,'github').quota==bindings.get('wallet.public_code_mentions','github').quota
    assert TOKEN not in json.dumps(ok(c.get(PREFIX+'/sources'))) and not state.calls

def test_missing_token_safe(remote,monkeypatch):
    monkeypatch.delenv('DISCOVERY_GITHUB_TOKEN')
    row,items=execute(remote)
    assert not items and not remote[3].calls and row['sources'][0]['error_code']=='configuration_unavailable'

@pytest.mark.parametrize('chain',['bch','solana','litecoin','bsc'])
def test_unsupported_chain_no_transport(remote,chain):
    r=remote[0].post(PREFIX+'/plan',json={'subject':{'chain':chain,'address':ETH},'selections':[{'transform_id':gs.TRANSFORM_ID}]})
    assert r.status_code==422 and not remote[3].calls

@pytest.mark.parametrize('chain,address,published',[('bitcoin',BTC,BTC),('bitcoin',BECH,BECH.upper()),('ethereum',ETH,ETH),('ethereum',ETH,'0x'+ETH[2:].upper())])
def test_exact_api_storage_graph_boundaries(remote,chain,address,published):
    c,h,_,state=remote;state.wallet=address;state.files=[material(pack(published,'BTC' if chain=='bitcoin' else 'ETH'))]
    before=unrelated(h)
    row,items=execute(remote,chain=chain,address=address)
    assert row['status']=='completed' and len(items)==1,(row,items)
    assert row['sources'][0]['requests_attempted']==row['sources'][0]['units_consumed']==2
    result=items[0]['result'];o=detail(remote,items[0]);snapshot=o['source_snapshot']
    assert result['predicate']=='publicly_labeled_as' and result['review_status']=='unreviewed'
    with h.sessions() as db:
        start=db.get(DiscoverySubject,result['from_subject_id']);end=db.get(DiscoverySubject,result['to_subject_id'])
        assert (start.kind,start.namespace,start.canonical_value)==('blockchain_address',chain,address)
        assert (end.kind,end.namespace,end.canonical_value)==('annotation','graphsense','Synthetic service A')
        assert db.scalar(select(func.count()).select_from(DiscoverySubject).where(DiscoverySubject.kind=='blockchain_address'))==1
    assert snapshot['tag']['actor']=='synthetic-actor' and snapshot['tag']['is_cluster_definer'] is True
    assert snapshot['tag']['confidence']=='service_data' and snapshot['blob_sha']==state.files[0][0]['sha']
    assert snapshot['tag']['lastmod']=='2026-09-01' and o['retrieved_at'] and o['origin_label_id'] is None
    assert snapshot['repository']==REPO and snapshot['ref']=='master' and 'tags' not in snapshot['tag']
    g=graph(remote,row);n=g['items'][0];edge=g['edges'][0]
    assert n['type']=='public_annotation' and n['public_annotation']==snapshot and n['promotion_count']==0
    assert edge['source']==g['root']['id'] and edge['target']==n['id'] and edge['predicate']=='publicly_labeled_as'
    assert unrelated(h)==before and TOKEN not in json.dumps([row,o,g])

@pytest.mark.parametrize('change',['substring','suffix','prose','base58_case','BCH','LTC','SOL','BSC','network','transaction'])
def test_non_matches_do_not_become_annotations(remote,change):
    state=remote[3];p=pack()
    if change=='substring':p['tags']=[{'address':ETH[:-2]}]
    elif change=='suffix':p['tags']=[{'address':ETH+'ab'}]
    elif change=='prose':p['description']=ETH;p['tags']=[{'address':'0x'+'cd'*20}]
    elif change=='base58_case':state.wallet=BTC;p=pack(BTC.swapcase(),'BTC')
    elif change in ('BCH','LTC','SOL','BSC'):p['currency']=change
    elif change=='network':p['network']='BSC'
    else:p['tx_hash']='0x'+'11'*32
    state.files=[material(p)];row,items=execute(remote,chain='bitcoin' if change=='base58_case' else 'ethereum',address=state.wallet)
    assert row['status']=='completed' and not items and graph(remote,row)['items']==[]

def test_header_inheritance_override_and_optional_metadata(remote):
    p=pack();p['tags']=[{'address':ETH,'label':'Per-address label','category':'service','confidence':'forensic','source':'Public document reference','currency':'ETH'}]
    p.pop('actor');p.pop('is_cluster_definer');remote[3].files=[material(p)]
    _,items=execute(remote);tag=detail(remote,items[0])['source_snapshot']['tag']
    assert tag['label']=='Per-address label' and tag['category']=='service' and tag['confidence']=='forensic'
    assert tag['creator']=='Test publisher' and tag['source']=='Public document reference'
    assert 'actor' not in tag and 'is_cluster_definer' not in tag and 'source_url' not in tag

def test_conflicting_packs_duplicate_tags_same_actor_no_merge(remote):
    p=pack();p['tags']=[{'address':ETH},{'address':ETH}]
    remote[3].files=[material(p,'packs/a.yaml'),material(pack(label='Synthetic service B'),'packs/b.yaml'),material(p,'packs/c.yaml')]
    before=unrelated(remote[1]);row,items=execute(remote)
    assert len(items)==3 and len({i['result']['id'] for i in items})==3
    g=graph(remote,row);assert len(g['items'])==len(g['edges'])==3
    assert {n['title'] for n in g['items']}=={'Synthetic service A','Synthetic service B'}
    assert all(e['source']==g['root']['id'] for e in g['edges']) and unrelated(remote[1])==before

@pytest.mark.parametrize('content',[b'!bad',b'!!python/object/apply:os.system [echo forbidden]',b'header: !include ../header.yaml\ntags: []',b'tags: [',b'a: &a [*a]',b'title: first\ntitle: second\ntags: []',b'[]',b'\xff',b'tags: data.csv',b'x: '+b'['*30+b'0'+b']'*30])
def test_unsafe_unsupported_yaml_partial_no_positive(remote,content):
    remote[3].files=[material(content)]
    row,items=execute(remote);assert row['status']=='partial' and not items
    assert row['sources'][0]['coverage']=='provider_incomplete' and len(remote[3].calls)==2

@pytest.mark.parametrize('change',['private','other_repo','traversal','outside_packs','symlink_extension','unsafe_source','secret','duplicate_key','oversize','bad_sha','wrong_size','bad_base64'])
def test_trusted_boundary_and_invalid_material(remote,change):
    item,blob=remote[3].files[0]
    if change=='private':item['repository']['private']=True
    elif change=='other_repo':item['repository']['full_name']='other/repo'
    elif change=='traversal':item['path']='packs/../outside.yaml'
    elif change=='outside_packs':item['path']='actors/actor.yaml'
    elif change=='symlink_extension':item['path']='packs/tags.txt'
    elif change=='unsafe_source':remote[3].files=[material(pack(source='https://user:pass@source.example.test/'))]
    elif change=='secret':remote[3].files=[material(pack(actor=TOKEN))]
    elif change=='duplicate_key':remote[3].files=[material(b'title: first\ntitle: second\ntags: []')]
    elif change=='oversize':blob['size']=gs.FILE_BYTES+1
    elif change=='bad_sha':blob['content']='YWJj';blob['size']=3
    elif change=='wrong_size':blob['size']=1
    else:blob['content']='%%%'
    row,items=execute(remote);assert row['status']=='partial' and not items and TOKEN not in json.dumps(row)
    assert len(remote[3].calls)==(1 if change in ('private','other_repo','traversal','outside_packs','symlink_extension') else 2)

def test_file_count_and_result_bounds(remote):
    remote[3].files=[material(pack(label='Test '+str(i)),'packs/'+str(i)+'.yaml') for i in range(9)]
    remote[3].total=20
    row,items=execute(remote,maximum=2)
    assert row['status']=='partial' and len(items)==2 and row['sources'][0]['coverage']=='limit_reached'
    assert len(remote[3].calls)<=10 and row['sources'][0]['provider_total']==20

def test_aggregate_content_bound(remote):
    remote[3].files=[material(pack(description='x'*220000),'packs/'+str(i)+'.yaml') for i in range(6)]
    row,items=execute(remote)
    assert row['status']=='partial' and len(items)==4 and len(remote[3].calls)==6

def test_cache_second_run_minute_rollover_conflict(remote,monkeypatch):
    """Reproduce the second-run 409 without sleeps or shared fixture state."""
    c,h,runtime,_=remote
    instant=datetime.now(timezone.utc).replace(second=59,microsecond=999999)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return instant if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(runtime_module,'datetime',Clock)
    remote[3].files=[]
    first,_=execute(remote)
    assert first['status']=='completed'
    assert all(task.done() for task in runtime._tasks.values())
    data={'subject':{'chain':'ethereum','address':ETH},
          'selections':[{'transform_id':gs.TRANSFORM_ID}],'refresh':False}
    planned=ok(c.post(PREFIX+'/plan',json=data))
    reasons=[]
    original=runtime.create_and_execute_run
    async def capture(*args,**kwargs):
        try:return await original(*args,**kwargs)
        except Conflict as exc:
            reasons.append(str(exc))
            raise
    monkeypatch.setattr(runtime,'create_and_execute_run',capture)
    instant+=timedelta(microseconds=1)
    response=c.post(PREFIX+'/runs',json={**data,'expected_plan_fingerprint':planned['fingerprint']})
    assert response.status_code==409
    assert reasons==['Plan changed or expired; plan again']
    with h.sessions() as db:
        from greedy_collector.models import DiscoveryRun
        assert db.scalar(select(func.count()).select_from(DiscoveryRun))==1
    # The same intent succeeds with a fresh plan; the empty cache is still valid.
    second,_=execute(remote)
    assert second['sources'][0]['status']=='cache_hit'


@pytest.fixture
def stable_plan_clock(remote,monkeypatch):
    """Cache/history assertions must not depend on a wall-clock minute boundary.

    Freeze only planning; retrieval, cache TTLs and executor deadlines retain
    their real clocks. The separate rollover test exercises plan expiration.
    """
    instant=datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return instant if tz else instant.replace(tzinfo=None)
    runtime=remote[2]
    original=runtime.plan
    def plan(*args,**kwargs):
        with patch.object(runtime_module,'datetime',Clock):
            return original(*args,**kwargs)
    monkeypatch.setattr(runtime,'plan',plan)


@pytest.mark.parametrize('empty',[False,True])
def test_cache_refresh_immutable_material_and_history(remote,empty,stable_plan_clock):
    c,h,_,state=remote
    if empty:state.files=[]
    first,a=execute(remote);second,b=execute(remote)
    assert second['sources'][0]['status']=='cache_hit' and len(state.calls)==(1 if empty else 2)
    seconds=(datetime.fromisoformat(first['sources'][0]['expires_at'])-datetime.fromisoformat(first['sources'][0]['completed_at'])).total_seconds()
    assert abs(seconds-(3600 if empty else 86400))<2
    original=detail(remote,a[0]) if a else None
    state.files=[material(pack(confidence='forensic'))]
    third,new=execute(remote,refresh=True)
    assert third['status']=='completed' and len(state.calls)==(3 if empty else 4)
    if a:
        assert new[0]['result']['id']==a[0]['result']['id'] and new[0]['observation']['id']!=a[0]['observation']['id']
        assert detail(remote,a[0])==original and graph(remote,first)['items'][0]['public_annotation']['tag']['confidence']=='service_data'
    else:assert graph(remote,first)['items']==[]

@pytest.mark.parametrize('status,error',[(401,'configuration_unavailable'),(403,'entitlement_unavailable'),(429,'rate_limited'),(500,'transport_failed'),(302,'invalid_provider_response')])
def test_search_errors_no_retry(remote,status,error):
    remote[3].status=status
    row,items=execute(remote)
    assert not items and row['sources'][0]['error_code']==error and len(remote[3].calls)==1

def test_secondary_rate_limit_shared_with_generic_code(remote):
    remote[3].blob_status=429
    row,items=execute(remote)
    assert row['status']=='partial' and not items and row['sources'][0]['retry_after_at']
    later,_=run(remote[0],transforms=('wallet.public_code_mentions',),refresh=True)
    assert later['sources'][0]['error_code']=='rate_limited' and len(remote[3].calls)==2

def test_search_quota_zero_stops_before_blob(remote):
    remote[3].headers={'x-ratelimit-remaining':'0','x-ratelimit-reset':str(int(datetime.now(timezone.utc).timestamp())+120),'x-ratelimit-resource':'code_search'}
    row,items=execute(remote)
    assert not items and row['status']=='partial' and len(remote[3].calls)==1 and row['sources'][0]['retry_after_at']

def test_incomplete_search_retains_exact_positive(remote):
    remote[3].incomplete=True;row,items=execute(remote)
    assert len(items)==1 and row['status']=='partial' and row['sources'][0]['coverage']=='provider_incomplete'

def test_relevant_explicit_context_promotion_immutable_refresh(remote):
    c,h,_,state=remote;row,items=execute(remote);o=detail(remote,items[0]);r=items[0]['result']
    p=ok(c.get(PREFIX+'/observations/'+o['id']+'/promotion-preview'));assert not p['eligible']
    entity=ok(c.post(A+'/entities',json={'canonical_name':'Explicit ED9B test entity'}),201)
    claim=ok(c.post(A+'/claims',json={'entity_id':entity['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'operated_by','scope_note':'Analyst-selected context'}),201)
    baseline=unrelated(h)
    for status in ['irrelevant','relevant']:
        r=ok(c.get(PREFIX+'/results/'+r['id']))
        ok(c.post(PREFIX+'/results/'+r['id']+'/review',json={'expected_version':r['version'],'observation_id':o['id'],'expected_source_fingerprint':o['content_sha256'],'status':status,'reason':'Explicit review'}))
        p=ok(c.get(PREFIX+'/observations/'+o['id']+'/promotion-preview'));assert p['eligible']==(status=='relevant')
    payload={'result_id':r['id'],'claim_id':claim['id'],'expected_claim_version':claim['version'],'expected_source_fingerprint':p['source_fingerprint'],'link':{'directness':'context','rationale':'Public annotation context'}}
    assert c.post(PREFIX+'/observations/'+o['id']+'/promote',json=payload).status_code==422
    payload['link']['stance']='context'
    saved=ok(c.post(PREFIX+'/observations/'+o['id']+'/promote',json=payload),201)
    assert saved['claim']['assessment']=='unassessed'
    capture=ok(c.get(A+'/evidence/'+saved['promotion']['evidence_id']))
    assert capture['origin']=='public_osint' and capture['metadata_json']['observation']['source_snapshot']==o['source_snapshot']
    state.files=[material(pack(confidence='forensic'))]
    changed,new=execute(remote,refresh=True)
    assert new[0]['result']['new_material_since_review']
    assert not ok(c.get(PREFIX+'/observations/'+new[0]['observation']['id']+'/promotion-preview'))['eligible']
    assert ok(c.get(PREFIX+'/observations/'+o['id']+'/promotion-preview'))['eligible']
    assert ok(c.get(A+'/evidence/'+capture['id']))==capture and detail(remote,items[0])==o
    assert graph(remote,row)['items'][0]['public_annotation']==o['source_snapshot']
    after=unrelated(h)
    for table in baseline:
        if table not in ('attribution_evidence','attribution_claim_evidence','attribution_events'):assert after[table]==baseline[table],table

@pytest.mark.parametrize('raw',[b'x'*(gs.FILE_BYTES*4//3+16385),b'{broken',b'\xff'],ids=['oversized','bad_json','invalid_utf8'])
def test_http_file_stream_limit_and_bad_json(remote,raw):
    remote[3].raw=raw;row,items=execute(remote)
    assert not items and row['status']=='partial' and len(remote[3].calls)==2

@pytest.mark.parametrize('error,category',[(httpx.ReadTimeout(TOKEN),'timeout'),(httpx.ConnectError(TOKEN),'transport_failed')])
def test_search_transport_failure_closed(remote,error,category):
    remote[3].error=error;row,items=execute(remote)
    assert not items and row['sources'][0]['error_code']==category and TOKEN not in json.dumps(row)

def test_resource_headers_retained_and_shared_local_rate(remote):
    state=remote[3];state.headers={'x-ratelimit-resource':'code_search','x-ratelimit-remaining':'7','x-ratelimit-limit':'10'}
    state.blob_headers={'x-ratelimit-resource':'core','x-ratelimit-remaining':'100','x-ratelimit-limit':'5000'}
    row,_=execute(remote);resources=row['sources'][0]['quota_snapshot']['github_resources']
    assert resources['code_search']['remaining']==7 and resources['core']['remaining']==100
    with remote[1].sessions() as db:
        source=db.scalar(select(DiscoveryRunSource));assert source.quota_bucket=='github:1'
        # Simulate this same account's preceding test-only requests in its ledger.
        source.attempt_log=source.attempt_log*5;db.commit()
    next_row,items=run(remote[0],transforms=('wallet.public_code_mentions',),refresh=True)
    assert not items and next_row['sources'][0]['error_code']=='rate_limited' and len(state.calls)==2

@pytest.mark.parametrize('override',[{'network':'BSC'},{'currency':'BCH'},{'currency':'BSC','network':'ETH'}])
def test_per_tag_network_currency_override_cannot_inherit_eth(remote,override):
    remote[3].files=[material(pack(network='ETH',tags=[{'address':ETH,**override}]))]
    row,items=execute(remote);assert not items and row['status']=='completed'

def test_empty_optional_fields_and_yaml_timestamp(remote):
    p=pack();p['lastmod']=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
    for key in ('confidence','actor','category','is_cluster_definer'):p.pop(key)
    remote[3].files=[material(p)];_,items=execute(remote)
    tag=detail(remote,items[0])['source_snapshot']['tag']
    assert tag['lastmod']=='2026-09-01T12:00:00+00:00' and 'confidence' not in tag

def test_maximum_retained_metadata_is_promotable(remote):
    p=pack(label='L'*255,title='T'*255,creator='C'*255,actor='A'*255,category='B'*255,
           source='https://source.example.test/'+('s'*1950),concepts=[str(i)+'c'*250 for i in range(20)])
    remote[3].files=[material(p)];row,items=execute(remote)
    assert row['status']=='completed' and len(items)==1
    o=detail(remote,items[0]);preview=ok(remote[0].get(PREFIX+'/observations/'+o['id']+'/promotion-preview'))
    assert preview['evidence']['metadata_json']['observation']['source_snapshot']['tag']['concepts']==sorted(p['concepts'])

def test_cache_expiry_causes_real_executor_request(remote):
    first,_=execute(remote)
    with remote[1].sessions() as db:
        source=db.scalar(select(DiscoveryRunSource));source.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    row,_=execute(remote);assert row['sources'][0]['status']=='succeeded' and len(remote[3].calls)==4

def test_expanded_inherited_metadata_returns_bounded_partial_batch(remote):
    p=pack(source='https://source.example.test/'+('s'*1950),concepts=[str(i)+'c'*250 for i in range(20)],
           tags=[{'address':ETH,'label':'Published test label '+str(i)} for i in range(100)])
    remote[3].files=[material(p)]
    row,items=execute(remote)
    assert row['status']=='partial' and row['sources'][0]['coverage']=='limit_reached'
    assert 1<len(items)<=row['sources'][0]['returned_count']<100 and len(remote[3].calls)==2

def test_exhausted_headers_without_reset_still_delay_shared_account(remote):
    remote[3].headers={'x-ratelimit-resource':'code_search','x-ratelimit-remaining':'0'}
    row,items=execute(remote)
    assert not items and row['sources'][0]['retry_after_at'] and len(remote[3].calls)==1

@pytest.mark.parametrize('label',['line\nbreak','tab\tlabel'])
def test_unsupported_annotation_text_does_not_discard_other_packs(remote,label):
    remote[3].files=[material(pack(label=label),'packs/a.yaml'),material(pack(),'packs/b.yaml')]
    row,items=execute(remote)
    assert row['status']=='partial' and len(items)==1
    assert detail(remote,items[0])['source_snapshot']['tag']['label']=='Synthetic service A'
