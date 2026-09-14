"""AT-6 pinned case/report workflows with real services and isolated SQLite."""
import json
from io import BytesIO
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from tests.test_attribution_api import api,migrated_template,claim,attach,assess,ok,P,API,ETH,entity
from tests.test_ui import ui_client,no_monitoring
from greedy_collector.models import CaseEntity,AttributionClaim,AttributionEntity,AttributionEvidence,AttributionEvent,AttributionClaimEvidence,RiskResult,Label,KycMatch
from greedy_collector.attribution.cases import CaseAttributionService


def case(client):return ok(client.post(API+'/cases',json={'title':'Synthetic AT6 case','description':'Retain existing material'}))
def pin(client,case_id,row,kind='attribution_claim',**extra):return client.post(P+f'/cases/{case_id}/references',json={'reference_type':kind,'target_id':row['id'],'expected_version':row['version'],**extra})
def refs(client,case_id):return ok(client.get(P+f'/cases/{case_id}/references'))
def report(client,case_id,fmt):return client.get(API+f'/reports/{case_id}?format={fmt}')
def counts(engine):
    with Session(engine) as db:return [db.scalar(select(func.count()).select_from(m)) for m in (CaseEntity,AttributionEntity,AttributionClaim,AttributionEvidence,AttributionClaimEvidence,AttributionEvent,RiskResult,Label,KycMatch)]


@pytest.fixture
def material(api):
    client,engine=api;row=claim(client)
    for stance in ['supports','contradicts','context']:row=attach(client,row,stance)['claim']
    row=ok(assess(client,row,'supported'))
    return case(client),row


@pytest.mark.parametrize('kind',['entity','attribution_claim'])
def test_explicit_reference_and_duplicate(api,material,kind):
    client,engine=api;c,row=material
    if kind=='entity':row=ok(client.get(P+'/entities/'+row['entity_id']))
    before=counts(engine);saved=ok(pin(client,c['id'],row,kind),201)
    assert saved['pinned']['target_id']==row['id'];assert saved['pinned']['reference_type']==kind
    assert saved['pinned']['entity']['version']>=1 and saved['pinned']['captured_at']
    assert saved['current']['changed'] is False
    after=counts(engine);assert after==[before[0]+1,*before[1:]]
    ok(pin(client,c['id'],row,kind),409);assert counts(engine)==after
    assert refs(client,c['id'])['total']==1
    assert ok(client.get(API+'/cases/'+c['id']))['entities'][0]['entity_type']==kind


@pytest.mark.parametrize('kind',['entity','attribution_claim'])
def test_missing_reference_and_case(api,kind):
    client,engine=api;c=case(client);before=counts(engine)
    ok(pin(client,c['id'],{'id':'missing','version':1},kind),404)
    row=entity(client) if kind=='entity' else claim(client)
    ok(pin(client,'missing',row,kind),404)
    assert counts(engine)[0]==before[0]


def test_pin_uses_existing_schema_and_forbids_forgery(api,material):
    client,engine=api;c,row=material
    for extra in [{'metadata':{'assessment':'strongly_supported'}},{'pinned':{}},{'expected_version':999}]:
        ok(pin(client,c['id'],row,**extra),409 if 'expected_version' in extra else 422)
    assert refs(client,c['id'])['total']==0
    saved=ok(pin(client,c['id'],row),201)
    with Session(engine) as db:
        record=db.get(CaseEntity,saved['id']);assert record.metadata_json['attribution_pin']['claim']['version']==row['version']
    # Existing generic case endpoint cannot forge these server-owned reference kinds.
    ok(client.post(API+f'/cases/{c["id"]}/entities',json={'entity_type':'attribution_claim','entity_ref':row['id'],'metadata':{'attribution_pin':{}}}),422)


def test_historical_pin_survives_rejection_and_withdrawal(api,material):
    client,engine=api;c,row=material;saved=ok(pin(client,c['id'],row),201)
    historical=report(client,c['id'],'json').json()['attribution']['references'][0]
    assert historical['pinned']['claim']['assessment']=='supported'
    rejected=ok(assess(client,row,'rejected'))
    original=historical['pinned'];links=original['links']
    link=next(x for x in links if x['stance']=='supports')
    ok(client.post(P+f'/claims/{row["id"]}/evidence/{link["id"]}/withdraw',json={'expected_version':rejected['version'],'reason':'Later withdrawal'}))
    current=refs(client,c['id'])['items'][0]
    assert current['pinned']==saved['pinned'];assert current['current']['claim']['assessment']=='rejected'
    assert current['current']['changed'] and current['current']['claim']['needs_review']
    later=report(client,c['id'],'json').json()['attribution']['references'][0]
    assert later['pinned']==original
    assert next(x for x in later['evidence'] if x['pinned_link']['id']==link['id'])['current_link']['withdrawn_at']
    assert historical['current']['claim']['assessment']=='supported' # Previously downloaded representation unchanged.
    text=report(client,c['id'],'markdown').text
    assert 'Pinned assessment: supported' in text and 'Current assessment: rejected' in text
    assert 'Withdrawn / historical' in text and 'Contradicting evidence' in text


@pytest.mark.parametrize('fmt',['markdown','html','json','pdf'])
def test_all_report_formats_retain_evidence_and_legacy_material(api,material,fmt,monkeypatch):
    client,engine=api;c,row=material;ok(pin(client,c['id'],row),201)
    ok(client.post(API+f'/cases/{c["id"]}/notes',json={'body':'Existing analyst note'}))
    before=counts(engine)
    paragraphs=[]
    if fmt=='pdf':
        from reportlab.platypus import Paragraph
        original=Paragraph.__init__
        def record(self,text,*args,**kwargs):paragraphs.append(text);original(self,text,*args,**kwargs)
        monkeypatch.setattr(Paragraph,'__init__',record)
    response=report(client,c['id'],fmt);assert response.status_code==200
    assert counts(engine)==before
    if fmt=='json':
        obj=response.json();assert obj['notes'][0]['body']=='Existing analyst note'
        assert 'evidence-backed analytic judgments' in obj['attribution']['disclaimer']
        ref=obj['attribution']['references'][0]
        assert {r['pinned_link']['stance'] for r in ref['evidence']}=={'supports','contradicts','context'}
        assert all(r['capture']['source_name'] and r['capture']['captured_at'] for r in ref['evidence'])
    else:
        text='\n'.join(paragraphs) if fmt=='pdf' else response.text
        for label in ['Attribution Assessment','Supporting evidence','Contradicting evidence','Contextual evidence','Existing analyst note','Pinned assessment: supported','Source:','rationale:']:
            assert label in text,label
        if fmt=='pdf':assert response.content.startswith(b'%PDF-') and len(response.content)>1000


@pytest.mark.parametrize('state',['rejected','archived'])
def test_rejected_and_archived_pins_are_explicit(api,material,state):
    client,_=api;c,row=material
    if state=='rejected':row=ok(assess(client,row,'rejected'))
    else:row=ok(client.post(P+f'/claims/{row["id"]}/archive',json={'expected_version':row['version'],'reason':'Archive'}))
    ok(pin(client,c['id'],row),201)
    text=report(client,c['id'],'markdown').text
    assert ('Pinned assessment: rejected' if state=='rejected' else 'Pinned claim state: Archived') in text


def test_withdrawn_before_pin_is_historical_not_active_count(api,material):
    client,_=api;c,row=material;link=ok(client.get(P+f'/claims/{row["id"]}/evidence'))['items'][0]
    row=ok(client.post(P+f'/claims/{row["id"]}/evidence/{link["id"]}/withdraw',json={'expected_version':row['version'],'reason':'Withdraw before pin'}))['claim']
    saved=ok(pin(client,c['id'],row),201)
    assert sum(saved['pinned_evidence_counts'].values())==2
    assert len(saved['pinned']['links'])==3
    assert 'Pinned link state: Withdrawn / historical' in report(client,c['id'],'markdown').text


def test_no_automatic_population_or_risk_changes(api,material):
    client,engine=api;c,row=material
    with Session(engine) as db:db.add(RiskResult(chain='ethereum',address=ETH,score=9,level='Low',findings=[]));db.commit()
    ok(client.post(API+f'/cases/{c["id"]}/entities',json={'entity_type':'wallet','entity_ref':ETH,'metadata':{'chain':'ethereum'}}))
    assert refs(client,c['id'])['total']==0
    before=counts(engine);ok(pin(client,c['id'],row),201);report(client,c['id'],'json')
    assert counts(engine)==[before[0]+1,*before[1:]]
    with Session(engine) as db:assert db.scalar(select(RiskResult)).score==9


def test_pin_late_failure_rolls_back(api,material,monkeypatch):
    client,engine=api;c,row=material;before=counts(engine)
    def fail(*args):raise RuntimeError('private database internals')
    monkeypatch.setattr(CaseAttributionService,'_summaries',fail)
    error=pin(client,c['id'],row);assert error.status_code==500 and 'private' not in error.text
    assert counts(engine)==before


@pytest.mark.parametrize('fmt',['markdown','html','json','pdf'])
def test_unmigrated_cases_reports_work(ui_client,fmt):
    client,_=ui_client;c=case(client)
    error=client.get(P+f'/cases/{c["id"]}/references');assert error.status_code==503
    assert report(client,c['id'],fmt).status_code==200
    assert client.get(API+'/cases/'+c['id']).status_code==200


def test_case_pin_pagination_and_entity_descriptor_change(api,material):
    client,_=api;c,row=material;ok(pin(client,c['id'],row),201)
    e=ok(client.get(P+'/entities/'+row['entity_id']));ok(pin(client,c['id'],e,'entity'),201)
    page=ok(client.get(P+f'/cases/{c["id"]}/references?limit=1'));assert page['total']==2 and page['next_offset']==1
    ok(client.patch(P+'/entities/'+e['id'],json={'expected_version':e['version'],'reason':'Revised descriptor','descriptor':{'canonical_name':'Changed descriptor','entity_type':'service'}}))
    for item in refs(client,c['id'])['items']:
        assert item['current']['changed'];assert item['pinned']['entity']['canonical_name']!='Changed descriptor'
    assert 'Changed descriptor' in report(client,c['id'],'markdown').text


def test_report_reapplies_secret_sanitization(api,material,monkeypatch):
    from greedy_collector.config import get_settings
    client,_=api;c,row=material
    # A manual capture may contain historical metadata; AT-6 reapplies the stronger boundary.
    payload={'evidence_type':'public_record','title':'<script>unsafe title</script>','summary':'Public summary','source_name':'Public source','source_locator':'record:1','origin':'public_osint','metadata_json':{'nested':{'client_secret':'hidden-at6-secret','debug':'hidden-at6-debug','public':'retain'}}}
    result=ok(client.post(P+f'/claims/{row["id"]}/evidence/capture',json={'expected_version':row['version'],'evidence':payload,'link':{'stance':'context','directness':'context','rationale':'Explicit context'}}),201)
    ok(pin(client,c['id'],result['claim']),201)
    for fmt in ['markdown','html','json']:
        text=report(client,c['id'],fmt).text
        assert 'hidden-at6-secret' not in text and 'hidden-at6-debug' not in text
        if fmt=='html':assert '<script>' not in text and '&lt;script&gt;' in text
    assert 'retain' in report(client,c['id'],'json').text


def test_case_attribution_assets_and_typed_routes(ui_client):
    client,_=ui_client
    assert client.get('/static/js/case_attribution.js').status_code==200
    schema=client.get('/openapi.json').json();operations=schema['paths'][P+'/cases/{case_id}/references']
    assert set(operations)=={'get','post'}
    for op in operations.values():assert any(v.get('content',{}).get('application/json',{}).get('schema',{}).get('$ref') for k,v in op['responses'].items() if k.startswith('2'))


@pytest.mark.parametrize('fmt',['markdown','html','json','pdf'])
def test_every_format_keeps_pin_after_rejection(api,material,fmt,monkeypatch):
    client,_=api;c,row=material;ok(pin(client,c['id'],row),201);ok(assess(client,row,'rejected'))
    paragraphs=[]
    if fmt=='pdf':
        from reportlab.platypus import Paragraph
        original=Paragraph.__init__
        def record(self,text,*args,**kwargs):paragraphs.append(text);original(self,text,*args,**kwargs)
        monkeypatch.setattr(Paragraph,'__init__',record)
    response=report(client,c['id'],fmt);assert response.status_code==200
    if fmt=='json':
        item=response.json()['attribution']['references'][0]
        assert item['pinned']['claim']['assessment']=='supported' and item['current']['claim']['assessment']=='rejected'
    else:
        text='\n'.join(paragraphs) if fmt=='pdf' else response.text
        assert 'Pinned assessment: supported' in text and 'Current assessment: rejected' in text and 'Contradicting evidence' in text


def test_no_hidden_first_page_limit_on_pinned_contradictions(api):
    from greedy_collector.attribution.service import AttributionService
    from tests.test_attribution_api import material as capture,role
    client,engine=api;c=case(client);row=claim(client)
    with Session(engine) as db:
        svc=AttributionService(db)
        for index in range(51):row=svc.create_and_link_evidence(row['id'],capture(title=f'Test citation {index}'),role('contradicts' if index==50 else 'supports'),expected_version=row['version'])['claim']
    saved=ok(pin(client,c['id'],row),201)
    assert len(saved['pinned']['links'])==51 and saved['pinned_evidence_counts']['contradicts']==1
    ref=report(client,c['id'],'json').json()['attribution']['references'][0]
    assert len(ref['evidence'])==51 and any(r['capture']['title']=='Test citation 50' and r['pinned_link']['stance']=='contradicts' for r in ref['evidence'])


def test_malformed_pin_report_error_is_safe(api,material):
    client,engine=api;c,row=material;saved=ok(pin(client,c['id'],row),201)
    with Session(engine) as db:db.get(CaseEntity,saved['id']).metadata_json={'attribution_pin':{'private':'SQL private-path-canary'}};db.commit()
    response=report(client,c['id'],'json');assert response.status_code==422
    assert 'private-path-canary' not in response.text and 'SQL' not in response.text


def test_entity_archival_does_not_rewrite_pin(api,material):
    client,_=api;c,row=material;e=ok(client.get(P+'/entities/'+row['entity_id']));saved=ok(pin(client,c['id'],e,'entity'),201)
    ok(client.post(P+'/entities/'+e['id']+'/archive',json={'expected_version':e['version'],'reason':'Later archival'}))
    current=refs(client,c['id'])['items'][0]
    assert current['pinned']==saved['pinned'] and current['current']['entity']['archived_at']
    assert 'Current entity:' in report(client,c['id'],'markdown').text


def test_pin_does_not_expose_removal_or_attribution_delete(api,material):
    client,engine=api;c,row=material;saved=ok(pin(client,c['id'],row),201);before=counts(engine)
    assert client.delete(P+f'/cases/{c["id"]}/references').status_code==405
    assert counts(engine)==before
