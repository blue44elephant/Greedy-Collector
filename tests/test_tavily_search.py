"""OSINT-2A: fixed-host mocked Tavily through the real migrated API/runtime."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
import pytest
from greedy_collector.discovery.broad import providers as p, tavily
from greedy_collector.models import DiscoveryRunSource
from tests.test_broad_discovery import env, lookup, unrelated, review, BTC, ETH, P, ok
T = 'wallet.web_search.tavily'
KEY = 'tvly-test-only-sensitive/key+value'

@pytest.fixture
def tv(env, monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', KEY)
    monkeypatch.setenv('TAVILY_KEYLESS_ENABLED', 'true')
    state = SimpleNamespace(calls=[], status=200, error=None, payload={'results':[
        {'url':'https://www.justice.gov/test#section', 'title':'Public notice',
         'content':BTC+'; alias: vendor123; organization: Example Service;', 'raw_content':'MUST NOT STORE RAW CONTENT'},
        {'url':'https://example.org/fuzzy', 'title':'Fuzzy candidate', 'content':'No wallet here'}]})
    actual = httpx.AsyncClient
    def handler(request):
        state.calls.append(request)
        assert request.method == 'POST' and str(request.url) == 'https://api.tavily.com/search'
        if state.error: raise state.error
        return httpx.Response(state.status, json=state.payload)
    monkeypatch.setattr(tavily, 'httpx', SimpleNamespace(
        AsyncClient=lambda **kw: actual(transport=httpx.MockTransport(handler), **kw),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError))
    env.tv = state
    return env


def run(e, **kw): return lookup(e, (T,), **kw)
def query_key(e,row):
    with e.db() as db:return db.get(DiscoveryRunSource,row['sources'][0]['id']).query_fingerprint
def observations(snapshot): return [o for g in snapshot['groups'] for o in g['observations']]


def test_registration_capabilities_configuration_and_secret_safety(tv, monkeypatch):
    e=tv
    assert p.PROVIDERS.get('tavily_search').id=='tavily_search'
    caps=ok(e.c.get(P+'/transforms'));t=next(t for t in caps if t['id']==T)
    assert t['configured'] and t['executable'] and t['access_mode']=='api_key'
    assert t['cost_class']=='LIMITED_FREE' and t['max_results']==20 and t['max_requests']==1
    assert 'monero' in t['chains'] and t['cache_seconds']==21600
    assert next(t for t in caps if t['id']=='wallet.broad_web')['executable']
    assert KEY not in json.dumps(caps) and not e.tv.calls
    monkeypatch.delenv('TAVILY_API_KEY');monkeypatch.setenv('TAVILY_KEYLESS_ENABLED','false')
    t=next(t for t in ok(e.c.get(P+'/transforms')) if t['id']==T)
    assert not t['configured'] and not t['executable'] and t['missing_configuration']==['TAVILY_API_KEY']
    row,_=run(e)
    assert row['sources'][0]['quota_snapshot']['diagnostic']=='missing_api_key' and not e.tv.calls


def test_basic_query_parsing_candidates_graph_and_no_unrelated_writes(tv):
    e=tv;before=unrelated(e);row,s=run(e)
    assert row['status']=='completed' and row['returned_count']==2
    assert len(e.tv.calls)==1 and not e.state.calls
    req=e.tv.calls[0];body=json.loads(req.content)
    assert body['query']=='"'+BTC+'"' and body['search_depth']=='basic' and body['max_results']==20
    assert body['exact_match'] is True and body['topic']=='general'
    assert all(body[k] is False for k in ('auto_parameters','include_answer','include_raw_content','include_images','include_image_descriptions','include_favicon'))
    assert req.headers['Authorization']=='Bearer '+KEY and 'X-Tavily-Access-Mode' not in req.headers
    obs=observations(s);exact=next(o for o in obs if o['source_snapshot']['exact_match']);fuzzy=next(o for o in obs if not o['source_snapshot']['exact_match'])
    snap=exact['source_snapshot']
    assert snap['provider']=='tavily_search' and snap['provider_metadata']['access_mode']=='api_key'
    assert snap['bounds']['max_requests']==1 and snap['rank']==1 and exact['retrieved_at']
    assert snap['query']=='"'+BTC+'"' and snap['chain']=='bitcoin'
    assert {c['kind'] for c in s['candidates']}=={'domain','alias','entity'}
    assert 'MUST NOT STORE' not in json.dumps(s)
    graph=ok(e.c.get(P+'/runs/'+row['id']+'/graph'))
    assert {'web_source','alias_candidate','entity_candidate','domain_candidate'} <= {n['type'] for n in graph['items']}
    assert not ok(e.c.get(P+'/observations/'+exact['id']+'/promotion-preview'))['eligible']
    review(e,exact);preview=ok(e.c.get(P+'/observations/'+exact['id']+'/promotion-preview'))
    assert preview['eligible'] and preview['evidence']['source_name']=='Tavily Web Search via Discovery'
    review(e,fuzzy);assert not ok(e.c.get(P+'/observations/'+fuzzy['id']+'/promotion-preview'))['eligible']
    assert unrelated(e)==before  # Labels, risk, monitoring, clusters, cases and Attribution unchanged.
    assert len(e.tv.calls)==1 and KEY not in json.dumps([row,s,graph,preview])


def test_canonical_dedupe_preserves_both_provider_observations(tv):
    e=tv;e.tv.payload['results']=[e.tv.payload['results'][0],dict(e.tv.payload['results'][0],url='https://www.justice.gov/test#another')]
    row,s=lookup(e,(T,'wallet.broad_web'))
    assert len(s['groups'])==1 and len(s['groups'][0]['result_ids'])==1
    assert {o['provider'] for o in observations(s)}=={'tavily_search','brave_search'}
    assert len(observations(s))==2 and len(e.tv.calls)==1 and len(e.state.calls)==1


@pytest.mark.parametrize('empty',[False,True])
def test_cache_hit_expiry_and_ttl(tv,empty):
    e=tv
    if empty:e.tv.payload={'results':[]}
    first,_=run(e);source=first['sources'][0]
    ttl=(datetime.fromisoformat(source['expires_at'])-datetime.fromisoformat(source['completed_at'])).total_seconds()
    assert ttl==(3600 if empty else 21600)
    cached,_=run(e);assert cached['sources'][0]['status']=='cache_hit' and len(e.tv.calls)==1
    with e.db() as db:
        db.get(DiscoveryRunSource,source['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    fresh,_=run(e);assert fresh['sources'][0]['status']=='succeeded' and len(e.tv.calls)==2


def test_keyless_mode_key_precedence_and_cache_isolation(tv,monkeypatch):
    e=tv;keyed,_=run(e)
    monkeypatch.delenv('TAVILY_API_KEY')
    caps=ok(e.c.get(P+'/transforms'));t=next(t for t in caps if t['id']==T)
    assert t['executable'] and t['configured'] and t['access_mode']=='keyless' and not t['missing_configuration']
    keyless,s=run(e)
    assert keyless['sources'][0]['status']=='succeeded' and len(e.tv.calls)==2
    assert query_key(e,keyed)!=query_key(e,keyless)
    assert e.tv.calls[-1].headers['X-Tavily-Access-Mode']=='keyless' and 'Authorization' not in e.tv.calls[-1].headers
    assert all(o['source_snapshot']['provider_metadata']['access_mode']=='keyless' for o in observations(s))
    cached,_=run(e);assert cached['sources'][0]['status']=='cache_hit' and len(e.tv.calls)==2


@pytest.mark.parametrize('status,diagnostic',[(401,'authentication_failed'),(403,'authentication_failed'),(429,'rate_limited'),(432,'quota_exhausted'),(433,'quota_exhausted'),(503,'provider_error'),(302,'provider_error')])
def test_provider_errors_are_distinct_no_retry_no_fallback(tv,status,diagnostic):
    e=tv;e.tv.status=status;e.tv.payload={'error':KEY+' upstream stack trace'}
    row,s=run(e)
    assert row['sources'][0]['quota_snapshot']['diagnostic']==diagnostic
    assert len(e.tv.calls)==1 and not e.state.calls and not s['groups']
    assert KEY not in json.dumps([row,s]) and 'upstream stack trace' not in json.dumps([row,s])


@pytest.mark.parametrize('status',[429,432,433])
def test_keyless_exhaustion(tv,monkeypatch,status):
    monkeypatch.delenv('TAVILY_API_KEY');tv.tv.status=status
    row,_=run(tv)
    assert row['sources'][0]['quota_snapshot']['diagnostic']=='keyless_allowance_exhausted'
    assert len(tv.tv.calls)==1 and not tv.state.calls


@pytest.mark.parametrize('error,diagnostic',[(httpx.ReadTimeout('private upstream'),'provider_timeout'),(httpx.ConnectError('private upstream'),'provider_error')])
def test_transport_failures(tv,error,diagnostic):
    tv.tv.error=error;row,_=run(tv)
    assert row['sources'][0]['quota_snapshot']['diagnostic']==diagnostic and len(tv.tv.calls)==1


@pytest.mark.parametrize('payload',[None,[],{}, {'results':None},{'results':[None]},{'results':[{'url':'https://example.org','title':'x','content':123}]}])
def test_invalid_response(tv,payload):
    tv.tv.payload=payload;row,s=run(tv)
    assert row['sources'][0]['quota_snapshot']['diagnostic']=='invalid_response' and not s['groups']


def test_quota_exhaustion_preserves_other_selected_provider(tv):
    tv.tv.status=432;row,s=lookup(tv,(T,'wallet.broad_web'))
    assert row['status']=='partial' and len(s['groups'])==1
    assert {o['provider'] for o in observations(s)}=={'brave_search'}
    assert len(tv.tv.calls)==len(tv.state.calls)==1


def test_provider_cap_never_repeats_queries(tv):
    tv.tv.payload={'results':[{'url':f'https://example.org/{i}','title':'Bounded','content':BTC} for i in range(25)]}
    row,s=run(tv)
    assert row['returned_count']==20 and s['truncated'] and len(tv.tv.calls)==1
    response=tv.c.post(P+'/plan',json={'broad':True,'subject':{'chain':'bitcoin','address':BTC},'selections':[{'transform_id':T,'parameters':{'max_results':21}}]})
    assert response.status_code==422


def test_chain_and_parameter_cache_isolation(tv):
    tv.tv.payload['results'][0]['content']=ETH
    a,_=run(tv,chain='ethereum',address=ETH);b,_=run(tv,chain='base',address=ETH);c,_=run(tv,chain='base',address=ETH,maximum=10)
    assert len({query_key(tv,r) for r in (a,b,c)})==3 and len(tv.tv.calls)==3


def test_secret_and_unsafe_url_redaction(tv):
    from urllib.parse import quote
    tv.tv.payload['results'][0]['content']+=' '+KEY+' '+quote(KEY,safe='')
    tv.tv.payload['results'].append({'url':'https://example.org/?value='+quote(KEY,safe=''),'title':'Secret URL','content':BTC})
    tv.tv.payload['results'].append({'url':'http://127.0.0.1/private','title':'Private URL','content':BTC})
    row,s=run(tv)
    assert row['returned_count']==2 and s['truncated']
    assert KEY not in json.dumps(s) and quote(KEY,safe='') not in json.dumps(s)
    assert '[redacted]' in json.dumps(s) and len(tv.tv.calls)==1
