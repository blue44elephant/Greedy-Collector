"""Real historical analytical pins feed NARC-1 without provider requests."""
import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.test_narcotics import api, migrated_template, create, profile, related, fact, N, API, BTC, ETH, ok
from tests.test_case_completion import case_material, pin_all

def discovery(engine, status):
    from datetime import datetime, timezone
    from uuid import uuid4
    from greedy_collector.discovery.service import DiscoveryService
    from greedy_collector.discovery.execution_service import ExecutionService
    from greedy_collector.discovery.broad.service import BroadService
    from greedy_collector.discovery.broad.providers import normalize_result, DiscoveryQuery, DiscoveryObservation
    from greedy_collector.discovery.broad.models import Candidate
    with Session(engine) as db:
        ds=DiscoveryService(db);subject=ds.get_or_create_subject('blockchain_address','bitcoin',BTC)
        run=ds.create_run(subject['id'],[{'transform_id':'wallet.broad_web','source_id':'brave_search'}],idempotency_key=str(uuid4()),execution_policy={'broad':True})
        run=ds.transition_run(run['id'],'running',expected_version=run['version'])
        ds.transition_source(run['sources'][0]['id'],'running',expected_run_version=run['version']);run=ds.get_run(run['id'])
        record=normalize_result('brave_search',DiscoveryQuery('bitcoin',BTC),DiscoveryObservation('https://public.example/notice','Public test source',BTC+'; alias: greenfox;',1),datetime.now(timezone.utc).isoformat())
        ds.record_batch(run['sources'][0]['id'],[record],expected_run_version=run['version']);run=ds.get_run(run['id'])
        ds.transition_run(run['id'],'completed',expected_version=run['version'])
        bs=BroadService(db,ExecutionService(db))
        if status!='unreviewed':
            # Observation IDs are assigned by real record_batch, not provider normalization.
            snapshot=bs.snapshot(run['id'])
            for c in snapshot['candidates']:bs.review_candidate(c['id'],status,'Explicit fixture analyst review',c['version'])
        return run['id']

@pytest.mark.parametrize('status,expected',[('unreviewed','CONTEXT_ONLY'),('relevant','MODERATE')])
def test_real_discovery_candidates_review_boundary(api,status,expected):
    client,engine=api;a,b=create(client),create(client)
    from greedy_collector.discovery.broad.service import BroadService
    from greedy_collector.discovery.execution_service import ExecutionService
    for case in [a,b]:
        run_id=discovery(engine,status)
        with Session(engine) as db:BroadService(db,ExecutionService(db)).pin(case['id'],run_id)
    run=related(client,a,b)
    aliases=[l for l in run['links'] if l['link_type']=='EXACT_ALIAS_REUSE']
    assert aliases and all(l['strength']==expected for l in aliases)
    assert all(p['candidate_id'] and p['review_status']==status for l in aliases for p in l['provenance'])
    domain=next(l for l in run['links'] if l['link_type']=='DOMAIN_REUSE')
    assert domain['strength']==expected
    if status=='unreviewed':assert run['related_cases'][0]['similarity']['score'] is None

def test_source_backed_manual_unreviewed_alias_cannot_become_strong(api):
    client,engine=api;a,b=create(client),create(client)
    from greedy_collector.discovery.broad.service import BroadService
    from greedy_collector.discovery.execution_service import ExecutionService
    run_id=discovery(engine,'unreviewed')
    for case in [a,b]:
        with Session(engine) as db:ref=BroadService(db,ExecutionService(db)).pin(case['id'],run_id)
        profile(client,case,wallets=[],logistics=[],substances=[],fields={'vendor_alias':[fact('greenfox',kind='discovery_result',reference_id=ref['id'])]})
    run=related(client,a,b)
    assert all(l['strength']=='CONTEXT_ONLY' for l in run['links'])

def test_entity_cluster_and_flow_preserve_real_pinned_states(case_material):
    client,engine,material=case_material;a,b=create(client),create(client)
    for case in [a,b]:pin_all(client,case['id'],material)
    run=related(client,a,b)
    entity=next(l for l in run['links'] if l['link_type']=='ATTRIBUTION_ENTITY_OVERLAP')
    assert entity['strength']=='MODERATE'
    assert all(p['claim']['assessment']=='supported' and p['evidence_state'] for p in entity['provenance'])
    assert any(l['link_type']=='TECHNICAL_CLUSTER_OVERLAP' and l['strength']=='STRONG' for l in run['links'])
    assert any(l['link_type']=='SHARED_COUNTERPARTY' for l in run['links'])
    graph=ok(client.post(N+'/nexus',json={'case_ids':[a['id'],b['id']],'link_run_ids':[run['id']]}))
    assert {'entity','technical_cluster','discovery_source','source_capture'}<={n['type'] for n in graph['nodes']}
    assert any(e['type']=='WALLET_IN_CLUSTER' for e in graph['edges'])
    score=ok(client.post(N+'/priority',json={'nexus_id':graph['id']}))
    assert any(m['independent_source_count']>0 for m in score['metrics'])

def test_existing_risk_and_attribution_rows_are_unchanged_by_network_analysis(case_material):
    from sqlalchemy import text
    client,engine,m=case_material;a,b=create(client),create(client)
    for case in [a,b]:pin_all(client,case['id'],m)
    tables=['risk_results','attribution_entities','attribution_claims','attribution_evidence','attribution_claim_evidence','attribution_events']
    def snapshot():
        with engine.connect() as c:return {t:sorted(c.execute(text('SELECT * FROM '+t)).all(),key=repr) for t in tables}
    before=snapshot();run=related(client,a,b)
    graph=ok(client.post(N+'/nexus',json={'case_ids':[a['id'],b['id']],'link_run_ids':[run['id']]}))
    ok(client.post(N+'/priority',json={'nexus_id':graph['id']}))
    assert snapshot()==before

def test_rejected_entity_claims_remain_context(case_material):
    client,engine,m=case_material;a,b=create(client),create(client)
    ok(client.post(API+'/attribution/cases/'+a['id']+'/references',json={'reference_type':'attribution_claim','target_id':m['claim_id'],'expected_version':m['claim_version']}),201)
    from greedy_collector.attribution.service import AttributionService
    with Session(engine) as db:
        svc=AttributionService(db);claim=svc.get_claim(m['claim_id']);links=svc.list_claim_evidence(claim['id'])['items']
        changed=svc.change_assessment(claim['id'],'rejected','Explicit rejected fixture claim',expected_version=claim['version'],
            reviewed_link_ids=[l['id'] for l in links],acknowledged_contradictions=[l['id'] for l in links if l['stance']=='contradicts'],conflict_discussion='Conflict retained')
    ok(client.post(API+'/attribution/cases/'+b['id']+'/references',json={'reference_type':'attribution_claim','target_id':m['claim_id'],'expected_version':changed['version']}),201)
    link=next(l for l in related(client,a,b)['links'] if l['link_type']=='ATTRIBUTION_ENTITY_OVERLAP')
    assert link['strength']=='CONTEXT_ONLY'
    assert {p['claim']['assessment'] for p in link['provenance']}=={'supported','rejected'}

@pytest.mark.parametrize('format',['json','html','markdown','pdf'])
def test_narcotics_pins_reports_explanation_historical_bytes_and_redaction(api,format,monkeypatch):
    client,_=api;a,b=create(client),create(client)
    from greedy_collector.config import get_settings
    monkeypatch.setattr(get_settings(),'etherscan_api_key','narc1-secret-canary')
    profile(client,a,fields={'vendor_alias':[fact('greenfox')],'notes':[fact('<script>unsafe</script> narc1-secret-canary')]});profile(client,b)
    run=related(client,a,b)
    link=next(l for l in run['links'] if l['link_type']=='EXACT_WALLET_REUSE')
    ok(client.post(N+'/links/'+link['id']+'/reviews',json={'expected_sequence':0,'status':'RELEVANT','rationale':'Technical identifier; no ownership conclusion'}))
    graph=ok(client.post(N+'/nexus',json={'case_ids':[a['id'],b['id']],'link_run_ids':[run['id']]}))
    priority=ok(client.post(N+'/priority',json={'nexus_id':graph['id']}))
    for kind,identifier in [('mo_fingerprint',run['origin_fingerprint']['id']),('case_comparison',run['id']),('reviewed_link',link['id']),('nexus',graph['id']),('priority',priority['id'])]:
        ok(client.post(N+'/cases/'+a['id']+'/pins',json={'kind':kind,'reference_id':identifier}))
    first=client.get(API+'/reports/'+a['id']+'?format='+format);assert first.status_code==200
    if format!='pdf':
        assert 'narc1-secret-canary' not in first.text and 'same_cartel' not in first.text
        assert 'denominator' in first.text and 'leadership probability' in first.text
        if format=='html':assert '<script>unsafe' not in first.text and '&lt;script&gt;' in first.text
    if format=='json':assert first.json()['narcotics_profile']['revision']==1
    pinbefore=ok(client.get(API+'/cases/'+a['id']))['entities']
    profile(client,a,expected_revision=1,fields={'vendor_alias':[fact('later alias')]});related(client,a,b)
    assert ok(client.get(API+'/cases/'+a['id']))['entities']==pinbefore
    stored=client.get(API+'/cases/'+a['id']+'/reports/'+first.headers['x-report-id'])
    assert stored.content==first.content

def test_temporal_unknown_before_after():
    from greedy_collector.narcotics.domain import temporal
    a={'period_start':'2026-01','period_end':'2026-02'};b={'period_start':'2026-03','period_end':'2026-04'}
    assert temporal(a,b)=='BEFORE' and temporal(b,a)=='AFTER' and temporal(a,{})=='UNKNOWN'

def test_priority_bridge_and_independent_sources_are_bounded_and_reproducible():
    from greedy_collector.narcotics.domain import priority
    graph={'nodes':[{'id':str(i),'type':'wallet','label':str(i),'case_ids':['A','B'] if i==1 else ['A']} for i in range(3)],
        'edges':[{'source':str(i),'target':str(i+1),'provenance':[{'source_identity':'https://one.example/a'},{'source_identity':'https://one.example/b'},{'source_identity':'https://two.example/c'}]} for i in range(2)]}
    result=priority(graph);bridge=next(n for n in result if n['node_id']=='1')
    assert bridge['betweenness']==1 and bridge['independent_source_count']==2
    assert bridge['score']>next(n['score'] for n in result if n['node_id']=='0')
    assert result==priority(graph)
