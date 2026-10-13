"""ED-9A through the real API/storage/review/graph/ED6, with no network."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import socket
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.exc import IntegrityError
from greedy_collector.models import (DiscoveryRun,DiscoveryRunItem,DiscoveryRunSource,DiscoveryResult,DiscoveryObservation,DiscoverySubject,Case,CaseEntity,AttributionEvidence,WatchlistWallet,MonitoringRun)
from greedy_collector.discovery.manual_source import ManualSourceService,TRANSFORM_ID,SOURCE_ID
from greedy_collector.discovery.domain import DiscoveryError
from tests.test_discovery_promotion import env as base_env,counts,preview,payload,promote,P,A
from tests.test_discovery_local_manual import BTC,BECH
from tests.test_discovery import ETH

ONION='http://'+'a'*56+'.onion/listing/1'

@pytest.fixture
def env(base_env,monkeypatch):
    def blocked(*a,**kw):raise AssertionError('Capture must not perform networking or DNS')
    for target in ('socket.getaddrinfo','socket.create_connection','socket.socket.connect'):
        monkeypatch.setattr(target,blocked)
    return base_env

def data(**kw):
    return dict(subject={'chain':'ethereum','address':ETH},source_type='marketplace_listing',
        source_url='https://example.invalid/listing/1',title='Test listing',service_name='Synthetic service',alias='Synthetic account',
        observed_at='2025-01-02T09:00:00+05:30',context='Test payment reference '+ETH+' — 日本語',analyst_note='Recorded manually in test.',**kw)

def capture(env,value=None):
    c=env[0];value=value or data()
    response=c.post(P+'/manual-source/preview',json=value);assert response.status_code==200,response.text
    response=c.post(P+'/manual-source/capture',json={'capture':value,'expected_preview_fingerprint':response.json()['preview_fingerprint']})
    assert response.status_code==201,response.text
    return response.json()

def amount(env,model):
    with env[1]() as db:return db.scalar(select(func.count()).select_from(model))

def graph(env,row):return env[0].get(P+'/runs/'+row['run_id']+'/graph').json()

def review(env,row,status='relevant'):
    r=env[0].get(P+'/results/'+row['result_id']).json();o=row['observation']
    response=env[0].post(P+'/results/'+r['id']+'/review',json={'observation_id':o['id'],'expected_version':r['version'],'expected_source_fingerprint':o['content_sha256'],'status':status,'reason':'Explicit test review'})
    assert response.status_code==200,response.text

@pytest.mark.parametrize('chain,address,expected', [('ethereum',ETH.upper().replace('0X','0x'),ETH.lower()),('bitcoin',BTC,BTC),('bitcoin',BECH.upper(),BECH)])
def test_capture_api_canonical_wallet_times_direction_and_boundaries(env,chain,address,expected):
    before=counts(env);value=data();value['subject']={'chain':chain,'address':address}
    row=capture(env,value);ob=row['observation'];snap=ob['source_snapshot']
    assert counts(env)==before
    assert amount(env,WatchlistWallet)==amount(env,MonitoringRun)==0
    assert snap['subject']=={'chain':chain,'address':expected}
    assert snap['context']==value['context'] and snap['alias']==value['alias']
    assert datetime.fromisoformat(ob['observed_at'])==datetime(2025,1,2,3,30,tzinfo=timezone.utc)
    assert datetime.fromisoformat(row['captured_at']).replace(tzinfo=timezone.utc)>datetime.now(timezone.utc)-timedelta(minutes=1)
    assert 'captured_at' not in snap and snap['source_fetched'] is False
    assert ob['kind']=='analyst_capture' and ob['verification']=='not_checked'
    run=env[0].get(P+'/runs/'+row['run_id']).json();src=run['sources'][0]
    assert run['status']=='completed' and src['source_id']==SOURCE_ID and src['transform_id']==TRANSFORM_ID
    assert src['requests_attempted']==src['units_consumed']==src['requests_reserved']==0
    r=env[0].get(P+'/results/'+row['result_id']).json()
    assert r['review_status']=='unreviewed' and r['predicate']=='mentions_wallet'
    with env[1]() as db:
        source=db.get(DiscoverySubject,r['from_subject_id']);wallet=db.get(DiscoverySubject,r['to_subject_id'])
        assert source.kind=='url' and wallet.canonical_value==expected and wallet.id==r['query_subject_id']
    g=graph(env,row);node=g['items'][0];edge=g['edges'][0]
    assert node['type']=='source_page' and node['manual_source']==snap
    assert edge['source']==node['id'] and edge['target']==g['root']['id'] and edge['predicate']=='mentions_wallet'
    assert not preview(env,ob)['eligible']

def test_preview_no_writes_and_capability_not_provider_plan(env):
    before=counts(env);c=env[0]
    response=c.post(P+'/manual-source/preview',json=data());assert response.status_code==200
    for model in (DiscoveryRun,DiscoverySubject,DiscoveryResult,DiscoveryObservation):assert amount(env,model)==0
    cap=next(t for t in c.get(P+'/transforms').json() if t['id']==TRANSFORM_ID)
    assert cap['capture_only'] and cap['implemented'] and cap['executable'] and cap['mode']=='manual' and cap['max_requests']==0
    assert c.post(P+'/plan',json={'subject':data()['subject'],'selections':[{'transform_id':TRANSFORM_ID}]}).status_code==422
    assert counts(env)==before

@pytest.mark.parametrize('source_type',['webpage','marketplace_listing','marketplace_vendor_page','forum_post','document','other'])
def test_source_types_and_reference_only(env,source_type):
    value=data();value.update(source_type=source_type,source_url=None,source_reference='EXHIBIT-01')
    row=capture(env,value)
    with env[1]() as db:
        r=db.get(DiscoveryResult,row['result_id']);endpoint=db.get(DiscoverySubject,r.from_subject_id)
        assert (endpoint.kind,endpoint.namespace)==('annotation','manual-source')
    assert graph(env,row)['items'][0]['manual_source']['source_reference']=='EXHIBIT-01'

@pytest.mark.parametrize('url',['https://example.invalid/a','http://example.invalid/a',ONION,'https://EXAMPLE.invalid:443/a?item=12'])
def test_inert_urls_no_fetch(env,url):
    value=data();value['source_url']=url
    row=capture(env,value);assert row['observation']['source_snapshot']['entered_source_url']==url
    assert row['observation']['source_snapshot']['source_fetched'] is False

@pytest.mark.parametrize('url',['javascript:alert(1)','data:text/plain,secret','file:///C:/private.txt','http://localhost/x','http://127.0.0.1/x','http://10.0.0.1/x','http://user:password@example.invalid/x','https://example.invalid/a\n','https://example.invalid/%0a','https://example.invalid/?session=secret','https://example.invalid/#access_token=secret','https://example.invalid/?api_key=secret','http://short.onion/','https://example.invalid/'+('a'*2050)])
def test_unsafe_urls_rejected_no_material_or_echo(env,url):
    value=data();value['source_url']=url
    response=env[0].post(P+'/manual-source/preview',json=value)
    assert response.status_code==422,response.text
    assert 'secret' not in response.text and amount(env,DiscoveryRun)==0

@pytest.mark.parametrize('field,value',[('context','Authorization: Bearer secret'),('analyst_note','Cookie: session=secret'),('source_reference','C:\\Users\\user\\secret.txt'),('alias','\x00bad'),('observed_at','bad-date'),('observed_at','2025-01-01T00:00:00'),('observed_at','2099-01-01T00:00:00Z'),('source_type','arbitrary'),('context',''),('analyst_note',' '),('context','a'*4001)])
def test_capture_validation(env,field,value):
    values=data();values[field]=value
    assert env[0].post(P+'/manual-source/preview',json=values).status_code==422
    assert amount(env,DiscoveryObservation)==0

@pytest.mark.parametrize('address',['alice.eth','0x'+'11'*32,'11'*32,'wc:example@2?secret=abc','arbitrary'])
def test_reject_non_wallet_subject(env,address):
    values=data();values['subject']['address']=address
    assert env[0].post(P+'/manual-source/preview',json=values).status_code==422

def test_double_submit_and_attachment_order_are_idempotent(env):
    values=data();values['attachments']=[{'reference':'Exhibit A','sha256':'a'*64},{'reference':'Exhibit B','sha256':'b'*64}]
    first=capture(env,values);values['attachments'].reverse();second=capture(env,values)
    assert second['duplicate'] and first['observation_id']==second['observation_id'] and first['captured_at']==second['captured_at']
    assert amount(env,DiscoveryObservation)==amount(env,DiscoveryRun)==1

def test_correction_retains_history_and_requires_new_review(env):
    first=capture(env);review(env,first);old_graph=graph(env,first)
    changed=data();changed['context']='Corrected test context';second=capture(env,changed)
    assert first['result_id']==second['result_id'] and first['observation_id']!=second['observation_id']
    assert env[0].get(P+'/observations/'+first['observation_id']).json()==first['observation']
    assert graph(env,first)['items'][0]['manual_source']==old_graph['items'][0]['manual_source']
    assert graph(env,second)['items'][0]['current_review_required']
    assert preview(env,first['observation'])['eligible'] and not preview(env,second['observation'])['eligible']
    with env[1]() as db:
        with pytest.raises(IntegrityError):db.execute(text('UPDATE discovery_observations SET title=:title WHERE id=:id'),{'title':'mutated','id':first['observation_id']});db.commit()

@pytest.mark.parametrize('status',['unreviewed','irrelevant','relevant'])
@pytest.mark.parametrize('stance',['supports','contradicts','context'])
def test_ed6_explicit_promotion_manual_origin_and_snapshot(env,status,stance):
    value=data();value['attachments']=[{'reference':'Exhibit A','filename':'capture.png','sha256':'a'*64,'content_type':'image/png','byte_size':123}]
    row=capture(env,value);review(env,row,status);ob=row['observation'];before=counts(env)
    response=promote(env,ob,payload(env,ob,stance))
    if status!='relevant':assert response.status_code==422 and counts(env)==before;return
    assert response.status_code==201,response.text
    saved=response.json();evidence=env[0].get(A+'/evidence/'+saved['promotion']['evidence_id']).json()
    assert evidence['origin']=='analyst_added' and saved['claim']['assessment']=='unassessed'
    assert evidence['metadata_json']['observation']['source_snapshot']==ob['source_snapshot']
    assert counts(env)[4:]==before[4:]
    changed=data();changed['analyst_note']='New correction';capture(env,changed)
    assert env[0].get(A+'/evidence/'+evidence['id']).json()==evidence

def test_stale_preview_and_partial_capture_rollback(env,monkeypatch):
    value=data();c=env[0];p=c.post(P+'/manual-source/preview',json=value).json();value['context']='Different'
    assert c.post(P+'/manual-source/capture',json={'capture':value,'expected_preview_fingerprint':p['preview_fingerprint']}).status_code==409
    original=ManualSourceService.record_batch
    def fail(self,*args,**kw):original(self,*args,**kw);raise RuntimeError('test failure after storage')
    monkeypatch.setattr(ManualSourceService,'record_batch',fail)
    p=c.post(P+'/manual-source/preview',json=value).json()
    assert c.post(P+'/manual-source/capture',json={'capture':value,'expected_preview_fingerprint':p['preview_fingerprint']}).status_code==500
    for model in (DiscoverySubject,DiscoveryRun,DiscoveryRunSource,DiscoveryResult,DiscoveryObservation,DiscoveryRunItem):assert amount(env,model)==0

def test_case_association_is_explicit_idempotent_and_independent(env):
    with env[1]() as db:
        case=Case(title='Synthetic investigation');db.add(case);db.commit();case_id=case.id
    value=data();value['case_id']=case_id;row=capture(env,value);capture(env,value)
    with env[1]() as db:
        links=db.scalars(select(CaseEntity)).all();assert len(links)==1
        assert links[0].entity_type=='discovery_observation' and links[0].entity_ref==row['observation_id']
        with pytest.raises(ValueError,match='immutable'):
            db.delete(links[0]);db.flush()
        db.rollback()
        from greedy_collector.models import utcnow
        db.get(Case,case_id).archived_at=utcnow();db.commit()
        assert db.scalars(select(CaseEntity)).all()[0].entity_ref==row['observation_id']
    assert env[0].get(P+'/observations/'+row['observation_id']).status_code==200

def test_two_wallets_same_source_no_cluster(env):
    first=capture(env);value=data();value['subject']={'chain':'bitcoin','address':BTC};second=capture(env,value)
    with env[1]() as db:
        a=db.get(DiscoveryResult,first['result_id']);b=db.get(DiscoveryResult,second['result_id'])
        assert a.from_subject_id==b.from_subject_id and a.to_subject_id!=b.to_subject_id
    assert len(graph(env,first)['edges'])==len(graph(env,second)['edges'])==1

@pytest.mark.parametrize('attachment',[{'reference':'Exhibit','sha256':'invalid'},{'reference':'Exhibit','sha256':'a'*64,'filename':'../capture.png'},{'reference':'Exhibit','sha256':'a'*64,'byte_size':-1}])
def test_invalid_attachment_references(env,attachment):
    values=data();values['attachments']=[attachment]
    assert env[0].post(P+'/manual-source/preview',json=values).status_code==422

@pytest.mark.parametrize('url',['http://2130706433/','http://0177.0.0.1/','http://localhost./','https://example.invalid/\u202e','https://example.invalid\\path'])
def test_browser_interpretation_and_unicode_control_urls_rejected(env,url):
    value=data();value['source_url']=url
    assert env[0].post(P+'/manual-source/preview',json=value).status_code==422

def test_missing_case_and_browser_supplied_server_fields_rejected(env):
    value=data();value['case_id']='does-not-exist'
    assert env[0].post(P+'/manual-source/preview',json=value).status_code==404
    value=data();value['captured_at']='2025-01-01T00:00:00Z'
    assert env[0].post(P+'/manual-source/preview',json=value).status_code==422
    assert amount(env,DiscoveryRun)==0

def test_promotion_stance_and_rationale_never_defaulted(env):
    row=capture(env);review(env,row);ob=row['observation']
    for field in ('stance','directness','rationale'):
        request=payload(env,ob);del request['link'][field]
        assert promote(env,ob,request).status_code==422
    assert amount(env,AttributionEvidence)==0

def test_full_length_context_remains_promotable(env):
    value=data();value.update(context='x'*4000,analyst_note='y'*2000)
    row=capture(env,value);review(env,row)
    response=promote(env,row['observation'],payload(env,row['observation'],'context'))
    assert response.status_code==201,response.text
    evidence=env[0].get(A+'/evidence/'+response.json()['promotion']['evidence_id']).json()
    assert evidence['metadata_json']['observation']['source_snapshot']['context']==value['context']

def test_test_session_database_guard():
    import os,tempfile
    from pathlib import Path
    from sqlalchemy import create_engine
    assert os.environ['PYTHON_DOTENV_DISABLED']=='1'
    assert Path(os.environ['GREEDY_COLLECTOR_DATABASE_URL'].removeprefix('sqlite:///')).is_relative_to(Path(tempfile.gettempdir()))
    forbidden=Path(__file__).resolve().parents[1]/'must-never-open.db'
    engine=create_engine('sqlite:///'+forbidden.as_posix())
    try:
        with pytest.raises(AssertionError,match='temporary storage'):engine.connect()
        assert not forbidden.exists()
    finally:engine.dispose()
