"""AT-5 real service/API transactions over migrated temporary SQLite only."""
from datetime import datetime,timezone
import json
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from tests.test_attribution_api import api,migrated_template,claim,ok,P,ETH
from greedy_collector.models import Label,KycMatch,KycScreeningRun,AttributionEntity,AttributionClaim,AttributionEvidence,AttributionClaimEvidence,AttributionEvent,RiskResult
from greedy_collector.attribution.handoff import EvidenceHandoffService
from greedy_collector.attribution.domain import Conflict
from tests.test_ui import ui_client,no_monitoring


@pytest.fixture
def sources(api):
    client,engine=api
    with Session(engine) as db:
        label=Label(chain='ethereum',address=ETH,label='Synthetic source annotation',type='Exchange',source='Manual analyst label',confidence=.9,last_updated=datetime(2025,1,2,tzinfo=timezone.utc))
        run=KycScreeningRun(query={'name':'Synthetic subject','domain':None},checked_sources=[{'id':'opensanctions'}])
        db.add_all([label,run]);db.flush()
        match=KycMatch(run_id=run.id,source='opensanctions',subject_name='Synthetic subject',match_score=.88,match_rationale='Synthetic public record context',source_url='https://example.invalid/record',categories=['registry'],source_data={'public':'Retain this','nested':{'api_key':'never-store','client_secret':'never-store-two','debug':'internal trace','url':'https://name:password@example.invalid/a?token=hidden&record=7#password=hidden'}},review_status='Potential match')
        db.add(match);db.commit()
        return {'label':label.id,'research':match.id}


def preview(client,kind,identifier):return ok(client.get(P+f'/evidence/sources/{kind}/{identifier}'))
def handoff(client,row,kind,identifier,stance='supports',**overrides):
    data={'expected_version':row['version'],'expected_source_fingerprint':preview(client,kind,identifier)['source_fingerprint'],
          'link':{'stance':stance,'directness':'context' if stance=='context' else 'direct','rationale':'Explicit relevance to this claim'},**overrides}
    return client.post(P+f'/claims/{row["id"]}/evidence/from-{kind}/{identifier}',json=data)


def counts(engine):
    with Session(engine) as db:return [db.scalar(select(func.count()).select_from(model)) for model in (AttributionEntity,AttributionClaim,AttributionEvidence,AttributionClaimEvidence,AttributionEvent,RiskResult)]


@pytest.mark.parametrize('kind',['label','research'])
@pytest.mark.parametrize('stance',['supports','contradicts','context'])
def test_handoff_stances_events_and_boundaries(api,sources,kind,stance):
    client,engine=api;row=claim(client);before=counts(engine)
    result=ok(handoff(client,row,kind,sources[kind],stance),201)
    assert result['link']['stance']==stance
    assert result['claim']['assessment']=='unassessed' and result['claim']['needs_review']
    assert result['claim']['version']==row['version']+1
    after=counts(engine);assert after==[before[0],before[1],before[2]+1,before[3]+1,before[4]+2,before[5]]
    capture=ok(client.get(P+'/evidence/'+result['link']['evidence_id']))
    assert capture['collection_method']==('label_snapshot' if kind=='label' else 'research_snapshot')
    assert capture['origin']==('analyst_added' if kind=='label' else 'public_osint')
    assert capture['source_reliability']=='unassessed'
    assert capture['metadata_json']['record']['id']==sources[kind]
    assert capture['captured_at'] and capture['content_sha256']
    events=ok(client.get(P+f'/claims/{row["id"]}/events'))['items'];assert events[-1]['event_type']=='evidence_linked'
    assert ok(client.get(P+f'/evidence/{capture["id"]}/events'))['items'][0]['event_type']=='created'


@pytest.mark.parametrize('kind',['label','research'])
def test_snapshot_immutable_after_source_change_and_new_capture(api,sources,kind):
    client,engine=api;row=claim(client)
    result=ok(handoff(client,row,kind,sources[kind]),201)
    identifier=result['link']['evidence_id'];old=ok(client.get(P+'/evidence/'+identifier))
    with Session(engine) as db:
        if kind=='label':
            record=db.get(Label,sources[kind]);record.confidence=.1;record.last_updated=datetime(2026,2,3,tzinfo=timezone.utc)
        else:record=db.get(KycMatch,sources[kind]);record.review_status='False positive'
        db.commit()
    assert ok(client.get(P+'/evidence/'+identifier))==old
    newer=ok(handoff(client,result['claim'],kind,sources[kind]),201)
    assert newer['link']['evidence_id']!=identifier
    record=old['metadata_json']['record']
    if kind=='label':
        assert record['confidence']==.9 and record['source']=='Manual analyst label'
        assert record['last_updated']=='2025-01-02T00:00:00+00:00'
        assert record['chain']=='ethereum' and record['address']==ETH
    else:
        assert record['review_status']=='Potential match' and record['match_score']==.88
        assert record['categories']==['registry'] and old['metadata_json']['run']['query']['name']=='Synthetic subject'


@pytest.mark.parametrize('kind',['label','research'])
def test_duplicate_snapshot_active_and_withdrawn(api,sources,kind):
    client,engine=api;row=claim(client);result=ok(handoff(client,row,kind,sources[kind]),201);before=counts(engine)
    error=ok(handoff(client,result['claim'],kind,sources[kind]),409)
    assert error['detail']['existing_id']==result['link']['id'];assert counts(engine)==before
    withdrawn=ok(client.post(P+f'/claims/{row["id"]}/evidence/{result["link"]["id"]}/withdraw',json={'expected_version':result['claim']['version'],'reason':'Retain history'}))
    before=counts(engine);ok(handoff(client,withdrawn['claim'],kind,sources[kind]),409);assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
def test_missing_source_no_fake_browser_fallback(api,kind):
    client,engine=api;row=claim(client);before=counts(engine)
    ok(client.get(P+f'/evidence/sources/{kind}/missing'),404)
    result=client.post(P+f'/claims/{row["id"]}/evidence/from-{kind}/missing',json={'expected_version':row['version'],'expected_source_fingerprint':'a'*64,'link':{'stance':'context','directness':'context','rationale':'Explicit'}})
    ok(result,404);assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
def test_stale_claim_and_source_rollback(api,sources,kind):
    client,engine=api;row=claim(client);before=counts(engine)
    ok(handoff(client,row,kind,sources[kind],expected_version=9),409);assert counts(engine)==before
    ok(handoff(client,row,kind,sources[kind],expected_source_fingerprint='0'*64),409);assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
def test_late_link_failure_rolls_back_capture_and_event(api,sources,kind,monkeypatch):
    client,engine=api;row=claim(client);before=counts(engine)
    def fail(*args,**kwargs):raise Conflict('Synthetic late failure')
    monkeypatch.setattr(EvidenceHandoffService,'_link',fail)
    ok(handoff(client,row,kind,sources[kind]),409);assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
@pytest.mark.parametrize('bad',[{'link':{'stance':'invalid','directness':'direct','rationale':'Reason'}},{'link':{'stance':'context','directness':'direct','rationale':'Reason'}},{'link':{'stance':'supports','directness':'invalid','rationale':'Reason'}},{'source_snapshot':{'label':'Forged'}}])
def test_invalid_handoff_and_forged_snapshots(api,sources,kind,bad):
    client,engine=api;row=claim(client);before=counts(engine)
    ok(handoff(client,row,kind,sources[kind],**bad),422);assert counts(engine)==before


def test_sanitized_research_snapshot(api,sources):
    client,engine=api;row=claim(client);result=ok(handoff(client,row,'research',sources['research']),201)
    capture=ok(client.get(P+'/evidence/'+result['link']['evidence_id']));text=json.dumps(capture)
    for secret in ['never-store','never-store-two','internal trace','name:password','token=hidden','password=hidden']:assert secret not in text
    record=capture['metadata_json']['record'];assert record['source_data']['public']=='Retain this'
    assert record['source_data']['nested']['url']=='https://example.invalid/a?record=7'


def test_label_chain_scope_and_any(api,sources):
    client,engine=api;row=claim(client)
    with Session(engine) as db:
        label=db.get(Label,sources['label']);label.chain='bitcoin';db.commit()
    ok(handoff(client,row,'label',sources['label']),422)
    with Session(engine) as db:
        label=db.get(Label,sources['label']);label.chain='any';db.commit()
    ok(handoff(client,row,'label',sources['label'],'context'),201)


def test_contradiction_preserves_assessment(api,sources):
    client,_=api;row=claim(client)
    first=ok(handoff(client,row,'label',sources['label']),201)
    row=ok(client.post(P+f'/claims/{row["id"]}/assessment',json={'expected_version':first['claim']['version'],'assessment':'possible','rationale':'Explicit provisional assessment','reviewed_link_ids':[first['link']['id']],'acknowledged_contradictions':[]}))
    result=ok(handoff(client,row,'research',sources['research'],'contradicts'),201)
    assert result['claim']['assessment']=='possible' and result['claim']['needs_review']


@pytest.mark.parametrize('state',['archived','missing'])
def test_claim_state(api,sources,state):
    client,engine=api;row=claim(client)
    if state=='archived':row=ok(client.post(P+f'/claims/{row["id"]}/archive',json={'expected_version':1,'reason':'Archive'}))
    else:row['id']='missing'
    before=counts(engine);ok(handoff(client,row,'label',sources['label']),409 if state=='archived' else 404);assert counts(engine)==before


@pytest.mark.parametrize('invalid',['manual','malformed','oversized','unavailable'])
def test_ineligible_source(api,sources,invalid):
    client,engine=api;row=claim(client)
    with Session(engine) as db:
        match=db.get(KycMatch,sources['research'])
        if invalid=='manual':match.source='opencorporates'
        elif invalid=='malformed':match.source_data=[]
        elif invalid=='unavailable':db.get(KycScreeningRun,match.run_id).checked_sources=[]
        else:match.source_data={'payload':'x'*33000}
        db.commit()
    before=counts(engine);ok(client.get(P+'/evidence/sources/research/'+sources['research']),422);assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
def test_preview_does_not_write_and_source_race_conflicts(api,sources,kind):
    client,engine=api;row=claim(client);before=counts(engine);old=preview(client,kind,sources[kind]);assert counts(engine)==before
    with Session(engine) as db:
        if kind=='label':db.get(Label,sources[kind]).label='Revised annotation'
        else:db.get(KycMatch,sources[kind]).review_status='Confirmed source match'
        db.commit()
    ok(handoff(client,row,kind,sources[kind],expected_source_fingerprint=old['source_fingerprint']),409)
    assert counts(engine)==before


@pytest.mark.parametrize('kind',['label','research'])
def test_unmigrated_handoff_is_nonfatal(ui_client,kind):
    client,_=ui_client
    assert client.get(P+f'/evidence/sources/{kind}/missing').status_code==503
    response=client.post(P+f'/claims/missing/evidence/from-{kind}/missing',json={'expected_version':1,'expected_source_fingerprint':'a'*64,'link':{'stance':'context','directness':'context','rationale':'Explicit'}})
    assert response.status_code==503 and response.json()['detail']['code']=='schema_unavailable'
    for route in ['/','/health','/api/greedy-collector/labels','/api/greedy-collector/kyc/sources']:assert client.get(route).status_code==200


def test_handoff_frontend_surface(ui_client):
    client,_=ui_client
    script=client.get('/static/js/attribution_handoff.js');assert script.status_code==200
    for value in ['Use as attribution evidence','Choose claim','Confirm capture','expected_source_fingerprint','snapshotProvenance','readPage','Create attribution claim']:
        assert value in script.text
    assert "evidenceHandoffButton('label',row.id)" in client.get('/static/js/labels.js').text
    research=client.get('/static/js/research.js').text
    assert "source.mode==='api'" in research and "evidenceHandoffButton('research',row.id)" in research
    for name in ['stance','directness']:
        assert f"Choose {name}" in client.get('/static/js/attribution_forms.js').text


def test_configured_secret_and_url_sanitization(api,sources,monkeypatch):
    from greedy_collector.config import get_settings
    client,engine=api;row=claim(client);monkeypatch.setattr(get_settings(),'etherscan_api_key','configured-at5-canary')
    with Session(engine) as db:
        match=db.get(KycMatch,sources['research']);match.source_url='https://name:pass@example.invalid/record?api_key=configured-at5-canary&record=8#access_token=hidden'
        match.source_data={'text':'configured-at5-canary','private_key':'secret-material','public':'preserved'};db.commit()
    result=ok(handoff(client,row,'research',sources['research']),201)
    capture=ok(client.get(P+'/evidence/'+result['link']['evidence_id']))
    assert capture['source_url']=='https://example.invalid/record?record=8'
    for value in ['configured-at5-canary','secret-material','name:pass','hidden']:assert value not in json.dumps(capture)


def test_captured_source_delete_is_restricted(api,sources):
    from sqlalchemy.exc import IntegrityError
    client,engine=api;row=claim(client);result=ok(handoff(client,row,'label',sources['label']),201)
    with Session(engine) as db:
        db.delete(db.get(Label,sources['label']))
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()
    assert client.get(P+'/evidence/'+result['link']['evidence_id']).status_code==200


def test_handoff_preserves_existing_risk_and_never_calls_providers(api,sources,monkeypatch):
    from unittest.mock import AsyncMock
    from greedy_collector.router import service
    from greedy_collector.chains import BitcoinAdapter,EthereumAdapter
    client,engine=api;row=claim(client)
    prohibited=AsyncMock(side_effect=AssertionError('No provider calls during handoff'))
    monkeypatch.setattr(service.kyc_engine,'screen',prohibited)
    monkeypatch.setattr(BitcoinAdapter,'lookup_address',prohibited)
    monkeypatch.setattr(EthereumAdapter,'lookup_address',prohibited)
    with Session(engine) as db:
        db.add(RiskResult(chain='ethereum',address=ETH,score=9,level='Low',findings=[{'rule_id':'retained-test-context'}]));db.commit()
    for kind in ['label','research']:row=ok(handoff(client,row,kind,sources[kind],'context'),201)['claim']
    prohibited.assert_not_called()
    with Session(engine) as db:
        risk=db.scalar(select(RiskResult));assert (risk.score,risk.level,risk.findings)==(9,'Low',[{'rule_id':'retained-test-context'}])
