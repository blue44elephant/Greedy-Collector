"""ED-4B real executor + isolated service/API storage; never live GitHub."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from greedy_collector.discovery import github
from greedy_collector.discovery.executors import ExecutionContext, ExecutionSignal
from greedy_collector.discovery.domain import canonical_subject, query_fingerprint
from greedy_collector.discovery.registry import REGISTRY
from greedy_collector.models import DiscoveryObservation, DiscoveryResult
from tests.test_discovery_local_manual import live, run, counts, label, BTC, BECH
from tests.test_discovery_execution import h, ETH
from tests.test_discovery_api import ok, PREFIX
from tests.test_config_startup import isolated_app, run_python

TOKEN = 'ed4b-test-only-token'


@pytest.mark.parametrize('value',[None,'test-only-process-token',''])
def test_github_dotenv_and_process_precedence(isolated_app,value):
    project,_,env=isolated_app
    env.pop('DISCOVERY_GITHUB_TOKEN',None)
    (project/'.env').write_text('DISCOVERY_GITHUB_TOKEN=test-only-file-token\n',encoding='utf8')
    expected='test-only-file-token' if value is None else value
    result=run_python(isolated_app, '''
import os
from greedy_collector.config import get_settings
from greedy_collector.discovery.registry import REGISTRY
get_settings()
assert os.environ['DISCOVERY_GITHUB_TOKEN']==os.environ['EXPECTED_TEST_VALUE']
source=next(s for s in REGISTRY.capabilities()['sources'] if s['id']=='github')
assert source['configured']==bool(os.environ['EXPECTED_TEST_VALUE'])
''', {'EXPECTED_TEST_VALUE':expected,**({'DISCOVERY_GITHUB_TOKEN':value} if value is not None else {})})
    assert expected not in result.stdout+result.stderr if expected else not result.stdout


def hit(address=ETH, rid=123, path='README.md', fragment=None, **extra):
    return {'repository': {'id': rid, 'full_name': f'test/repo-{rid}', 'html_url': f'https://github.com/test/repo-{rid}', 'private': False, 'visibility': 'public', 'fork': False},
        'name': path.split('/')[-1], 'path': path, 'sha': 'a'*40,
        'html_url': f'https://github.com/test/repo-{rid}/blob/main/{path}', 'score': 2.5,
        'text_matches': [{'property': 'content', 'fragment': fragment if fragment is not None else 'wallet = "'+address+'";', 'matches': [{'text': address, 'indices': [10, 10+len(address)]}]}], **extra}


def response(items=None, total=None, incomplete=False):
    items = [hit()] if items is None else items
    return {'total_count': len(items) if total is None else total, 'incomplete_results': incomplete, 'items': items}


@pytest.fixture
def transport(live, monkeypatch):
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN', TOKEN)
    state = SimpleNamespace(calls=[], status=200, body=response(), headers={'x-ratelimit-remaining': '9', 'x-ratelimit-limit': '10', 'x-ratelimit-resource': 'code_search'}, error=None)
    def handler(request):
        state.calls.append(request)
        assert request.url.host == 'api.github.com' and request.url.path == '/search/code'
        if state.error: raise state.error
        return httpx.Response(state.status, json=state.body, headers=state.headers)
    actual = httpx.AsyncClient
    monkeypatch.setattr(github, 'httpx', SimpleNamespace(AsyncClient=lambda **kw: actual(transport=httpx.MockTransport(handler), **kw), TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError))
    return (*live, state)


def execute(value, **kw):
    client, _, _, state = value
    row, items = run(client, transforms=('wallet.public_code_mentions',), **kw)
    return row, items


def detail(client, item):
    return ok(client.get(PREFIX+'/observations/'+item['observation']['id']))


def test_missing_token_is_implemented_but_unavailable(live, monkeypatch):
    client, h, _ = live
    monkeypatch.delenv('DISCOVERY_GITHUB_TOKEN', raising=False)
    capability = next(t for t in ok(client.get(PREFIX+'/transforms')) if t['id']=='wallet.public_code_mentions')
    assert capability['implemented'] and not capability['configured'] and not capability['executable']
    row, items = run(client, transforms=('wallet.public_code_mentions',))
    assert not items and row['sources'][0]['requests_attempted']==0
    assert row['sources'][0]['error_code']=='configuration_unavailable'
    assert h.count(DiscoveryObservation)==0


@pytest.mark.parametrize('chain,address,query', [('ethereum', ' '+ETH.upper().replace('0X','0x')+' ', ETH), ('bitcoin', BTC, BTC), ('bitcoin', BECH.upper(), BECH)])
def test_real_api_exact_public_mention(transport, chain, address, query):
    client, h, runtime, state = transport
    state.body=response([hit(query)])
    before=counts(h)
    row, items=execute(transport, chain=chain, address=address)
    assert row['status']=='completed' and len(items)==1 and counts(h)==before
    request=state.calls[0]
    assert request.method=='GET' and dict(request.url.params)=={'q':'"'+query+'" in:file','per_page':'30','page':'1'}
    assert request.headers['authorization']=='Bearer '+TOKEN
    assert request.headers['accept']=='application/vnd.github.text-match+json'
    assert request.headers['x-github-api-version']==github.API_VERSION
    result=items[0]['result']; observation=detail(client,items[0])
    assert result['predicate']=='repository_contains' and result['fact_key']=={'path':'README.md'}
    assert observation['verification']=='exact_in_excerpt' and observation['match_context']['matched_wallet']==query
    assert query.lower() in observation['excerpt'].lower() and observation['excerpt_complete'] is False
    snapshot=observation['source_snapshot']
    assert snapshot['public'] is True and snapshot['blob_sha']=='a'*40 and snapshot['github_search_score']==2.5
    assert observation['retrieved_at'] and observation['observed_at'] is None
    assert TOKEN not in json.dumps([row,items,observation])
    assert row['sources'][0]['requests_attempted']==row['sources'][0]['units_consumed']==1
    assert row['sources'][0]['quota_snapshot']['resource']=='code_search'
    assert row['sources'][0]['quota_snapshot']['limit']==10


@pytest.mark.parametrize('fragment', ['0xabab...abab', ETH[:12], ETH[-12:], 'x'+ETH, ETH+'0', '_'+ETH, ETH+'_', 'é'+ETH, 'no wallet', ETH[:20]+'\n'+ETH[20:]])
def test_partial_and_substring_hits_are_omitted(transport, fragment):
    transport[3].body=response([hit(fragment=fragment)])
    row, items=execute(transport)
    assert row['status']=='completed' and not items


@pytest.mark.parametrize('change', ['private','missing_public','internal','string_false','path_match','no_fragment','missing_repo','unsafe_url','different_repo_url'])
def test_public_metadata_and_context_gate(transport, change):
    value=hit()
    if change=='private':value['repository']['private']=True
    if change=='missing_public':value['repository'].pop('private')
    if change=='internal':value['repository']['visibility']='internal'
    if change=='string_false':value['repository']['private']='false'
    if change=='path_match':value['text_matches'][0]['property']='path'
    if change=='no_fragment':value.pop('text_matches')
    if change=='missing_repo':value.pop('repository')
    if change=='unsafe_url':value['html_url']='https://github.com/test/repo-123/blob/main/README.md?token='+TOKEN
    if change=='different_repo_url':value['html_url']='https://github.com/another/repo/blob/main/README.md'
    transport[3].body=response([value])
    row, items=execute(transport)
    assert row['status']=='completed' and not items and len(transport[3].calls)==1


def test_base58_case_is_not_folded(transport):
    transport[3].body=response([hit(BTC.lower())])
    _,items=execute(transport,chain='bitcoin',address=BTC)
    assert not items


def test_bech32_unicode_lookalike_is_not_a_wallet_match(transport):
    transport[3].body=response([hit(BECH.replace('k','\u212a'))])
    _,items=execute(transport,chain='bitcoin',address=BECH)
    assert not items


def test_trimmed_configured_credential_is_redacted(transport,monkeypatch):
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN',' '+TOKEN+' ')
    transport[3].body=response([hit(fragment=ETH+' '+TOKEN)])
    row,items=execute(transport)
    assert len(items)==1 and TOKEN not in json.dumps(detail(transport[0],items[0]))
    assert transport[3].calls[0].headers['authorization']=='Bearer '+TOKEN


def test_eth_case_and_bounded_sanitized_context(transport):
    transport[3].body=response([hit(fragment='x'*2000+' "'+ETH.upper()+'" api_key=unrelated-test-secret '+TOKEN+' '+'y'*2000)])
    row,items=execute(transport)
    observation=detail(transport[0],items[0])
    assert len(observation['excerpt'])<=1000 and '[redacted]' in observation['excerpt']
    assert TOKEN not in json.dumps(observation) and 'unrelated-test-secret' not in json.dumps(observation)
    match=observation['match_context']
    assert observation['excerpt'][match['excerpt_start']:match['excerpt_end']]==ETH.upper()


def test_deduplicate_file_keep_other_locations_and_forks(transport):
    values=[hit(),hit(),hit(path='src/wallet.py'),hit(rid=456)]
    values[-1]['repository']['fork']=True
    transport[3].body=response(values)
    _,items=execute(transport)
    assert len(items)==3 and len({i['result']['id'] for i in items})==3


@pytest.mark.parametrize('incomplete,total,coverage', [(True,1,'provider_incomplete'),(False,100,'limit_reached'),(False,1,'bounded')])
def test_coverage_and_one_request_cap(transport,incomplete,total,coverage):
    transport[3].body=response(total=total,incomplete=incomplete)
    row,items=execute(transport,maximum=2)
    assert row['sources'][0]['coverage']==coverage and len(transport[3].calls)==1
    assert detail(transport[0],items[0])['source_snapshot']['incomplete_results']==incomplete
    if coverage!='bounded':
        execute(transport,maximum=2)
        assert len(transport[3].calls)==2


@pytest.mark.parametrize('status,headers,body,category', [
    (401,{}, {'message':TOKEN},'configuration_unavailable'),
    (403,{}, {'message':'access denied '+TOKEN},'entitlement_unavailable'),
    (403,{'x-ratelimit-remaining':'0','x-ratelimit-reset':'1999999999'}, {},'rate_limited'),
    (403,{}, {'message':'You have exceeded a secondary rate limit. '+TOKEN},'rate_limited'),
    (403,{'retry-after':'60'}, {},'rate_limited'),
    (429,{'retry-after':'60'}, {},'rate_limited'),
    (422,{}, {'message':TOKEN},'invalid_provider_response'),
    (500,{}, {'message':TOKEN},'transport_failed'),
    (503,{}, {},'transport_failed'),
    (302,{'location':'https://example.invalid/?token='+TOKEN},{},'invalid_provider_response')])
def test_error_mapping_and_no_retry_or_secret(transport,status,headers,body,category):
    state=transport[3];state.status=status;state.headers=headers;state.body=body
    row,items=execute(transport)
    assert row['status']=='failed' and not items and len(state.calls)==1
    assert row['sources'][0]['error_code']==category and TOKEN not in json.dumps(row)
    if category=='rate_limited':
        assert row['sources'][0]['retry_after_at']
        execute(transport,refresh=True)
        assert len(state.calls)==1


@pytest.mark.parametrize('error,category',[(httpx.ReadTimeout(TOKEN),'timeout'),(httpx.ConnectError(TOKEN),'transport_failed')])
def test_network_errors_are_safe(transport,error,category):
    transport[3].error=error
    row,items=execute(transport)
    assert not items and row['sources'][0]['error_code']==category and TOKEN not in json.dumps(row)


@pytest.mark.parametrize('bad', [[],{}, {'items':[],'total_count':True,'incomplete_results':False}, {'items':'bad','total_count':1,'incomplete_results':False}, {'items':[None],'total_count':1,'incomplete_results':False}, response([hit()]*31), response([hit()],total=0), {'items':[],'total_count':0,'incomplete_results':'false'}])
def test_malformed_provider_batches_are_atomic(transport,bad):
    transport[3].body=bad
    row,items=execute(transport)
    assert row['status']=='failed' and not items and transport[1].count(DiscoveryObservation)==0


def test_oversize_response_is_rejected(transport):
    transport[3].body=response([hit(fragment='x'*(github.MAX_BYTES+1))])
    row,items=execute(transport)
    assert not items and row['sources'][0]['error_code']=='invalid_provider_response'


def test_cache_refresh_score_and_changed_material_review(transport):
    client,h,_,state=transport
    first,items=execute(transport); old=detail(client,items[0]);result=items[0]['result']
    ok(client.post(PREFIX+'/results/'+result['id']+'/review',json={'expected_version':result['version'],'observation_id':old['id'],'expected_source_fingerprint':old['content_sha256'],'status':'relevant','reason':'Test relevance only'}))
    cached,cached_items=execute(transport)
    assert cached['sources'][0]['status']=='cache_hit' and cached['sources'][0]['requests_attempted']==0 and len(state.calls)==1
    assert cached_items[0]['observation']['id']==old['id']
    state.body['items'][0]['score']=99
    _,same=execute(transport,refresh=True)
    assert same[0]['result']['id']==result['id'] and not same[0]['result']['new_material_since_review']
    assert h.count(DiscoveryObservation)==2
    assert detail(client,same[0])['content_sha256']==old['content_sha256']
    assert detail(client,same[0])['source_snapshot']['github_search_score']==99
    state.body['items'][0]['text_matches'][0]['fragment']='Changed context "'+ETH+'"'
    _,changed=execute(transport,refresh=True)
    assert changed[0]['result']['id']==result['id'] and changed[0]['result']['new_material_since_review']
    assert h.count(DiscoveryObservation)==3 and detail(client,items[0])==old
    assert len(state.calls)==3


def test_empty_result_cache_and_no_claims(transport):
    transport[3].body=response([])
    before=counts(transport[1]);first,items=execute(transport);second,_=execute(transport)
    assert not items and first['status']=='completed' and second['sources'][0]['status']=='cache_hit'
    assert len(transport[3].calls)==1 and counts(transport[1])==before


def test_sha_change_and_disappeared_file_preserve_history(transport):
    client,h,_,state=transport
    _,items=execute(transport);old=detail(client,items[0])
    state.body['items'][0]['sha']='c'*40
    _,changed=execute(transport,refresh=True)
    assert changed[0]['result']['id']==items[0]['result']['id']
    assert detail(client,changed[0])['content_sha256']!=old['content_sha256']
    state.body=response([])
    _,empty=execute(transport,refresh=True)
    assert not empty and h.count(DiscoveryResult)==1 and h.count(DiscoveryObservation)==2
    assert detail(client,items[0])==old


@pytest.mark.parametrize('empty,seconds',[(False,86400),(True,3600)])
def test_cache_ttl_is_bounded(transport,empty,seconds):
    from sqlalchemy import select
    from greedy_collector.models import DiscoveryRunSource
    transport[3].body=response([] if empty else [hit()])
    row,_=execute(transport)
    with transport[1].sessions() as db:
        source=db.scalar(select(DiscoveryRunSource).where(DiscoveryRunSource.run_id==row['id']))
        assert (source.expires_at-source.completed_at).total_seconds()==seconds


def test_query_cache_isolates_subject_limit_version(transport):
    execute(transport)
    execute(transport,maximum=5)
    assert len(transport[3].calls)==2
    subj=canonical_subject('blockchain_address','ethereum',ETH)
    transform,source=REGISTRY.pair('wallet.public_code_mentions','github')
    key=query_fingerprint(subj,transform,source,{'max_results':30})
    assert key!=query_fingerprint(subj,transform.model_copy(update={'version':2}),source,{'max_results':30})
    assert key!=query_fingerprint(canonical_subject('blockchain_address','bitcoin',BTC),transform,source,{'max_results':30})


def test_budget_and_result_limit_prevent_http(transport):
    client,_,_,state=transport
    data={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.public_code_mentions','parameters':{'max_results':31}}]}
    assert client.post(PREFIX+'/plan',json=data).status_code==422
    data['selections'][0].pop('parameters');data['budget']={'allow_limited_free':False}
    plan=ok(client.post(PREFIX+'/plan',json=data))
    assert plan['selections'][0]['eligibility']=='budget_exhausted' and not state.calls


def test_real_executor_cancels_inflight(transport):
    client,_,runtime,state=transport
    from greedy_collector.discovery import schemas
    async def scenario():
        gate=asyncio.Event();entered=asyncio.Event()
        actual=httpx.AsyncClient
        async def handler(request):
            entered.set();await gate.wait()
            return httpx.Response(200,json=response())
        previous=github.httpx
        github.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)
        try:
            data={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.public_code_mentions'}]}
            plan,_=runtime.plan(schemas.PlanRequest(**data))
            row=await runtime.create_and_execute_run(schemas.RunCreate(**data,expected_plan_fingerprint=plan.fingerprint))
            await asyncio.wait_for(entered.wait(),2)
            task=runtime._tasks[row['id']]
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            assert transport[1].count(DiscoveryObservation)==0
            with runtime.service() as svc:
                current=svc.read_run(row['id'])
                assert current['sources'][0]['requests_attempted']==1
        finally:github.httpx=previous
    client.portal.call(scenario)


def test_local_success_survives_github_failure(transport):
    client,h,_,state=transport;label(client);before=counts(h);state.status=503
    row,items=run(client,transforms=('wallet.local_labels','wallet.public_code_mentions'))
    assert row['status']=='partial' and len(items)==1 and counts(h)==before


def test_retry_after_survives_application_session_reload(transport):
    from sqlalchemy.orm import sessionmaker
    client,h,runtime,state=transport
    h.sessions=sessionmaker(h.engine,autoflush=False,expire_on_commit=False)
    runtime.sessions=h.sessions
    state.status=429;state.headers={'retry-after':'60'}
    first,_=execute(transport)
    assert first['sources'][0]['retry_after_at']
    second,_=run(client,transforms=('wallet.local_labels','wallet.public_code_mentions'),refresh=True)
    source=next(s for s in second['sources'] if s['source_id']=='github')
    assert source['status']=='rate_limited' and source['requests_attempted']==0
    assert source['retry_after_at'] and len(state.calls)==1


def test_open_plan_routes_do_not_issue_github_search(transport):
    client,_,_,state=transport
    for path in ['/','/health','/docs','/openapi.json','/static/js/discovery.js','/static/app.css',PREFIX+'/sources',PREFIX+'/transforms',PREFIX+'/runs']:
        assert client.get(path).status_code==200,path
    plan={'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.public_code_mentions'}]}
    output=ok(client.post(PREFIX+'/plan',json=plan))
    assert output['selections'][0]['eligibility']=='eligible' and not state.calls
    assert TOKEN not in json.dumps(output)


def test_cancellation_before_charge():
    event=asyncio.Event();event.set();charges=[]
    context=ExecutionContext(canonical_subject('blockchain_address','ethereum',ETH),{'max_results':30},'github',datetime.now(timezone.utc)+timedelta(seconds=30),event,charges.append)
    async def scenario():
        with pytest.raises(asyncio.CancelledError):await context.request(lambda:None)
    asyncio.run(scenario());assert not charges


def test_quota_headers_allowlist_and_bad_values():
    headers=httpx.Headers({'x-ratelimit-remaining':'garbage','x-ratelimit-limit':'-1','x-ratelimit-resource':TOKEN,'retry-after':'bad','x-ratelimit-reset':'9999999999999999','authorization':TOKEN})
    assert github.quota_headers(headers)=={}
    quota=github.quota_headers(httpx.Headers({'retry-after':'Fri, 01 Jan 2027 00:00:00 GMT'}))
    assert quota['retry_after_at']==datetime(2027,1,1,tzinfo=timezone.utc)


def test_frontend_github_contract_and_runtime_not_fixtures():
    root=Path(__file__).resolve().parents[1]
    js=(root/'static/js/discovery.js').read_text(encoding='utf8')
    for text in ['Open on GitHub','Matched code context','GitHub search score','Matched full wallet','repository_full_name','file_path']:
        assert text in js
    source=(root/'greedy_collector/discovery/github.py').read_text(encoding='utf8')
    for prohibited in ['sampleWallet','fakeGraph','demoNodes','mockTransactions','cannedSearch','MockTransport','from tests']:
        assert prohibited not in source+js
