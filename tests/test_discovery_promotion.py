"""ED-6 real stored-material/API promotion; all synthetic material is test-only."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session, sessionmaker
from greedy_collector.models import (Base, Label, AttributionEntity, AttributionClaim, AttributionEvidence,
    AttributionClaimEvidence, AttributionEvent, DiscoveryPromotion, DiscoveryObservation, DiscoveryReview,
    RiskResult, Case, CaseEntity, KycMatch, WalletAlert)
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.attribution.service import AttributionService
from greedy_collector.attribution.domain import Conflict, AttributionError
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.promotion import PromotionService
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.router import router as discovery_router, get_runtime
from greedy_collector.attribution.router import router as attribution_router
from tests.test_discovery import record, ETH

P='/api/greedy-collector/discovery'
A='/api/greedy-collector/attribution'

@pytest.fixture
def env(tmp_path,monkeypatch):
    def blocked(*a,**k):raise AssertionError('Promotion must not request any provider')
    for target in ('httpx.HTTPTransport.handle_request','httpx.AsyncHTTPTransport.handle_async_request','requests.Session.request'):
        monkeypatch.setattr(target,blocked)
    engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'promotion.db').as_posix(),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,autoflush=False,expire_on_commit=False)
    app=FastAPI();app.include_router(discovery_router,prefix='/api/greedy-collector');app.include_router(attribution_router,prefix='/api/greedy-collector')
    runtime=DiscoveryRuntime(sessions,metadata_only=True)
    app.dependency_overrides[get_runtime]=lambda:runtime
    def db():
        with sessions() as session:yield session
    # Attribution routes use their normal service factory; explicit test-only stamp.
    with engine.begin() as c:
        c.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('20260915_01')")
    app.dependency_overrides[get_db]=db
    with sessions() as session:
        at=AttributionService(session)
        entity=at.create_entity({'canonical_name':'Test-only existing entity'})
        claim=at.create_claim({'entity_id':entity['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'operated_by','scope_note':'Test-only explicit scope'})
    with TestClient(app) as client:yield client,sessions,claim
    engine.dispose()

def material(env,kind='github',content='Test-only stored code context',review='relevant',**overrides):
    _,sessions,_=env
    with sessions() as db:
        svc=DiscoveryService(db)
        subject=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
        source='github' if kind=='github' else 'gc_labels'
        transform='wallet.public_code_mentions' if kind=='github' else 'wallet.local_labels'
        row=svc.create_run(subject['id'],[{'transform_id':transform,'source_id':source}],idempotency_key=__import__('uuid').uuid4().hex)
        row=svc.transition_run(row['id'],'running',expected_version=row['version'])
        svc.transition_source(row['sources'][0]['id'],'running',expected_run_version=row['version']);row=svc.get_run(row['id'])
        item=record(content,verification='exact_in_excerpt',excerpt=content,match_context={'matched_wallet':ETH.lower()},**overrides)
        if kind=='label':
            label=db.scalar(select(Label).limit(1))
            if label is None:
                # Historical Alembic revision tests seed the original Label
                # columns before RISK-2's archive-state revision exists.
                label=Label(id=__import__('uuid').uuid4().hex,chain='ethereum',address=ETH.lower(),label='Test annotation',type='Exchange',source='Test-only Label source',confidence=.7,last_updated=datetime.now(timezone.utc))
                db.execute(text('INSERT INTO labels (id,address,chain,label,type,source,confidence,last_updated) VALUES (:id,:address,:chain,:label,:type,:source,:confidence,:last_updated)'),
                    {key:getattr(label,key) for key in ('id','address','chain','label','type','source','confidence','last_updated')})
                db.commit()
            item={'kind':'candidate_evidence','predicate':'locally_labeled_as','from':{'kind':'blockchain_address','namespace':'ethereum','value':ETH},
                'to':{'kind':'annotation','namespace':'gc-label','value':label.id},'fact_key':{'label_id':label.id},
                'observation':{'kind':'local_label_snapshot','source_record_key':label.id,'origin_label_id':label.id,
                    'source_locator':'label:'+label.id,'title':'Test Label','summary':content,'retrieved_at':datetime.now(timezone.utc),
                    'source_snapshot':{'source_subsystem':'Greedy Collector Label','record':{'id':label.id,'label':label.label,'source':label.source,'confidence':label.confidence,'last_updated':label.last_updated}}}}
        result=svc.record_batch(row['sources'][0]['id'],[item],expected_run_version=row['version'])
        ob=svc.get_observation(result['observation_ids'][0])
        if review is not None:
            current=svc.get_result(ob['result_id'])
            svc.review(current['id'],ob['id'],review,'Explicit test review',expected_version=current['version'],expected_source_fingerprint=ob['content_sha256'])
        return ob

def preview(env,ob):
    response=env[0].get(P+f'/observations/{ob["id"]}/promotion-preview')
    assert response.status_code==200,response.text
    return response.json()

def payload(env,ob,stance='supports',**changes):
    return {'result_id':ob['result_id'],'claim_id':env[2]['id'],'expected_claim_version':env[2]['version'],
        'expected_source_fingerprint':preview(env,ob)['source_fingerprint'],
        'link':{'stance':stance,'directness':'context' if stance=='context' else 'direct','rationale':'Explicit test link rationale'},**changes}

def promote(env,ob,data=None):return env[0].post(P+f'/observations/{ob["id"]}/promote',json=data or payload(env,ob))
def counts(env):
    with env[1]() as db:return [db.scalar(select(func.count()).select_from(m)) for m in
        (AttributionEvidence,AttributionClaimEvidence,AttributionEvent,DiscoveryPromotion,AttributionEntity,AttributionClaim,Label,RiskResult,Case,CaseEntity,KycMatch,WalletAlert)]

@pytest.mark.parametrize('kind',['label','github'])
@pytest.mark.parametrize('stance',['supports','contradicts','context'])
def test_promotes_stored_material_atomically_with_provenance(env,kind,stance):
    ob=material(env,kind);before=counts(env);p=preview(env,ob)
    assert p['eligible'] and counts(env)==before
    response=promote(env,ob,payload(env,ob,stance));assert response.status_code==201,response.text
    value=response.json();promotion=value['promotion']
    assert value['claim']['assessment']=='unassessed' and value['claim']['needs_review']
    assert value['claim']['version']==2 and promotion['stance']==stance
    after=counts(env);assert after[:4]==[before[0]+1,before[1]+1,before[2]+2,before[3]+1] and after[4:]==before[4:]
    capture=env[0].get(A+'/evidence/'+promotion['evidence_id']).json()
    assert capture['collection_method']=='discovery_snapshot'
    assert capture['origin']==('analyst_added' if kind=='label' else 'public_osint')
    assert capture['origin_discovery_observation_id']==ob['id'] and capture['source_reliability']=='unassessed'
    assert capture['metadata_json']['observation']['source_snapshot']==ob['source_snapshot']
    history=env[0].get(P+f'/results/{ob["result_id"]}/promotions?limit=1').json()
    assert history['total']==1 and history['items'][0]['id']==promotion['id']

@pytest.mark.parametrize('status',[None,'unreviewed','irrelevant'])
def test_review_required_no_implicit_review(env,status):
    ob=material(env,review=status);before=counts(env)
    assert not preview(env,ob)['eligible'];assert promote(env,ob).status_code==422;assert counts(env)==before

def test_new_material_requires_own_review_historical_selection_remains_exact(env):
    old=material(env);new=material(env,content='Changed test material',review=None)
    assert old['result_id']==new['result_id']
    assert preview(env,old)['eligible'] and not preview(env,new)['eligible']
    response=promote(env,old);assert response.status_code==201,response.text
    env[2].update(response.json()['claim'])
    with env[1]() as db:
        svc=DiscoveryService(db);r=svc.get_result(new['result_id'])
        svc.review(r['id'],new['id'],'relevant','Reviewed changed content',expected_version=r['version'],expected_source_fingerprint=new['content_sha256'])
    response=promote(env,new);assert response.status_code==201,response.text
    assert counts(env)[3]==2

@pytest.mark.parametrize('withdrawn',[False,True])
def test_duplicate_permanent_identity(env,withdrawn):
    ob=material(env);data=payload(env,ob);response=promote(env,ob,data);assert response.status_code==201,response.text
    row=response.json();p=row['promotion']
    if withdrawn:
        with env[1]() as db:AttributionService(db).withdraw_evidence(p['claim_id'],p['link_id'],expected_version=2,reason='Test withdrawal')
    before=counts(env);duplicate=promote(env,ob,data)
    assert duplicate.status_code==409 and duplicate.json()['detail']['existing_id']==p['id'];assert counts(env)==before
    hist=env[0].get(P+f'/results/{ob["result_id"]}/promotions').json()['items'][0]
    assert bool(hist['withdrawn_at'])==withdrawn

def test_other_claim_reuses_identical_capture(env):
    ob=material(env);first=promote(env,ob).json()
    with env[1]() as db:
        svc=AttributionService(db);second=svc.create_claim({**{k:env[2][k] for k in ('chain','subject_ref','entity_id','scope_note')},'relationship':'controlled_by'})
    response=promote(env,ob,payload(env,ob,'contradicts',claim_id=second['id'],expected_claim_version=1))
    assert response.status_code==201,response.text
    assert response.json()['promotion']['evidence_id']==first['promotion']['evidence_id'];assert counts(env)[0]==1

@pytest.mark.parametrize('failure',['capture','link','promotion','event'])
def test_late_failures_rollback_every_record(env,monkeypatch,failure):
    ob=material(env);data=payload(env,ob);before=counts(env)
    original=Session.flush
    def broken(db,*a,**k):
        pending=list(db.new);original(db,*a,**k)
        typ={'capture':AttributionEvidence,'link':AttributionClaimEvidence,'promotion':DiscoveryPromotion,'event':AttributionEvent}[failure]
        if any(isinstance(row,typ) for row in pending):raise RuntimeError('test-only injected failure')
    monkeypatch.setattr(Session,'flush',broken)
    assert promote(env,ob,data).status_code==500
    assert counts(env)==before

@pytest.mark.parametrize('field,value',[('expected_claim_version',99),('expected_source_fingerprint','0'*64),('result_id','wrong-result')])
def test_stale_or_mismatched_intent(env,field,value):
    ob=material(env);before=counts(env)
    response=promote(env,ob,payload(env,ob,**{field:value}))
    assert response.status_code==(422 if field=='result_id' else 409);assert counts(env)==before

@pytest.mark.parametrize('extra',['snapshot','actor','entity_id','relationship','assessment','repository'])
def test_browser_cannot_supply_evidence_or_inferences(env,extra):
    ob=material(env);before=counts(env)
    assert promote(env,ob,payload(env,ob,**{extra:'test-only-forbidden'})).status_code==422;assert counts(env)==before

def test_resanitization_immutable_refresh_review_and_label_changes(env,monkeypatch):
    ob=material(env,'label');response=promote(env,ob);assert response.status_code==201,response.text
    path=A+'/evidence/'+response.json()['promotion']['evidence_id'];original=env[0].get(path).json()
    with env[1]() as db:
        label=db.scalar(select(Label));label.confidence=.1;db.commit()
        svc=DiscoveryService(db);r=svc.get_result(ob['result_id'])
        svc.review(r['id'],ob['id'],'irrelevant','Later explicit correction',expected_version=r['version'],expected_source_fingerprint=ob['content_sha256'])
    material(env,'label',content='Later test material',review=None)
    assert env[0].get(path).json()==original

@pytest.mark.parametrize('secret_key',['token','authorization','cookie','debug_path','localpath'])
def test_nested_secret_sanitization_at_promotion(env,secret_key,monkeypatch):
    ob=material(env,source_snapshot={'public':True,'nested':{secret_key:'test-only-sensitive','url':'https://u:pw@example.invalid/x?token=hidden&record=1','path':'C:\\private\\file'}})
    response=promote(env,ob);assert response.status_code==201,response.text
    value=env[0].get(A+'/evidence/'+response.json()['promotion']['evidence_id']).text
    assert 'test-only-sensitive' not in value and 'u:pw' not in value and 'hidden' not in value and 'private' not in value

def test_configured_secret_added_after_discovery_is_removed(env,monkeypatch):
    ob=material(env,content='stored later-configured-secret')
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','later-configured-secret')
    response=promote(env,ob);assert response.status_code==201,response.text
    assert 'later-configured-secret' not in env[0].get(A+'/evidence/'+response.json()['promotion']['evidence_id']).text

def test_missing_local_record_safe_and_openapi_typed(env):
    response=env[0].get(P+'/observations/not-present/promotion-preview');assert response.status_code==404
    schema=env[0].get('/openapi.json').json();assert 'PromotionInput' in schema['components']['schemas']
    assert schema['components']['schemas']['PromotionInput']['additionalProperties'] is False
    for method in ('patch','delete'):assert getattr(env[0],method)(P+'/results/x/promotions').status_code==405

@pytest.mark.parametrize('operation',['update','delete','replace','orm_update','orm_delete'])
def test_promotion_identity_is_immutable(env,operation):
    from sqlalchemy.exc import IntegrityError
    ob=material(env);response=promote(env,ob);assert response.status_code==201,response.text
    row=response.json()['promotion'];before=counts(env)
    with env[1]() as db:
        with pytest.raises((IntegrityError,ValueError)):
            if operation.startswith('orm'):
                p=db.get(DiscoveryPromotion,row['id'])
                if operation=='orm_update':p.actor_ref='changed'
                else:db.delete(p)
                db.flush()
            else:
                sql={'update':"UPDATE discovery_promotions SET actor_ref='changed' WHERE id=:id",
                     'delete':'DELETE FROM discovery_promotions WHERE id=:id',
                     'replace':'INSERT OR REPLACE INTO discovery_promotions SELECT * FROM discovery_promotions WHERE id=:id'}[operation]
                db.execute(text(sql),{'id':row['id']})
        db.rollback()
    assert counts(env)==before

@pytest.mark.parametrize('change',['missing_claim','different_wallet','archived_claim','archived_entity'])
def test_target_claim_boundaries(env,change):
    ob=material(env);data=payload(env,ob)
    with env[1]() as db:
        at=AttributionService(db)
        if change=='missing_claim':data['claim_id']='absent'
        if change=='different_wallet':
            c=at.create_claim({'entity_id':env[2]['entity_id'],'chain':'ethereum','subject_ref':'0x'+'cd'*20,'relationship':'operated_by','scope_note':'Another test wallet'})
            data['claim_id']=c['id']
        if change=='archived_claim':at.archive_claim(env[2]['id'],expected_version=1,reason='Test archive')
        if change=='archived_entity':at.archive_entity(env[2]['entity_id'],expected_version=1,reason='Test archive')
    before=counts(env);response=promote(env,ob,data)
    assert response.status_code==({'missing_claim':404,'different_wallet':422}.get(change,409));assert counts(env)==before

@pytest.mark.parametrize('field,value',[('stance','owner'),('directness','certain'),('rationale',''),('directness','direct')])
def test_explicit_link_validation(env,field,value):
    ob=material(env);data=payload(env,ob,'context');data['link'][field]=value
    assert promote(env,ob,data).status_code==422

def test_concurrent_duplicate_serialized_no_orphans(env):
    from concurrent.futures import ThreadPoolExecutor
    ob=material(env);data=payload(env,ob);before=counts(env)
    def work():
        with env[1]() as db:
            try:PromotionService(db).promote(ob['id'],data);return 'created'
            except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(lambda _:work(),range(2)))==['conflict','created']
    after=counts(env);assert after[:4]==[before[0]+1,before[1]+1,before[2]+2,before[3]+1]

def test_withdrawal_replacement_and_assessment_do_not_rewrite_promotion(env):
    ob=material(env);saved=promote(env,ob).json();p=saved['promotion']
    old=env[0].get(A+'/evidence/'+p['evidence_id']).json()
    with env[1]() as db:
        at=AttributionService(db)
        at.change_assessment(p['claim_id'], 'possible', expected_version=2,rationale='Explicit test assessment',reviewed_link_ids=[p['link_id']],acknowledged_contradictions=[])
        at.replace_evidence(p['claim_id'],p['link_id'],{'evidence_type':'analyst_observation','origin':'analyst_added','title':'Explicit test replacement','summary':'New analyst material','source_name':'Test analyst','analyst_note':'Test replacement'},
            {'stance':'context','directness':'context','rationale':'Explicit replacement context'},expected_version=3,reason='Test replacement')
    assert env[0].get(A+'/evidence/'+p['evidence_id']).json()==old
    history=env[0].get(P+f'/results/{ob["result_id"]}/promotions').json()['items'][0]
    assert history['evidence_id']==p['evidence_id'] and history['withdrawn_at']

def test_preview_policy_revocation_and_review_change_conflict(env):
    ob=material(env);data=payload(env,ob)
    with env[1]() as db:
        svc=DiscoveryService(db);r=svc.get_result(ob['result_id'])
        svc.review(r['id'],ob['id'],'irrelevant','Explicit new decision',expected_version=r['version'],expected_source_fingerprint=ob['content_sha256'])
    assert promote(env,ob,data).status_code==409

@pytest.mark.parametrize('field', ['observation_id','claim_id','evidence_id','link_id','capture_fingerprint','claim_version_after'])
def test_promotion_database_references_and_checks(env,field):
    from sqlalchemy.exc import IntegrityError
    ob=material(env);saved=promote(env,ob).json()['promotion']
    with env[1]() as db:
        original=db.get(DiscoveryPromotion,saved['id'])
        values={c.name:getattr(original,c.name) for c in DiscoveryPromotion.__table__.columns}
        values['id']='test-another-id';values['observation_id']='missing-observation'
        values[field]=0 if field=='claim_version_after' else 'invalid'
        with pytest.raises(IntegrityError):db.execute(DiscoveryPromotion.__table__.insert().values(**values))
        db.rollback()

@pytest.mark.parametrize('fmt',['markdown','html','json','pdf'])
def test_case_pin_and_all_report_formats_retain_discovery_capture(env,fmt,monkeypatch):
    from greedy_collector.attribution.cases import CaseAttributionService, report_attribution
    from greedy_collector.attribution.service import row_data
    from greedy_collector import reporting
    ob=material(env);saved=promote(env,ob).json();p=saved['promotion']
    with env[1]() as db:
        case=Case(title='ED-6 test report',description='Test only');db.add(case);db.commit();cid=case.id;case_data=row_data(case)
        CaseAttributionService(db).add_reference(cid,'attribution_claim',p['claim_id'],expected_version=2)
        before=report_attribution(db,cid)
        AttributionService(db).withdraw_evidence(p['claim_id'],p['link_id'],expected_version=2,reason='Later test withdrawal')
        after=report_attribution(db,cid)
        assert before['references'][0]['pinned']==after['references'][0]['pinned']
        assert before['references'][0]['evidence'][0]['capture']==after['references'][0]['evidence'][0]['capture']
    paragraphs=[]
    if fmt=='pdf':
        from reportlab.platypus import Paragraph
        original=Paragraph.__init__
        def record_paragraph(self,value,*a,**k):paragraphs.append(value);original(self,value,*a,**k)
        monkeypatch.setattr(Paragraph,'__init__',record_paragraph)
    output=getattr(reporting,'case_'+fmt)(case_data,[],[],[],after)
    rendered=' '.join(paragraphs) if fmt=='pdf' else output
    assert 'discovery_snapshot' in rendered and ob['id'] in rendered
    if fmt=='pdf':assert output.startswith(b'%PDF')

def test_populated_promotion_downgrade_refuses_history_loss(env,monkeypatch):
    from alembic import command
    from tests.test_attribution_migration import config
    ob=material(env);saved=promote(env,ob);assert saved.status_code==201,saved.text
    engine=env[1].kw['bind'];before=counts(env)
    with pytest.raises(RuntimeError,match='populated Discovery promotion history'):
        command.downgrade(config(str(engine.url),monkeypatch),'20260913_01')
    assert counts(env)==before
    with engine.connect() as c:assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()=='20260915_01'

def test_policy_revoked_before_confirmation_blocks_promotion(env):
    from greedy_collector.discovery.registry import Registry,REGISTRY
    ob=material(env);data=payload(env,ob);before=counts(env)
    sources=[s.model_dump() for s in REGISTRY.sources.values()]
    for source in sources:
        if source['id']=='github':source['storage_allowed']=False
    registry=Registry(sources,list(REGISTRY.transforms.values()))
    with env[1]() as db:
        svc=PromotionService(db,registry=registry)
        assert not svc.preview(ob['id'])['eligible']
        with pytest.raises(Conflict):svc.promote(ob['id'],data)
    assert counts(env)==before

def test_quota_and_nonattribution_rows_are_unchanged_by_promotion(env):
    from sqlalchemy import inspect
    ob=material(env)
    def state():
        with env[1]() as db:
            tables=inspect(db.connection()).get_table_names()
            return {t:db.execute(text('SELECT * FROM '+t+' ORDER BY rowid')).all() for t in tables if not t.startswith('attribution_') and t!='discovery_promotions'}
    before=state();assert promote(env,ob).status_code==201;assert state()==before
