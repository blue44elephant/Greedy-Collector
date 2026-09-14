"""Explicit local persistence commands versus existing API workflows; no live HTTP."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from pydantic import ValidationError
from sqlalchemy import select,func,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from greedy_collector.chains import BitcoinAdapter,EthereumAdapter
from greedy_collector.discovery.domain import DiscoveryError,Conflict,clean
from greedy_collector.discovery.registry import Registry,REGISTRY
from greedy_collector.models import (Label,DiscoveryRun,DiscoveryRunSource,DiscoveryReview,
    DiscoveryRunItem,DiscoveryObservation,DiscoverySubject,DiscoveryResult)
from tests.test_discovery import svc,subject,run,start,record,batch,saved,counts,ETH,BTC
from tests.test_attribution_api import api,migrated_template,ok,API
from tests.test_research_ui import research_provider

def empty_discovery(engine):
    with Session(engine) as db:
        for model in (DiscoverySubject,DiscoveryRun,DiscoveryResult,DiscoveryObservation):
            assert db.scalar(select(func.count()).select_from(model))==0

def test_labels_and_research_do_not_start_discovery(api,research_provider):
    client,engine=api
    ok(client.post(API+'/labels/manual',json={'chain':'bitcoin','address':BTC,'label':'Synthetic annotation','type':'Unknown'}))
    empty_discovery(engine)
    result=ok(client.post(API+'/kyc/screen',json={'name':'Test Company'}))
    assert result['matches'];empty_discovery(engine)

@pytest.mark.parametrize('chain,address,adapter',[('bitcoin',BTC,BitcoinAdapter),('ethereum',ETH,EthereumAdapter)])
def test_real_wallet_service_never_starts_discovery(api,monkeypatch,chain,address,adapter):
    client,engine=api
    monkeypatch.setattr(adapter,'lookup_address',AsyncMock(return_value={'balance_native':'1','source_api':'test-only'}))
    monkeypatch.setattr(adapter,'transactions',AsyncMock(return_value=[]))
    result=ok(client.post(API+'/lookup/address',json={'chain':chain,'address':address}))
    assert result['address']['chain']==chain
    empty_discovery(engine)

def test_stored_label_context_requires_explicit_material(svc):
    label=Label(chain='ethereum',address=ETH.lower(),label='Synthetic annotation',type='Unknown',source='Test only',confidence=.5)
    svc.db.add(label);svc.db.commit()
    assert svc.list_runs()['total']==0 and svc.db.scalar(select(func.count()).select_from(DiscoveryResult))==0
    queried=subject(svc)
    row=svc.create_run(queried['id'],[{'transform_id':'wallet.local_labels','source_id':'gc_labels'}],idempotency_key='local')
    row=start(svc,row)
    value={'kind':'candidate_evidence','predicate':'locally_labeled_as',
        'from':{'kind':'blockchain_address','namespace':'ethereum','value':ETH},
        'to':{'kind':'annotation','namespace':'gc-label','value':label.id},
        'fact_key':{'label':label.label,'type':label.type},
        'observation':{'kind':'local_label_snapshot','source_record_key':label.id,'source_locator':'label:'+label.id,
            'title':'Stored label context','summary':label.label,'retrieved_at':datetime.now(timezone.utc),
            'origin_label_id':label.id,'source_snapshot':{'label':label.label,'confidence':label.confidence}}}
    data=batch(svc,row,[value]);ob=svc.get_observation(data['observation_ids'][0])
    assert ob['origin_label_id']==label.id and ob['verification']=='not_checked'
    assert svc.run_items(row['id'])['items'][0]['inclusion_kind']=='local'
    assert data['source']['expires_at'] is None
    with pytest.raises(IntegrityError):svc.db.execute(text('DELETE FROM labels WHERE id=:id'),{'id':label.id})
    svc.db.rollback()

@pytest.mark.parametrize('table,operation',[(table,op) for table in ['reviews','run_items'] for op in ['update','delete','replace_pk','replace_unique']])
def test_immutable_membership_and_review_guards(svc,table,operation):
    _,ob=saved(svc);r=svc.get_result(ob['result_id'])
    svc.review(r['id'],ob['id'],'relevant','Test review',expected_version=r['version'],expected_source_fingerprint=ob['content_sha256'])
    model=DiscoveryReview if table=='reviews' else DiscoveryRunItem
    values=dict(svc.db.execute(select(model.__table__)).mappings().one())
    original=deepcopy(values)
    with pytest.raises(IntegrityError):
        if operation=='delete':svc.db.execute(model.__table__.delete())
        elif operation=='update':svc.db.execute(model.__table__.update().values(**values))
        else:
            if operation=='replace_unique':
                if table=='reviews':values['id']='new-review-id'
                else:values['observation_id']='new-observation-id'
            svc.db.execute(model.__table__.insert().prefix_with('OR REPLACE').values(**values))
    svc.db.rollback()
    assert dict(svc.db.execute(select(model.__table__)).mappings().one())==original

def test_late_review_failure_rolls_back_history_and_summary(svc,monkeypatch):
    _,ob=saved(svc);row=svc.get_result(ob['result_id']);before=counts(svc)
    def fail(*args,**kwargs):raise RuntimeError('late test-only failure')
    monkeypatch.setattr(svc,'get_result',fail)
    with pytest.raises(RuntimeError):svc.review(row['id'],ob['id'],'relevant','Test review',expected_version=row['version'],expected_source_fingerprint=ob['content_sha256'])
    assert counts(svc)==before
    assert svc.db.get(DiscoveryResult,row['id']).review_status=='unreviewed'

def test_cache_changed_policy_version_refresh_and_negative_cache(svc):
    first=start(svc,run(svc));batch(svc,first,[])
    target=run(svc,'new');sid=target['sources'][0]['id']
    candidate=svc.cache_candidate(sid)
    assert candidate['returned_count']==0
    assert datetime.fromisoformat(candidate['expires_at'])-datetime.fromisoformat(candidate['completed_at'])<=timedelta(hours=1)
    assert svc.cache_candidate(run(svc,'refresh',refresh=True)['sources'][0]['id']) is None
    original=svc.registry.transforms['wallet.public_code_mentions']
    svc.registry.transforms[original.id]=original.model_copy(update={'version':2})
    assert svc.cache_candidate(sid) is None
    svc.registry.transforms[original.id]=original
    source=svc.registry.sources['github'];svc.registry.sources['github']=source.model_copy(update={'storage_allowed':False})
    assert svc.cache_candidate(sid) is None

def test_manual_descriptor_and_unapproved_remote_do_not_produce_material(svc):
    row=svc.create_run(subject(svc)['id'],[{'transform_id':'wallet.manual_exact_web','source_id':'google'}],idempotency_key='manual')
    row=svc.transition_run(row['id'],'running',expected_version=row['version'])
    source=svc.transition_source(row['sources'][0]['id'],'manual_ready',expected_run_version=row['version'])
    assert source['requests_attempted']==source['units_consumed']==source['returned_count']==0
    assert svc.run_items(row['id'])['total']==0
    svc.registry=REGISTRY
    row=start(svc,run(svc,'unapproved'))
    with pytest.raises(DiscoveryError,match='retention'):batch(svc,row)
    assert svc.run_items(row['id'])['total']==0

def test_result_fact_change_and_atomic_second_record_failure(svc):
    row=start(svc,run(svc));one=record();two=deepcopy(one);two['fact_key']['path']='OTHER.md'
    result=batch(svc,row,[one,two]);assert len(result['observation_ids'])==2
    assert svc.db.scalar(select(func.count()).select_from(DiscoveryResult))==2
    row=start(svc,run(svc,'failed'));before=counts(svc)
    bad=record('bad');bad['observation']['origin_label_id']='not-present'
    with pytest.raises(DiscoveryError):batch(svc,row,[record('would be new'),bad])
    assert counts(svc)==before

def test_configured_token_encoded_redaction(monkeypatch):
    secret='synthetic +/ token';monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN',secret)
    assert clean({'context':secret,'encoded':quote(secret,safe='')})=={'context':'[redacted]','encoded':'[redacted]'}

def test_registry_rejects_predicate_endpoint_mismatch():
    values=REGISTRY.transforms['wallet.public_code_mentions'].model_dump();values['output_types']=('url',)
    with pytest.raises(ValidationError,match='predicate/type'):Registry(list(REGISTRY.sources.values()),[values])
