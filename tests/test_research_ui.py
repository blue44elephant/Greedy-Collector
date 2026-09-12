"""Real research engine/service/API paths with isolated SQLite and provider fixtures."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from tests.test_ui import ui_client,no_monitoring
from greedy_collector.router import service
from greedy_collector.kyc import KycScreeningEngine
from greedy_collector.schemas import KycQuery
from greedy_collector.models import KycScreeningRun,KycMatch,Label,Address,CaseEntity

PREFIX='/api/greedy-collector'
SECRET='research-test-only-secret'

@pytest.fixture
def research_provider(monkeypatch):
    settings=service.kyc_engine.settings
    for key in ['opensanctions_api_key','virustotal_api_key','urlscan_api_key']:monkeypatch.setattr(settings,key,SECRET)
    calls=[]
    async def request(url,**kwargs):
        calls.append((url,kwargs))
        if 'opensanctions' in url:return {'results':[{'caption':'Test Company','id':'test-record','schema':'Company','datasets':['test'],'api_key':SECRET,'public_field':'Preserve this evidence'}]}
        if 'interpol' in url:return {'_embedded':{'notices':[]}}
        if 'sec.gov' in url:return {}
        if 'gdelt' in url:return {'articles':[]}
        if 'crt.sh' in url:return []
        if 'urlscan' in url:raise RuntimeError('https://provider.invalid?key='+SECRET)
        if 'virustotal' in url:return {'data':{'attributes':{'last_analysis_stats':{'malicious':0}}}}
        raise AssertionError('Unexpected provider')
    monkeypatch.setattr(service.kyc_engine,'_request',request)
    monkeypatch.setattr('httpx.AsyncClient.request',AsyncMock(side_effect=AssertionError('No live HTTP')))
    return calls

def test_research_redacts_provider_credentials_in_evidence_and_storage(ui_client,research_provider):
    client,engine=ui_client
    response=client.post(PREFIX+'/kyc/screen',json={'name':'Test Company','domain':'example.org'})
    assert response.status_code==200
    assert SECRET not in response.text
    data=response.json()
    assert data['matches'][0]['source_data']['public_field']=='Preserve this evidence'
    with Session(engine) as db:
        match=db.scalar(select(KycMatch).where(KycMatch.source=='opensanctions'))
        assert SECRET not in str(match.source_data)
        run=db.get(KycScreeningRun,data['run_id'])
        assert SECRET not in str(run.unavailable_sources)

@pytest.mark.parametrize('payload',[{'name':'  '},{'name':'Test Company','domain':'https://example.org/path'},{'name':'Test Company','domain':'bad domain'}])
def test_research_rejects_invalid_query_before_requests(ui_client,research_provider,payload):
    client,_=ui_client
    response=client.post(PREFIX+'/kyc/screen',json=payload)
    assert response.status_code==422
    assert research_provider==[]

def test_unexpected_source_exception_remains_visible(monkeypatch):
    engine=KycScreeningEngine()
    async def checked(query):return {'source':'test','checked':True,'matches':[]}
    for name in ['_opensanctions','_sec_edgar','_gdelt']:monkeypatch.setattr(engine,name,checked)
    monkeypatch.setattr(engine,'_interpol',AsyncMock(side_effect=RuntimeError(SECRET)))
    result=asyncio.run(engine.screen(KycQuery(name='Test Company')))
    assert any(row['id']=='interpol' for row in result['unavailable_sources'])
    assert SECRET not in str(result)

@pytest.mark.parametrize('configured',[False,True])
def test_source_capabilities_credentials_and_inputs(ui_client,monkeypatch,configured):
    client,_=ui_client
    for field in ['opensanctions_api_key','virustotal_api_key','urlscan_api_key']:monkeypatch.setattr(service.kyc_engine.settings,field,SECRET if configured else '')
    response=client.get(PREFIX+'/kyc/sources');assert response.status_code==200 and SECRET not in response.text
    rows={row['id']:row for row in response.json()['sources']}
    assert len(rows)==25
    for key in ['opensanctions','virustotal','urlscan']:assert rows[key]['credential_configured'] is configured
    assert rows['opensanctions']['credential_required'] is True
    assert rows['virustotal']['domain_required'] is True
    assert rows['urlscan']['credential_required'] is False
    assert rows['opencorporates']['mode']==rows['companies_house']['mode']=='manual'
    assert rows['sec_edgar']['input_fields']==['name']

@pytest.mark.parametrize('domain',[None,'example.org'])
def test_research_partial_results_persist_without_wallet_or_label_creation(ui_client,research_provider,domain):
    client,engine=ui_client
    response=client.post(PREFIX+'/kyc/screen',json={'name':'Test Company','domain':domain})
    assert response.status_code==200
    data=response.json();assert data['run_id'] and data['matches'] and data['manual_sources']
    assert len(research_provider)==(7 if domain else 4)
    assert any('opencorporates.com' in row['url'] for row in data['manual_sources'])
    assert any(row['id']=='urlscan' for row in data['unavailable_sources']) is bool(domain)
    assert SECRET not in response.text
    with Session(engine) as db:
        assert db.scalar(select(func.count(KycScreeningRun.id)))==1
        assert db.scalar(select(func.count(KycMatch.id)))==len(data['matches'])
        for model in [Label,Address,CaseEntity]:assert db.scalar(select(func.count(model.id)))==0

@pytest.mark.parametrize('status',['Unreviewed','Potential match','False positive','Confirmed source match'])
def test_match_review_persists_exact_status(ui_client,research_provider,status):
    client,engine=ui_client
    match=client.post(PREFIX+'/kyc/screen',json={'name':'Test Company'}).json()['matches'][0]
    response=client.patch(PREFIX+'/kyc/matches/'+match['id'],json={'review_status':status})
    assert response.status_code==200 and response.json()['review_status']==status and SECRET not in response.text
    with Session(engine) as db:assert db.get(KycMatch,match['id']).review_status==status
    assert client.patch(PREFIX+'/kyc/matches/missing',json={'review_status':status}).status_code==404
    assert client.patch(PREFIX+'/kyc/matches/'+match['id'],json={'review_status':'Owner confirmed'}).status_code==422

def test_name_only_no_matches_missing_keys_and_manual_toggle(ui_client,research_provider,monkeypatch):
    client,_=ui_client
    monkeypatch.setattr(service.kyc_engine.settings,'opensanctions_api_key','')
    response=client.post(PREFIX+'/kyc/screen',json={'name':'Nobody','include_manual_sources':False})
    assert response.status_code==200
    data=response.json();assert data['matches']==[] and data['manual_sources']==[]
    assert data['unavailable_sources'][0]['id']=='opensanctions'
    assert len(data['checked_sources'])==3

def test_research_frontend_and_routes(ui_client):
    client,_=ui_client
    assert 'data-workspace="research"' in client.get('/').text
    response=client.get('/static/js/research.js');assert response.status_code==200
    assert 'innerHTML' not in response.text
    paths=client.get('/openapi.json').json()['paths']
    assert 'get' in paths[PREFIX+'/kyc/sources']
    assert 'post' in paths[PREFIX+'/kyc/screen']
    assert 'patch' in paths[PREFIX+'/kyc/matches/{match_id}']
