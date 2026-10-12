"""AT-7 source/claim integration over isolated real services; fixtures stay here."""
import json
import pytest
from sqlalchemy.orm import Session
from greedy_collector.attribution.service import AttributionService
from greedy_collector.models import AttributionEvidence, Case
from greedy_collector.attribution.cases import CaseAttributionService
from greedy_collector.attribution.reporting import attribution_lines
from greedy_collector.sanctions.service import SanctionsRegistry
from tests.test_attribution import svc, entity
from tests.test_attribution_api import api, migrated_template, claim, attach, assess, ok, API, P
from tests.test_public_capture import captured, capture, preview, review
from tests.test_public_capture_network import wire
from tests.test_broad_discovery import env, unrelated, BTC, review as review_observation
from tests.test_discovery_local_manual import run
from tests.test_sanctions_registry import FixtureSource, source, ETH


def test_alias_search_is_normalized_and_never_merges_entities(svc):
    first=entity(svc,canonical_name='Different canonical name',aliases=['Éxample Alias', '100% literal'])
    second=entity(svc,canonical_name='Other entity',aliases=['Éxample Alias'])
    assert {r['id'] for r in svc.list_entities(search='éXAMPLE alias')['items']}=={first['id'],second['id']}
    assert svc.list_entities(search='100%')['items'][0]['id']==first['id']
    assert svc.list_entities(search='missing')['total']==0


def capture_claims(e):
    with e.db() as db:
        service=AttributionService(db)
        target=service.create_entity({'canonical_name':'Synthetic AT7 entity'})
        return [service.create_claim({'entity_id':target['id'],'chain':'bitcoin',
            'subject_ref':BTC,
            'relationship':relationship,'scope_note':'Explicit synthetic scoped assertion'})
            for relationship in ('controlled_by','publicly_declared_by')]


def promote_capture(e,c,row,**extra):
    return e.c.post(API+'/discovery/public-captures/'+c['id']+'/promote',json={
        'confirmed':True,'claim_id':row['id'],'expected_claim_version':row['version'],
        'expected_source_fingerprint':preview(e,c)['source_fingerprint'],
        'excerpt':c['origin']['wallet'],'link':{'stance':'supports','directness':'direct','rationale':'Analyst interpreted exact fixture source'},**extra})


def test_public_capture_reuses_immutable_material_across_claims(captured):
    e,w,o,_=captured;c=review(e,capture(e,o));a,b=capture_claims(e)
    one=ok(promote_capture(e,c,a),201);two=ok(promote_capture(e,c,b),201)
    assert one['promotion']['evidence_id']==two['promotion']['evidence_id']


def test_captured_source_can_be_assessed_with_explicit_reliability(captured):
    e,w,o,_=captured;c=review(e,capture(e,o));a,_=capture_claims(e)
    promoted=ok(promote_capture(e,c,a,source_reliability='reliable',reliability_rationale='Reviewed the primary captured source and exact identifier'),201)
    with e.db() as db:
        service=AttributionService(db);row=promoted['claim'];links=service.list_claim_evidence(row['id'])['items']
        result=service.change_assessment(row['id'],'supported','Scope justified by the synthetic primary source',
            expected_version=row['version'],reviewed_link_ids=[v['id'] for v in links],acknowledged_contradictions=[])
        assert result['assessment']=='supported'


def test_report_text_preserves_evidence_hash_and_metadata(api):
    client,_=api;row=claim(client);linked=attach(client,row);row=ok(assess(client,linked['claim']))
    case=ok(client.post(API+'/cases',json={'title':'Synthetic AT7 report'}))
    ok(client.post(P+f"/cases/{case['id']}/references",json={'reference_type':'attribution_claim','target_id':row['id'],'expected_version':row['version']}),201)
    evidence=ok(client.get(P+'/evidence/'+linked['link']['evidence_id']))
    text=client.get(API+f"/reports/{case['id']}?format=markdown").text
    assert evidence['content_sha256'] in text


def test_ofac_discovery_material_promotes_explicitly_with_snapshot(env):
    e=env
    fixture=FixtureSource(source())
    with e.db() as db:SanctionsRegistry(db,fixture).sync()
    before=unrelated(e)
    _,items=run(e.c,address=ETH,transforms=('wallet.ofac_sdn_match',))
    assert unrelated(e)==before
    observation=ok(e.c.get(API+'/discovery/observations/'+items[0]['observation']['id']))
    review_observation(e,observation)
    pv=ok(e.c.get(API+'/discovery/observations/'+observation['id']+'/promotion-preview'))
    assert pv['eligible'],pv
    with e.db() as db:
        service=AttributionService(db);target=service.create_entity({'canonical_name':'Explicit analyst-selected entity'})
        row=service.create_claim({'entity_id':target['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'controlled_by','scope_note':'This assertion is explicit; OFAC association alone is not ownership'})
    result=ok(e.c.post(API+'/discovery/observations/'+observation['id']+'/promote',json={
        'result_id':observation['result_id'],'claim_id':row['id'],'expected_claim_version':row['version'],
        'expected_source_fingerprint':pv['source_fingerprint'],'link':{'stance':'context','directness':'context','rationale':'OFAC source association as context only'}}),201)
    with e.db() as db:
        evidence=db.get(AttributionEvidence,result['promotion']['evidence_id'])
        snapshot=evidence.metadata_json['observation']['source_snapshot']
        assert snapshot['snapshot_sha256'] and snapshot['entity']['programs']
        assert snapshot['identifier']['raw_value']==ETH
        assert snapshot['listing_state']=='CURRENTLY_LISTED'
        assert result['claim']['assessment']=='unassessed'
        preserved=AttributionService(db).get_evidence(evidence.id)
    fixture.data=source([(3,'Replacement fixture',['CYBER2'],[('ETH','0x'+'cd'*20)])])
    with e.db() as db:
        SanctionsRegistry(db,fixture).sync()
        assert AttributionService(db).get_evidence(preserved['id'])==preserved
        from greedy_collector.attribution.reporting import provenance_lines
        text='\n'.join(provenance_lines(preserved))
        assert snapshot['snapshot_sha256'] in text and 'CURRENTLY_LISTED' in text


@pytest.mark.parametrize('reliability',['reliable','uncertain','unreliable'])
def test_capture_quality_cannot_be_assigned_without_rationale(captured,reliability):
    e,w,o,_=captured;c=review(e,capture(e,o));a,_=capture_claims(e);before=unrelated(e)
    assert promote_capture(e,c,a,source_reliability=reliability).status_code==422
    assert unrelated(e)==before


def test_capture_loss_recapture_and_contradiction_preserve_case_evidence(captured):
    e,w,o,_=captured;c=review(e,capture(e,o));a,_=capture_claims(e)
    promoted=ok(promote_capture(e,c,a,source_reliability='reliable',reliability_rationale='Exact primary source reviewed'),201)
    with e.db() as db:
        service=AttributionService(db);row=promoted['claim'];links=service.list_claim_evidence(row['id'])['items']
        row=service.change_assessment(row['id'],'supported','Explicit synthetic supported assertion',
            expected_version=row['version'],reviewed_link_ids=[v['id'] for v in links],acknowledged_contradictions=[])
        db.add(Case(id='at7-case',title='AT7 historical source'));db.commit()
        pinned=CaseAttributionService(db).add_reference('at7-case','attribution_claim',row['id'],expected_version=row['version'])
        original=service.get_evidence(promoted['promotion']['evidence_id'])
        counter=service.create_and_link_evidence(row['id'],{
            'evidence_type':'public_record','title':'Conflicting fixture','summary':'A contradiction remains visible',
            'source_name':'Synthetic counter-source','source_locator':'fixture:contradiction','origin':'public_osint'},
            {'stance':'contradicts','directness':'direct','rationale':'Conflicts with the assertion'},expected_version=row['version'])
        all_links=service.list_claim_evidence(row['id'])['items']
        rejected=service.change_assessment(row['id'],'rejected','Explicit rejection rationale',
            expected_version=counter['claim']['version'],reviewed_link_ids=[v['id'] for v in all_links],
            acknowledged_contradictions=[counter['link']['id']],conflict_discussion='Contradiction assessed, not removed')
        assert rejected['assessment']=='rejected' and len(all_links)==2
    w.body+=b'<p>Changed source</p>';later=capture(e,o)
    assert later['body_sha256']!=c['body_sha256']
    w.status=404;failed=capture(e,o);assert failed['status']=='failed'
    with e.db() as db:
        service=AttributionService(db)
        assert service.get_evidence(original['id'])==original
        material=CaseAttributionService(db).report_references('at7-case')
        assert material['references'][0]['pinned']==pinned['pinned']
        assert material['references'][0]['pinned']['claim']['assessment']=='supported'
        assert material['references'][0]['current']['claim']['assessment']=='rejected'
        text='\n'.join(attribution_lines(material))
        for value in [c['id'],c['body_sha256'],original['content_sha256'],c['requested_url'],c['final_url']]:
            assert value in text


def test_ofac_other_chain_cannot_supply_direct_support(env):
    e=env
    with e.db() as db:SanctionsRegistry(db,FixtureSource(source())).sync()
    _,items=run(e.c,chain='base',address=ETH,transforms=('wallet.ofac_sdn_match',))
    observation=ok(e.c.get(API+'/discovery/observations/'+items[0]['observation']['id']))
    review_observation(e,observation)
    pv=ok(e.c.get(API+'/discovery/observations/'+observation['id']+'/promotion-preview'))
    assert pv['eligible'] and pv['context_only']
    with e.db() as db:
        service=AttributionService(db);target=service.create_entity({'canonical_name':'Synthetic Base assertion'})
        row=service.create_claim({'entity_id':target['id'],'chain':'base','subject_ref':ETH,'relationship':'controlled_by','scope_note':'No Ethereum/Base identity equivalence'})
    body={'result_id':observation['result_id'],'claim_id':row['id'],'expected_claim_version':row['version'],
        'expected_source_fingerprint':pv['source_fingerprint'],'link':{'stance':'supports','directness':'direct','rationale':'Must reject this chain-incompatible source'}}
    before=unrelated(e)
    assert e.c.post(API+'/discovery/observations/'+observation['id']+'/promote',json=body).status_code==422
    assert unrelated(e)==before


def test_source_quality_is_a_description_not_identity_probability(svc):
    from greedy_collector.attribution.domain import EvidenceQualityInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):EvidenceQualityInput(source_reliability='95%',reliability_rationale='Unsupported probability')
    with pytest.raises(ValidationError):EvidenceQualityInput(confidence=.95)
