"""Bounded Discovery HTTP contracts using temporary SQLite and test-only executors."""
import asyncio
import json
import time
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text,inspect
import main
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.discovery.router import get_runtime
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.executors import ExecutorRegistry
from greedy_collector.models import DiscoveryRun,DiscoveryObservation
from tests.test_discovery_execution import h,Harness,SyntheticExecutor,material,ETH

PREFIX='/api/greedy-collector/discovery'

@pytest.fixture
def api(h,monkeypatch):
    monkeypatch.setattr(main,'start_monitoring',lambda:None)
    monkeypatch.setattr(main,'stop_monitoring',lambda:None)
    old=main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_runtime]=lambda:h.runtime
    try:
        with TestClient(main.app) as client:
            yield client,h
            client.portal.call(h.runtime.stop)
    finally:
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(old)

def payload(sources=('test_one',),**options):
    return {'subject':{'chain':'ethereum','address':ETH},'selections':[{'transform_id':'wallet.public_code_mentions','source_id':x} for x in sources],**options}

def ok(response,status=200):
    assert response.status_code==status,response.text
    return response.json()

def create(client,data=None,key=None):
    data=data or payload()
    planned=ok(client.post(PREFIX+'/plan',json=data))
    return client.post(PREFIX+'/runs',json={**data,'expected_plan_fingerprint':planned['fingerprint']},headers={'Idempotency-Key':key} if key else {})

def terminal(client,identifier):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        row=ok(client.get(PREFIX+'/runs/'+identifier))
        if row['status'] not in ('queued','running'):return row
        time.sleep(.01)
    raise AssertionError('Test worker did not finish')

def result(client,row):return ok(client.get(PREFIX+'/runs/'+row['id']+'/results'))['items'][0]

@pytest.mark.parametrize('route',['/','/health','/docs','/openapi.json','/static/js/app.js','/static/app.css'])
def test_existing_routes(api,route):
    client,_=api;assert client.get(route).status_code==200
    assert client.get('/').text.count('data-workspace=')==11
    assert 'data-workspace="discovery"' in client.get('/').text

def test_capabilities_safe_and_no_execution(api,monkeypatch):
    client,h=api;monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','test-only-capability-secret')
    sources=ok(client.get(PREFIX+'/sources'));transforms=ok(client.get(PREFIX+'/transforms'))
    assert sources and transforms
    assert all(not row['executable'] for row in transforms)
    assert all(row['configured'] is True for row in sources)
    assert 'test-only-capability-secret' not in json.dumps([sources,transforms])
    assert 'credential_env' not in json.dumps(sources)
    assert h.count(DiscoveryRun)==0

def test_plan_is_local_and_create_dispatches(api):
    client,h=api;executor=h.bind()
    plan=ok(client.post(PREFIX+'/plan',json=payload()))
    assert h.count(DiscoveryRun)==0 and executor.calls==0
    assert plan['selections'][0]['eligibility']=='eligible'
    row=ok(create(client),202);done=terminal(client,row['id'])
    assert done['status']=='completed' and done['returned_count']==1 and executor.calls==1
    assert done['subject']['canonical_value']==ETH
    assert 'request_snapshot' not in done

def test_requested_descriptors_without_registered_implementations(api):
    client,h=api
    runtime=DiscoveryRuntime(h.sessions,ExecutorRegistry(),metadata_only=True)
    main.app.dependency_overrides[get_runtime]=lambda:runtime
    data=payload();data['selections']=[{'transform_id':x} for x in ('wallet.local_labels','wallet.manual_exact_web','wallet.public_code_mentions')]
    row=ok(create(client,data),202);done=terminal(client,row['id'])
    assert done['status']=='failed'
    assert all(source['status']=='unavailable' and source['requests_attempted']==0 for source in done['sources'])
    assert all(source['quota_snapshot']['eligibility']=='not_implemented' for source in done['sources'])
    assert h.count(DiscoveryObservation)==0
    client.portal.call(runtime.stop)

def test_run_result_and_observation_pagination(api):
    client,h=api;h.bind(executor=SyntheticExecutor(records=[material(repository=str(x+1)) for x in range(3)]))
    row=ok(create(client),202);terminal(client,row['id'])
    page=ok(client.get(PREFIX+'/runs/'+row['id']+'/results?limit=2'))
    assert page['total']==3 and len(page['items'])==2 and page['next_offset']==2
    assert len(ok(client.get(PREFIX+'/runs/'+row['id']+'/results?limit=2&offset=2'))['items'])==1
    item=page['items'][0];rid=item['result']['id'];oid=item['observation']['id']
    assert 'source_snapshot' not in item['observation']
    detail=ok(client.get(PREFIX+'/observations/'+oid));assert detail['source_snapshot']['public'] is True
    assert detail['source_id']=='test_one'
    assert ok(client.get(PREFIX+'/results/'+rid))['id']==rid
    assert ok(client.get(PREFIX+'/results/'+rid+'/observations?limit=1'))['total']==1

def test_list_filter_archive_restore(api):
    client,h=api;h.bind()
    first=terminal(client,ok(create(client),202)['id']);second=terminal(client,ok(create(client),202)['id'])
    page=ok(client.get(PREFIX+'/runs?limit=1'))
    assert page['total']==2 and page['next_offset']==1
    assert ok(client.get(PREFIX+'/runs?status=failed'))['total']==0
    row=ok(client.post(PREFIX+'/runs/'+first['id']+'/archive',json={'expected_version':first['version']}))
    assert ok(client.get(PREFIX+'/runs'))['total']==1
    assert ok(client.get(PREFIX+'/runs?include_archived=true'))['total']==2
    ok(client.post(PREFIX+'/runs/'+first['id']+'/restore',json={'expected_version':row['version']}))
    assert ok(client.get(PREFIX+'/runs?subject_id='+second['subject_id']))['total']==2

@pytest.mark.parametrize('state',['unreviewed','relevant','irrelevant'])
def test_review_api_and_history(api,state):
    client,h=api;h.bind();row=terminal(client,ok(create(client),202)['id']);item=result(client,row)
    r=item['result'];o=item['observation']
    assert r['review_status']=='unreviewed'
    data={'expected_version':r['version'],'observation_id':o['id'],'expected_source_fingerprint':o['content_sha256'],'status':state,'reason':'Synthetic review reason'}
    review=ok(client.post(PREFIX+'/results/'+r['id']+'/review',json=data))
    assert review['result']['review_status']==state and review['review']['actor_ref']=='local_analyst'
    assert ok(client.get(PREFIX+'/results/'+r['id']+'/reviews'))['total']==1
    assert client.post(PREFIX+'/results/'+r['id']+'/review',json=data).status_code==409

@pytest.mark.parametrize('change',[{'status':'promoted'},{'expected_version':0},{'reason':''},{'expected_source_fingerprint':'bad'},{'executor':'module.path'}])
def test_invalid_review_is_safe(api,change):
    client,h=api;h.bind();row=terminal(client,ok(create(client),202)['id']);item=result(client,row)
    data={'expected_version':item['result']['version'],'observation_id':item['observation']['id'],'expected_source_fingerprint':item['observation']['content_sha256'],'status':'relevant','reason':'Test only',**change}
    response=client.post(PREFIX+'/results/'+item['result']['id']+'/review',json=data)
    assert response.status_code==422
    assert response.json()['detail']['code']=='invalid_request'

@pytest.mark.parametrize('route',['/runs/missing','/runs/missing/results','/results/missing','/results/missing/observations','/observations/missing','/results/missing/reviews'])
def test_missing_records(api,route):
    client,_=api;assert client.get(PREFIX+route).status_code==404

@pytest.mark.parametrize('suffix',['?limit=0','?limit=101','?offset=-1','?status=garbage'])
def test_bounded_pagination(api,suffix):
    client,_=api;assert client.get(PREFIX+'/runs'+suffix).status_code==422

def test_invalid_plan_and_secret_error_safety(api):
    client,h=api;executor=h.bind()
    data=payload();data['selections'][0]['transform_id']='https://private.invalid?key=synthetic-secret'
    response=client.post(PREFIX+'/plan',json=data)
    assert response.status_code==422 and 'synthetic-secret' not in response.text
    assert executor.calls==0 and h.count(DiscoveryRun)==0

def test_stale_plan_rejected_before_run(api):
    client,h=api;executor=h.bind()
    response=client.post(PREFIX+'/runs',json={**payload(),'expected_plan_fingerprint':'0'*64})
    assert response.status_code==409 and executor.calls==0 and h.count(DiscoveryRun)==0

def test_idempotency_returns_existing_run(api):
    client,h=api;executor=h.bind()
    first=terminal(client,ok(create(client,key='fixed-intent'),202)['id'])
    again=ok(create(client,key='fixed-intent'),202)
    assert again['id']==first['id'] and executor.calls==1
    assert create(client,payload(refresh=True),key='fixed-intent').status_code==409

def test_cancel_completed_conflicts(api):
    client,h=api;h.bind();row=terminal(client,ok(create(client),202)['id'])
    assert client.post(PREFIX+'/runs/'+row['id']+'/cancel',json={'expected_version':row['version']}).status_code==409

@pytest.mark.parametrize('origin',['https://evil.invalid','null','http://testserver.evil.invalid','http://testserver/path'])
def test_cross_origin_mutations_rejected(api,origin):
    client,h=api
    assert client.post(PREFIX+'/plan',json=payload(),headers={'Origin':origin}).status_code==403
    assert h.count(DiscoveryRun)==0

def test_same_origin_and_cli_json_accepted(api):
    client,_=api
    assert client.post(PREFIX+'/plan',json=payload(),headers={'Origin':'http://testserver'}).status_code==200
    assert client.post(PREFIX+'/plan',json=payload()).status_code==200
    assert client.post(PREFIX+'/plan',data={'subject':'value'}).status_code==422

def test_request_size_and_raw_json_errors_safe(api):
    client,_=api
    for body in ['x'*32769,'{"token":"synthetic-secret",']:
        response=client.post(PREFIX+'/plan',content=body,headers={'Content-Type':'application/json'})
        assert response.status_code==422 and 'synthetic-secret' not in response.text

def test_schema_unavailable_preserves_capabilities_and_existing_ui(api,tmp_path):
    client,_=api;engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'unmigrated.db').as_posix(),connect_args={'check_same_thread':False})
    runtime=DiscoveryRuntime(sessionmaker(engine))
    main.app.dependency_overrides[get_runtime]=lambda:runtime
    try:
        assert client.get(PREFIX+'/runs').status_code==503
        assert client.get(PREFIX+'/transforms').status_code==200
        data=payload();data['selections']=[{'transform_id':'wallet.local_labels'}]
        assert create(client,data).status_code==503
        assert client.get('/').status_code==200
        assert inspect(engine).get_table_names()==[]
    finally:engine.dispose()

def test_openapi_contracts(api):
    client,_=api;spec=ok(client.get('/openapi.json'))
    paths={path:value for path,value in spec['paths'].items() if path.startswith(PREFIX)}
    assert len(paths)==23
    assert not any('/executor' in path for path in paths)
    assert [path for path in paths if path.endswith('/graph')]==[PREFIX+'/runs/{run_id}/graph']
    assert PREFIX+'/observations/{observation_id}/promote' in paths
    assert PREFIX+'/observations/{observation_id}/promotion-preview' in paths
    assert PREFIX+'/results/{result_id}/promotions' in paths
    for operations in paths.values():
        for operation in operations.values():
            assert operation['responses']
            for code,response in operation['responses'].items():
                if code.startswith('2'):assert response['content']['application/json']['schema']
    for name in ('RunState','SourceState','ReviewState','CostClass','SourceError'):
        assert spec['components']['schemas'][name]['enum']
    assert spec['components']['schemas']['ReviewState']['enum']==['unreviewed','relevant','irrelevant']
    assert 'DISCOVERY_GITHUB_TOKEN' not in json.dumps(paths)

def test_running_cancel_through_http(api):
    client,h=api;executor=h.bind()
    async def initialize():
        executor.entered=asyncio.Event();executor.release=asyncio.Event()
    client.portal.call(initialize)
    row=ok(create(client),202)
    async def entered():await asyncio.wait_for(executor.entered.wait(),5)
    client.portal.call(entered)
    current=ok(client.get(PREFIX+'/runs/'+row['id']))
    stopped=ok(client.post(PREFIX+'/runs/'+row['id']+'/cancel',json={'expected_version':current['version']}))
    assert stopped['status']=='cancelled' and stopped['sources'][0]['units_consumed']==1
    assert h.count(DiscoveryObservation)==0
