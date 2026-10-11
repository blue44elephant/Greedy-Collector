"""ED-8A0 type/storage tests. Synthetic ENS material never leaves this module."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, DiscoverySubject, DiscoveryRun
from greedy_collector.discovery import enums
from greedy_collector.discovery.domain import (
    canonical_subject, canonical_ens_subject, result_identity, query_fingerprint,
    observation_fingerprint, ObservationInput, DiscoveryError,
)
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.registry import REGISTRY, Registry
from greedy_collector.discovery.runtime import DiscoveryRuntime
from greedy_collector.discovery.router import router, get_runtime
from greedy_collector.discovery.graph import graph_summary
from tests.test_discovery import ETH, BTC, record

P='/api/greedy-collector/discovery'


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args,**kwargs):raise AssertionError('ED-8A0 must not call a provider')
    for target in ('httpx.HTTPTransport.handle_request','httpx.AsyncHTTPTransport.handle_async_request','requests.Session.request'):
        monkeypatch.setattr(target,blocked)


def ens_registry():
    # A contract for persistence tests only: no executor or production source.
    source={**REGISTRY.sources['gc_labels'].model_dump(),'id':'test_ens_storage'}
    transform=dict(id='wallet.test_ens_storage',display_name='Test canonical endpoint',
        description='Test-only stored material',source_ids=(source['id'],),chains=('ethereum',),
        output_types=('ens_name',),result_kinds=('candidate_relationship',),predicates=('resolves_to',),
        observation_kinds=('name_service_record',),mode='local',cost_class='FREE_LOCAL',max_requests=0)
    return Registry([s.model_dump() for s in REGISTRY.sources.values()]+[source],
                    [t.model_dump() for t in REGISTRY.transforms.values()]+[transform])


@pytest.fixture
def foundation():
    engine=create_fk_enabled_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield DiscoveryService(db,metadata_only=True,registry=ens_registry())
    finally:engine.dispose()


def ens_record(name='fixture.eth'):
    return dict(kind='candidate_relationship',predicate='resolves_to',
        **{'from':dict(kind='ens_name',namespace='ethereum',value=name),
           'to':dict(kind='blockchain_address',namespace='ethereum',value=ETH)},
        fact_key={'normalized_name':name},observation=dict(kind='name_service_record',
            source_record_key=name,source_locator='test-ens:'+name,title='Test stored canonical name',
            summary='Test storage only; no protocol verification is performed.',
            retrieved_at=datetime.now(timezone.utc),source_snapshot={'normalized_name':name}))


def store_ens(svc,name='fixture.eth'):
    root=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
    run=svc.create_run(root['id'],[dict(transform_id='wallet.test_ens_storage',source_id='test_ens_storage')],idempotency_key=uuid4().hex)
    run=svc.transition_run(run['id'],'running',expected_version=run['version'])
    svc.transition_source(run['sources'][0]['id'],'running',expected_run_version=run['version'])
    run=svc.get_run(run['id'])
    stored=svc.record_batch(run['sources'][0]['id'],[ens_record(name)],expected_run_version=run['version'])
    observation=svc.get_observation(stored['observation_ids'][0])
    current=svc.get_run(run['id'])
    svc.transition_run(run['id'],'completed',expected_version=current['version'])
    return run['id'],observation,svc.get_result(observation['result_id'])


def test_only_new_kind_and_pair_enabled():
    assert enums.SUBJECT_KINDS==('blockchain_address','url','domain','repository','annotation','ens_name')
    assert enums.PAIRS['resolves_to']==(('ens_name','blockchain_address'),)
    assert enums.PAIRS['locally_labeled_as']==(('blockchain_address','annotation'),)
    assert enums.PAIRS['repository_contains']==(('repository','blockchain_address'),)
    assert enums.RESULT_KINDS==('candidate_evidence','candidate_identifier','candidate_relationship')
    assert 'name_service_record' in enums.OBSERVATION_KINDS
    assert set(REGISTRY.transforms)=={'wallet.local_labels','wallet.manual_exact_web','wallet.public_code_mentions','wallet.ens_primary_name','wallet.manual_source_observation','wallet.graphsense_public_tags','wallet.broad_web','wallet.web_search.tavily','wallet.ofac_sdn_match'}


@pytest.mark.parametrize('value',['fixture.eth','é.eth','e\u0301.eth','MiXeD.eth','🦊.eth'])
def test_internal_canonical_input_preserved_without_claiming_normalization(foundation,value):
    expected=canonical_ens_subject('ethereum',value)
    row=foundation.get_or_create_subject('ens_name','ethereum',value)
    assert row['canonical_value']==row['display_value']==value
    assert row['identity_sha256']==expected['identity_sha256']
    assert foundation.get_or_create_subject('ens_name','ethereum',value)['id']==row['id']
    assert foundation.get_subject(row['id'])==row
    with pytest.raises(DiscoveryError,match='Only wallet'):
        foundation.create_run(row['id'],[],idempotency_key='not-a-root')


@pytest.mark.parametrize('namespace,value',[
    ('bitcoin','fixture.eth'),('sns','fixture.eth'),('ethereum',''),('ethereum',' '),
    ('ethereum',' fixture.eth'),('ethereum','fixture.eth '),('ethereum','a b.eth'),
    ('ethereum','a\x00.eth'),('ethereum','a\u200b.eth'),('ethereum','x'*2049),('ethereum',None),
])
def test_canonical_boundary_rejects_bad_namespace_whitespace_controls(namespace,value):
    with pytest.raises(DiscoveryError):canonical_ens_subject(namespace,value)


def test_unsupported_subject_kind_rejected_by_domain_and_database(foundation):
    with pytest.raises(DiscoveryError):canonical_subject('name_service','ethereum','fixture.eth')
    with pytest.raises(IntegrityError):
        foundation.db.execute(DiscoverySubject.__table__.insert().values(kind='name_service',namespace='ethereum',
            canonical_value='fixture.eth',display_value='fixture.eth',identity_sha256='0'*64))
    foundation.db.rollback()


def test_db_rejects_cross_namespace_ens(foundation):
    with pytest.raises(IntegrityError,match='ck_discovery_subjects_8'):
        foundation.db.execute(DiscoverySubject.__table__.insert().values(kind='ens_name',namespace='bitcoin',
            canonical_value='fixture.eth',display_value='fixture.eth',identity_sha256='0'*64))
    foundation.db.rollback()


def test_wallet_root_with_incoming_ens_relation_persists_and_deduplicates(foundation):
    first,ob,result=store_ens(foundation)
    second,again,repeated=store_ens(foundation)
    assert result['id']==repeated['id'] and result['identity_sha256']==repeated['identity_sha256']
    assert ob['id']!=again['id'] and ob['content_sha256']==again['content_sha256']
    assert result['review_status']=='unreviewed'
    assert foundation.get_subject(result['from_subject_id'])['kind']=='ens_name'
    assert result['to_subject_id']==result['query_subject_id']==foundation.get_run(first)['subject_id']
    _,_,changed=store_ens(foundation,'different.eth')
    assert changed['id']!=result['id']
    assert foundation.run_items(first)['items'][0]['observation_id']==ob['id']


@pytest.mark.parametrize('direction',['reverse','annotation','repository','bitcoin'])
def test_invalid_resolves_to_endpoints_rejected(foundation,direction):
    name=canonical_subject('ens_name','ethereum','fixture.eth')
    wallet=canonical_subject('blockchain_address','ethereum',ETH)
    start,end=name,wallet
    if direction=='reverse':start,end=wallet,name
    elif direction=='annotation':start=canonical_subject('annotation','gc-label','test')
    elif direction=='repository':start,end=canonical_subject('repository','github','123'),name
    else:end=canonical_subject('blockchain_address','bitcoin',BTC)
    with pytest.raises(DiscoveryError):result_identity(wallet,'candidate_relationship','resolves_to',start,end,{})


@pytest.mark.parametrize('predicate',['owned_by','operated_by','controlled_by','publicly_declared_by'])
def test_ownership_predicates_remain_rejected(predicate):
    name=canonical_subject('ens_name','ethereum','fixture.eth')
    wallet=canonical_subject('blockchain_address','ethereum',ETH)
    with pytest.raises(DiscoveryError):result_identity(wallet,'candidate_relationship',predicate,name,wallet,{})


def test_graph_retains_known_unrendered_page_membership(foundation):
    run,ob,result=store_ens(foundation)
    graph=graph_summary(foundation,run,metadata_only=True).model_dump()
    assert graph['total']==1 and graph['items']==[] and graph['edges']==[]
    assert graph['unrendered_results']==[dict(result_id=result['id'],observation_id=ob['id'],endpoint_type='ens_name',reason='presentation_not_implemented')]
    assert graph==graph_summary(foundation,run,metadata_only=True).model_dump()
    assert graph_summary(foundation,run,offset=1,metadata_only=True).unrendered_results==[]


def test_storage_has_no_other_subsystem_side_effects(foundation):
    tables=[t for t in Base.metadata.tables.values() if not t.name.startswith('discovery_')]
    before={t.name:foundation.db.execute(select(t)).all() for t in tables}
    store_ens(foundation)
    assert {t.name:foundation.db.execute(select(t)).all() for t in tables}==before


@pytest.fixture
def api(foundation):
    app=FastAPI();app.include_router(router,prefix='/api/greedy-collector')
    runtime=DiscoveryRuntime(sessionmaker(foundation.db.get_bind()),metadata_only=True)
    app.dependency_overrides[get_runtime]=lambda:runtime
    with TestClient(app) as client:yield client


@pytest.mark.parametrize('path',['/plan','/runs'])
@pytest.mark.parametrize('subject',[
    {'chain':'ethereum','address':'fixture.eth'},
    {'kind':'ens_name','namespace':'ethereum','value':'fixture.eth'},
])
def test_api_cannot_plan_or_run_an_ens_root(api,foundation,path,subject):
    data={'subject':subject,'selections':[{'transform_id':'wallet.local_labels'}]}
    if path=='/runs':data['expected_plan_fingerprint']='0'*64
    assert api.post(P+path,json=data).status_code==422
    assert foundation.db.scalars(select(DiscoveryRun)).all()==[]


@pytest.mark.parametrize('chain,address',[('bitcoin',BTC),('ethereum',ETH)])
def test_wallet_plan_and_openapi_root_contract_unchanged(api,chain,address):
    response=api.post(P+'/plan',json={'subject':{'chain':chain,'address':address},'selections':[{'transform_id':'wallet.local_labels'}]})
    assert response.status_code==200,response.text
    assert response.json()['selections'][0]['eligibility']=='eligible'
    schema=api.get('/openapi.json').json()['components']['schemas']['SubjectInput']
    assert set(schema['properties'])=={'chain','address'}
    assert schema['properties']['chain']['enum']==['bitcoin','ethereum','base','arbitrum','bsc','polygon','tron','solana','litecoin','monero']
    ens=next(t for t in api.get(P+'/transforms').json() if t['id']=='wallet.ens_primary_name')
    assert ens['implemented'] and ens['chains']==['ethereum']
    assert ens['input_types']==['blockchain_address'] # ENS endpoints remain output-only.


def legacy_fingerprints():
    """Fixed material hashed before ED-8A0; retrieval clocks are not material."""
    wallet=canonical_subject('blockchain_address','ethereum',ETH)
    label=dict(kind='candidate_evidence',predicate='locally_labeled_as',
        **{'from':dict(kind='blockchain_address',namespace='ethereum',value=ETH),
           'to':dict(kind='annotation',namespace='gc-label',value='fixed-label')},
        fact_key={'label_id':'fixed-label'},observation=dict(kind='local_label_snapshot',
            source_record_key='fixed-label',origin_label_id='fixed-label',source_locator='label:fixed-label',
            title='Fixed annotation',summary='Fixed context',retrieved_at=datetime(2026,9,13,tzinfo=timezone.utc),
            source_snapshot={'record':{'id':'fixed-label','label':'Fixed annotation'}}))
    output={'wallet':wallet['identity_sha256']}
    for key,item,tid,sid in [('label',label,'wallet.local_labels','gc_labels'),('github',record(),'wallet.public_code_mentions','github')]:
        transform,source=REGISTRY.pair(tid,sid)
        output[key+'_query']=query_fingerprint(wallet,transform,source,{'max_results':transform.max_results})
        endpoints=[canonical_subject(**item[x]) for x in ('from','to')]
        output[key+'_result']=result_identity(wallet,item['kind'],item['predicate'],*endpoints,item['fact_key'])[1]
        payload=ObservationInput.model_validate(item['observation']).model_dump()
        output[key+'_observation']=observation_fingerprint(payload,dict(source_id=sid,source_version=1,transform_id=tid,transform_version=1))
    return output


def test_legacy_fingerprints_unchanged():
    assert legacy_fingerprints()==LEGACY_FINGERPRINTS


LEGACY_FINGERPRINTS = {
    'wallet':'19fa27c39c87058517e955a98cfebc8daedd5a4cf96eda16aa27d5fed695d578',
    'label_query':'9c336d551e1cc66aa14da3b25e127adcc47c73ffc19d157b3bc3e980ad5df6b2',
    'label_result':'d1fd2153bf02cb71471a53e898eecbc400fe3cfaad5302cfc4e1700df05eaa18',
    'label_observation':'331cea99924a0b65c820c05743db2aa39d95c3963ae642ab5efa28ec76e0e32d',
    'github_query':'eb3cb29bbf65f9703251599ec5ad60641b1736c2da1e920d55eef8e32abc7f7b',
    'github_result':'202fa1ba156895fa195e587465cd36df7fab24acb6a09010ffb8c4945414395c',
    'github_observation':'42a0c32cc98cab020420e928d76116bc507245fc0513c25e8840dc2a9cda9f42',
}
