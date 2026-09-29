"""Real API/migration/persistence capture workflow with controlled HTTP fixtures."""
import json
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError
from alembic import command
import pytest
from tests.test_broad_discovery import env,lookup,unrelated,ok,P,BTC,ETH
from tests.test_public_capture_network import wire
from greedy_collector.discovery.capture.models import PublicSourceCapture as Capture
from greedy_collector.attribution.service import AttributionService
from greedy_collector.models import Case,CaseEntity,AttributionEvidence

@pytest.fixture
def captured(env,wire):
    row,snapshot=lookup(env)
    o=snapshot['groups'][0]['observations'][0]
    return env,wire,o,row

def capture(e,o):return ok(e.c.post(P+'/observations/'+o['id']+'/public-captures',json={'confirmed':True}),201)
def preview(e,c):return ok(e.c.get(P+'/public-captures/'+c['id']+'/promotion-preview'))
def review(e,c):return ok(e.c.post(P+'/public-captures/'+c['id']+'/review',json={'status':'relevant','note':'Reviewed the captured source; no ownership inference','expected_version':c['review']['sequence']}))

def test_explicit_capture_review_history_and_no_side_effects(captured):
    e,w,o,row=captured;before=unrelated(e)
    assert not w.calls
    assert e.c.post(P+'/observations/'+o['id']+'/public-captures',json={}).status_code==422
    assert not w.calls
    c=capture(e,o)
    assert c['status']=='captured' and c['wallet_present_in_capture'] and c['change_state']=='FIRST_CAPTURE'
    assert c['origin']['observation_id']==o['id'] and c['origin']['provider']=='brave_search'
    assert c['origin']['chain']=='bitcoin' and c['origin']['wallet']==BTC
    assert c['body_sha256'] and c['byte_count']==len(w.body) and c['http_status']==200 and c['retrieved_at']
    assert c['review']['status']=='unreviewed' and not preview(e,c)['eligible']
    reviewed=review(e,c);assert reviewed['review']['sequence']==1 and preview(e,c)['eligible']
    assert unrelated(e)==before
    with e.db() as db:assert db.get(Capture,c['id']).raw_body==w.body
    history=ok(e.c.get(P+'/observations/'+o['id']+'/public-captures'))
    assert history['total']==1 and 'text' not in history['items'][0] and 'raw_body' not in json.dumps(history)
    assert ok(e.c.get(P+'/observations/'+o['id']))['content_sha256']==o['content_sha256']


def test_change_detection_old_material_and_case_pin_immutable(captured):
    e,w,o,_=captured;first=capture(e,o);second=capture(e,o)
    assert first['id']!=second['id'] and second['change_state']=='UNCHANGED'
    assert second['previous_capture_id']==first['id']
    with e.db() as db:db.add(Case(id='capture-case',title='Explicit test case'));db.commit()
    pv=preview(e,first);pin=ok(e.c.post(P+'/public-captures/'+first['id']+'/cases/capture-case/pin',json={'excerpt':BTC,'expected_source_fingerprint':pv['source_fingerprint']}),201)
    old=ok(e.c.get(P+'/public-captures/'+first['id']))
    w.body+=b'<p>Changed page</p>';third=capture(e,o)
    assert third['change_state']=='CHANGED' and third['body_sha256']!=first['body_sha256']
    assert ok(e.c.get(P+'/public-captures/'+first['id']))==old
    with e.db() as db:assert db.get(CaseEntity,pin['id']).metadata_json==pin['metadata_json']
    for sql in ["UPDATE discovery_public_captures SET status='failed'","DELETE FROM discovery_public_captures","UPDATE case_entities SET metadata_json='{}' WHERE entity_type='public_source_capture'"]:
        with e.engine.connect() as db:
            with pytest.raises(IntegrityError,match='immutable'):db.execute(text(sql))
            db.rollback()
    with pytest.raises(RuntimeError,match='Retained'):command.downgrade(e.cfg,'20260928_01')


def test_wallet_absent_and_failed_capture_do_not_change_search(captured):
    e,w,o,_=captured;w.body=b'<p>The current page omits the wallet.</p>';c=capture(e,o)
    assert c['wallet_present_in_capture'] is False
    w.ip='127.0.0.1';failed=capture(e,o)
    assert failed['failure_reason']=='blocked_private_address' and failed['status']=='failed' and failed['wallet_present_in_capture'] is None
    review(e,failed);assert not preview(e,failed)['eligible']
    assert ok(e.c.get(P+'/observations/'+o['id']))['content_sha256']==o['content_sha256']


def test_explicit_promotion_literal_excerpt_and_chain_guard(captured):
    e,w,o,_=captured;c=review(e,capture(e,o));pv=preview(e,c)
    with e.db() as db:
        svc=AttributionService(db);entity=svc.create_entity({'canonical_name':'Test analyst entity'})
        claim=svc.create_claim({'entity_id':entity['id'],'chain':'bitcoin','subject_ref':BTC,'relationship':'operated_by','scope_note':'Explicit test claim'})
    before=unrelated(e)
    payload={'confirmed':True,'claim_id':claim['id'],'expected_claim_version':claim['version'],'expected_source_fingerprint':pv['source_fingerprint'],'excerpt':'fabricated text','link':{'stance':'context','directness':'context','rationale':'Source context only'}}
    assert e.c.post(P+'/public-captures/'+c['id']+'/promote',json=payload).status_code==422
    assert unrelated(e)==before
    payload['excerpt']=BTC
    promoted=ok(e.c.post(P+'/public-captures/'+c['id']+'/promote',json=payload),201)
    with e.db() as db:
        evidence=db.get(AttributionEvidence,promoted['promotion']['evidence_id'])
        assert evidence.origin=='public_osint' and evidence.excerpt==BTC
        assert evidence.metadata_json['capture']['body_sha256']==c['body_sha256']
        assert evidence.metadata_json['capture']['origin']['observation_id']==o['id']
    assert e.c.post(P+'/public-captures/'+c['id']+'/promote',json=payload).status_code==409
    after=unrelated(e)
    assert after['attribution_entities']==before['attribution_entities'] and after['attribution_claims']==before['attribution_claims']
    for name,count in before.items():
        if not name.startswith('attribution_'):assert after[name]==count


def test_evm_capture_context_is_chain_scoped(env,wire):
    e=env;e.state.rows[0]['description']=ETH;wire.body=ETH.encode();wire.headers={'content-type':'text/plain'}
    a,x=lookup(e,chain='ethereum',address=ETH);b,y=lookup(e,chain='base',address=ETH)
    ca=capture(e,x['groups'][0]['observations'][0]);cb=capture(e,y['groups'][0]['observations'][0])
    assert ca['wallet_present_in_capture'] and cb['wallet_present_in_capture']
    assert ca['origin']['chain']=='ethereum' and cb['origin']['chain']=='base'
    assert ca['origin']['result_id']!=cb['origin']['result_id']


def test_capture_graph_and_paginated_history(captured):
    e,w,o,row=captured
    ids=[capture(e,o)['id'] for _ in range(6)]
    graph=ok(e.c.get(P+'/runs/'+row['id']+'/graph'))
    nodes=[n for n in graph['items'] if n['type']=='public_capture']
    assert len(nodes)==5 and all(n['predicate']=='captured_as' for n in nodes)
    parent=next(n for n in graph['items'] if n['type']=='web_source')
    assert parent['capture_total']==6
    assert all(v['source']==parent['id'] for v in graph['edges'] if v['predicate']=='captured_as')
    page=ok(e.c.get(P+'/observations/'+o['id']+'/public-captures?limit=5'))
    rest=ok(e.c.get(P+'/observations/'+o['id']+'/public-captures?limit=5&offset=5'))
    assert len(page['items'])==5 and len(rest['items'])==1 and page['total']==6


def test_review_stale_and_append_only(captured):
    e,w,o,_=captured;c=capture(e,o);old=preview(e,c)
    reviewed=review(e,c)
    assert preview(e,c)['source_fingerprint']!=old['source_fingerprint']
    assert e.c.post(P+'/public-captures/'+c['id']+'/review',json={'status':'irrelevant','note':'stale','expected_version':0}).status_code==409
    for sql in ["UPDATE discovery_capture_reviews SET note='overwrite'","DELETE FROM discovery_capture_reviews","INSERT OR REPLACE INTO discovery_public_captures SELECT * FROM discovery_public_captures"]:
        with e.engine.connect() as db:
            with pytest.raises(IntegrityError,match='immutable'):db.execute(text(sql))
            db.rollback()


def test_capture_input_rejects_injected_url_headers_and_cross_origin(captured):
    e,w,o,_=captured;url=P+'/observations/'+o['id']+'/public-captures'
    assert e.c.post(url,json={'confirmed':True,'url':'http://127.0.0.1'}).status_code==422
    assert e.c.post(url,json={'confirmed':True,'headers':{'Authorization':'secret'}}).status_code==422
    assert e.c.post(url,json={'confirmed':True},headers={'Origin':'https://evil.example'}).status_code==403
    assert not w.calls


def test_wrong_wallet_claim_and_stale_review_cannot_promote(captured):
    e,w,o,_=captured;c=review(e,capture(e,o));pv=preview(e,c)
    with e.db() as db:
        svc=AttributionService(db);entity=svc.create_entity({'canonical_name':'Other claim entity'})
        claim=svc.create_claim({'entity_id':entity['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'operated_by','scope_note':'Other wallet'})
    before=unrelated(e)
    payload={'confirmed':True,'claim_id':claim['id'],'expected_claim_version':claim['version'],'expected_source_fingerprint':pv['source_fingerprint'],'excerpt':BTC,'link':{'stance':'context','directness':'context','rationale':'Context only'}}
    assert e.c.post(P+'/public-captures/'+c['id']+'/promote',json=payload).status_code==422
    assert unrelated(e)==before


def test_capture_migration_empty_roundtrip_and_foreign_keys(env):
    e=env
    with e.engine.connect() as db:
        assert db.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert db.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()=='20260929_01_public_source_capture'
    command.downgrade(e.cfg,'20260928_01');command.upgrade(e.cfg,'head')
    with e.engine.connect() as db:assert db.exec_driver_sql('SELECT COUNT(*) FROM discovery_public_captures').scalar_one()==0
