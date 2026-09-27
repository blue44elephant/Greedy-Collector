"""CL-1 real stored normalization/service/API contracts. All provider data is test-only."""
import hashlib
import json
import random
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import main
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import Base, Transaction, Label, Case, CaseEntity, Address, RiskResult, WatchlistWallet
from greedy_collector.chains import get_chain
from greedy_collector.chains.base58 import base58_encode
from greedy_collector.clustering.models import Base as ClusterBase, Evidence, Version, Exclusion, Cluster
from greedy_collector.clustering.domain import ClusteringError, fingerprint
from greedy_collector.clustering.heuristics import components, evaluate
from greedy_collector.clustering.service import ClusteringService
from greedy_collector.clustering.graph import graph_view
from greedy_collector.transaction_identity import persist_normalized_event
from greedy_collector.reporting import case_markdown, case_json, case_html, case_pdf


def address(n, chain='bitcoin'):
    payload = bytes([0 if chain == 'bitcoin' else 48]) + n.to_bytes(20, 'big')
    return base58_encode(payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4])

def raw(inputs, number=1, outputs=None):
    return {'txid': f'{number:064x}', 'vin': [{'txid': f'{1000+i:064x}', 'vout': i, 'prevout': {'scriptpubkey_address': a, 'value': 100000}} for i,a in enumerate(inputs)],
        'vout': outputs or [{'scriptpubkey_address': address(999), 'value': 199000}],
        'status': {'confirmed': True, 'block_height': 123, 'block_time': 1700000000}, 'fee': 1000}

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError('No provider request permitted')
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request', deny)
    monkeypatch.setattr('httpx.HTTPTransport.handle_request', deny)

@pytest.fixture
def db():
    engine = create_fk_enabled_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    ClusterBase.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session: yield session
    engine.dispose()

def store(db, members, number=1, chain='bitcoin', payload=None):
    adapter = get_chain(chain).adapter()
    tx = adapter._normalize(payload or raw(members, number), members[0] if members else '', 'test-only')
    persist_normalized_event(db, tx)
    db.commit()
    return tx

def analyze(db, chain='bitcoin'):
    return ClusteringService(db).analyze(chain)

@pytest.mark.parametrize('chain', ['bitcoin','litecoin'])
def test_real_normalization_persists_all_inputs(db, chain):
    a,b = address(1,chain),address(2,chain)
    store(db,[a,b],chain=chain)
    data=analyze(db,chain)
    assert data['clusters'][0]['members']==sorted([a,b])
    assert data['evidence'][0]['inputs']==sorted([a,b])
    assert db.scalar(select(Transaction)).raw_payload['vin'][1]['prevout']['scriptpubkey_address']==b
    assert address(999) not in data['clusters'][0]['members']

def test_same_text_cross_chain_never_merges(db):
    # Prefix 5 is valid on both chains.
    def shared(n):
        value=bytes([5])+n.to_bytes(20,'big')
        return base58_encode(value+hashlib.sha256(hashlib.sha256(value).digest()).digest()[:4])
    a,b=shared(1),shared(2)
    store(db,[a,b]);store(db,[a,b],chain='litecoin')
    btc=analyze(db)['clusters'][0];ltc=analyze(db,'litecoin')['clusters'][0]
    assert btc['id']!=ltc['id'] and btc['chain']!=ltc['chain']

@pytest.mark.parametrize('members', [[1],[1,1]])
def test_single_distinct_input_has_no_cluster(db,members):
    store(db,[address(n) for n in members])
    result=analyze(db)
    assert result['clusters']==[]
    assert 'fewer_than_two_distinct_inputs' in result['evidence'][0]['automatic_exclusions']

def test_duplicate_members_and_transitive_evidence(db):
    a,b,c=map(address,[1,2,3])
    store(db,[a,a,b]);store(db,[b,c],2)
    result=analyze(db)['clusters'][0]
    assert result['members']==sorted([a,b,c])
    direct=[set(e['inputs']) for e in result['evidence']]
    assert {a,b} in direct and {b,c} in direct
    assert not any({a,c}<=inputs for inputs in direct)
    view=graph_view(result)
    assert len(view['direct_evidence'])==2

@pytest.mark.parametrize('kind', ['coinjoin','high_inputs','high_outputs','missing_prevout','invalid_input','missing_outputs','pending','coinbase'])
def test_conservative_exclusions_retained(db,kind):
    members=[address(1),address(2),address(3)]
    payload=raw(members)
    if kind=='coinjoin': payload['vout']=[{'value':123,'scriptpubkey_address':address(99)}]*3
    if kind=='high_inputs': payload['vin']=raw([address(n) for n in range(1,21)])['vin']
    if kind=='high_outputs': payload['vout']=[{'value':n+1} for n in range(20)]
    if kind=='missing_prevout': payload['vin'][1]['prevout']=None
    if kind=='invalid_input': payload['vin'][1]['prevout']['scriptpubkey_address']='not an address'
    if kind=='missing_outputs': payload['vout']=[]
    if kind=='pending': payload['status']={'confirmed':False}
    if kind=='coinbase': payload['vin'][0]['is_coinbase']=True
    # Store through normalizer except malformed prevout, which represents historical partial records.
    db.add(Transaction(chain='bitcoin',tx_hash=payload['txid'],raw_payload=payload));db.commit()
    data=analyze(db)
    assert not data['clusters'] and data['evidence'][0]['excluded']
    assert db.scalar(select(func.count()).select_from(Evidence))==1

def test_exclusion_splits_preserves_versions_and_case_pin(db):
    a,b,c=map(address,[1,2,3]);store(db,[a,b]);store(db,[b,c],2)
    service=ClusteringService(db)
    first=service.analyze('bitcoin')['clusters'][0]
    db.add(Case(id='test-case',title='Test'));db.commit()
    pin=service.pin('test-case',first['id'],first['version'])
    bc=next(e for e in first['evidence'] if c in e['inputs'])
    result=service.exclude(bc['id'],'Likely collaborative transaction')
    latest=result['clusters'][0]
    assert latest['id']==first['id'] and latest['version']==2
    assert latest['members']==sorted([a,b])
    assert service.cluster(first['id'],1)==first
    stored=db.get(CaseEntity,pin['id']).metadata_json['cluster_pin']
    assert stored==first
    assert any(e['analyst_exclusion'] for e in latest['evidence'])
    assert db.scalar(select(func.count()).select_from(Exclusion))==1

@pytest.mark.parametrize('reason',['','   ','x'*1001])
def test_rationale_required(db,reason):
    store(db,[address(1),address(2)]);e=analyze(db)['evidence'][0]
    with pytest.raises(ClusteringError):ClusteringService(db).exclude(e['id'],reason)

def test_unchanged_rerun_and_new_evidence(db):
    a,b,c=map(address,[1,2,3]);store(db,[a,b])
    first=analyze(db)['clusters'][0]
    second=analyze(db)['clusters'][0]
    assert first==second
    store(db,[b,c],2)
    third=analyze(db)['clusters'][0]
    assert third['id']==first['id'] and third['version']==2
    assert ClusteringService(db).cluster(first['id'],1)==first

@pytest.mark.parametrize('category',['Exchange','Mixer','Bridge','Service'])
def test_labels_are_caution_not_topology(db,category):
    a,b=address(1),address(2);store(db,[a,b])
    db.add(Label(chain='bitcoin',address=a,label='Actual local annotation',type=category,source='test'));db.commit()
    result=analyze(db)['clusters'][0]
    assert result['members']==sorted([a,b]) and not result['evidence'][0]['excluded']
    assert category in result['evidence'][0]['counter_indicators'][0]

@pytest.mark.parametrize('chain',['ethereum','base','arbitrum','bsc','polygon','tron','solana','monero'])
def test_unsupported_chains(db,chain):
    with pytest.raises(ClusteringError,match='unavailable'):analyze(db,chain)

@pytest.mark.parametrize('source',['same_source_page','same_github_mention','same_ens_entity'])
def test_no_cluster_from_public_context(db,source):
    for n in [1,2]:db.add(Address(chain='bitcoin',address=address(n),metadata_json={'context':source}))
    db.commit()
    assert analyze(db)['clusters']==[]

def test_no_attribution_risk_label_or_watch_side_effects(db):
    store(db,[address(1),address(2)])
    tables=['attribution_entities','attribution_claims','labels','risk_results','watchlist_wallets','wallet_alerts']
    before={table:db.execute(text(f'SELECT count(*) FROM {table}')).scalar() for table in tables}
    db.rollback();analyze(db)
    assert {table:db.execute(text(f'SELECT count(*) FROM {table}')).scalar() for table in tables}==before

@pytest.mark.parametrize('seed', range(4))
def test_union_find_determinism_and_linear_hyperedges(seed):
    evidence=[{'inputs':[str(n),str(n+1)]} for n in range(1000)]
    expected=components(evidence);random.Random(seed).shuffle(evidence)
    assert components(evidence)==expected
    assert len(expected[0])==1001
    assert len(components([{'inputs':[str(n) for n in range(5000)]}])[0])==5000

def test_large_cluster_guard_and_bounded_graph(db):
    from greedy_collector.clustering.models import Base as CB
    for n in range(1,502):store(db,[address(n),address(n+1)],n)
    result=analyze(db)['clusters'][0]
    assert result['status']=='review_required' and len(result['members'])==502
    page=graph_view(result)
    assert len(page['members'])==100 and len(page['direct_evidence'])<=100
    assert page['next_offset']==100 and page['total_members']==502
    assert len(graph_view(result,500)['members'])==2

def test_bound_rejects_without_partial_writes(db,monkeypatch):
    store(db,[address(1),address(2)])
    monkeypatch.setattr('greedy_collector.clustering.service.MAX_ROWS',0)
    with pytest.raises(ClusteringError,match='No partial'):analyze(db)
    assert db.scalar(select(func.count()).select_from(Evidence))==0

def test_reports_preserve_pinned_material(db):
    store(db,[address(1),address(2)]);snap=analyze(db)['clusters'][0]
    case={'title':'CL-1','description':'','status':'Open'}
    entities=[{'entity_type':'technical_cluster','entity_ref':snap['id'],'metadata_json':{'cluster_pin':snap,'chain':'bitcoin'}}]
    markdown=case_markdown(case,entities,[],[])
    assert snap['heuristic'] in markdown and snap['disclaimer'] in markdown
    assert snap['evidence'][0]['tx_hash'] in markdown
    assert 'Direct evidence' in markdown and 'same owner' not in markdown
    assert json.loads(case_json(case,entities,[],[]))['entities'][0]['metadata_json']['cluster_pin']==snap
    assert snap['heuristic'] in case_html(case,entities,[],[])
    assert case_pdf(case,entities,[],[]).startswith(b'%PDF')

def test_api_analysis_wallet_graph_case_and_safe_errors(db,monkeypatch):
    a,b=address(1),address(2);store(db,[a,b]);db.add(Case(id='case',title='CL-1'));db.commit()
    engine=db.get_bind()
    def sessions():
        with Session(engine) as session:yield session
    previous=main.app.dependency_overrides.copy();main.app.dependency_overrides[get_db]=sessions
    try:
        with TestClient(main.app) as client:
            result=client.post('/api/greedy-collector/clustering/analyze',json={'chain':'bitcoin'})
            assert result.status_code==200,result.text
            snap=result.json()['clusters'][0]
            assert client.get(f'/api/greedy-collector/clustering/wallet/bitcoin/{a}').json()['clusters'][0]['id']==snap['id']
            assert client.get(f'/api/greedy-collector/clustering/clusters/{snap["id"]}/graph').status_code==200
            assert client.post('/api/greedy-collector/clustering/cases/case/pin',json={'cluster_id':snap['id'],'version':1}).status_code==200
            assert client.post('/api/greedy-collector/clustering/analyze',json={'chain':'monero'}).status_code==422
            assert client.post(f'/api/greedy-collector/clustering/evidence/{snap["evidence"][0]["id"]}/exclude',json={'reason':' '}).status_code==422
            assert client.get('/static/js/clustering.js').status_code==200
            for value in ['API_KEY','Authorization','https://']:assert value not in result.text
    finally:main.app.dependency_overrides.clear();main.app.dependency_overrides.update(previous)

def test_inconsistent_records_fail_closed(db):
    a,b,c=map(address,[1,2,3]);store(db,[a,b])
    db.add(Transaction(chain='bitcoin',tx_hash=f'{1:064x}',event_key='legacy:other',raw_payload=raw([b,c])));db.commit()
    result=analyze(db)
    assert not result['clusters']
    assert 'inconsistent_stored_transaction_views' in result['evidence'][0]['automatic_exclusions']

def test_material_determinism_under_db_order(db):
    a,b,c=map(address,[1,2,3]);store(db,[b,c],2);store(db,[a,b],1)
    first=analyze(db)['clusters'][0]
    assert first['fingerprint']==fingerprint({k:v for k,v in first.items() if k not in {'id','version','fingerprint','created_at','recomputed_at'}})
    assert analyze(db)['clusters'][0]==first


def test_exclusion_capture_time_not_material_identity():
    from greedy_collector.clustering.domain import material_fingerprint
    first={"members":["A","B"],"evidence":[{"analyst_exclusion":{"reason":"Review","timestamp":"2026-09-27T00:00:00+00:00"}}]}
    second=deepcopy(first);second["evidence"][0]["analyst_exclusion"]["timestamp"]="2026-09-28T00:00:00+00:00"
    assert material_fingerprint(first)==material_fingerprint(second)


def test_reingestion_cannot_bypass_exclusion(db):
    a,b=address(1),address(2);store(db,[a,b])
    evidence=analyze(db)['evidence'][0]
    ClusteringService(db).exclude(evidence['id'],'Known false merge')
    row=db.scalar(select(Transaction));payload=deepcopy(row.raw_payload);payload['status']['block_height']=456;row.raw_payload=payload;db.commit()
    result=analyze(db)
    assert not result['clusters'] and result['evidence'][0]['analyst_exclusion']['reason']=='Known false merge'


def test_wrong_raw_transaction_identity_excluded(db):
    payload=raw([address(1),address(2)])
    db.add(Transaction(chain='bitcoin',tx_hash=f'{999:064x}',raw_payload=payload));db.commit()
    result=analyze(db)
    assert not result['clusters'] and 'inconsistent_transaction_id' in result['evidence'][0]['automatic_exclusions']


def test_split_and_merge_retire_ids_without_erasing_history(db):
    a,b,c,d=map(address,[1,2,3,4]);store(db,[a,b],1);store(db,[c,d],2)
    before=analyze(db)['clusters'];store(db,[b,c],3)
    merged=analyze(db)['clusters'][0]
    assert len(merged['members'])==4
    assert merged['id']==min(row['id'] for row in before)
    service=ClusteringService(db)
    for old in before:
        assert service.cluster(old['id'],1)==old
    db.rollback()
    evidence=next(e for e in merged['evidence'] if e['tx_hash']==f'{3:064x}')
    split=service.exclude(evidence['id'],'False bridge merge')['clusters']
    assert sorted(len(c['members']) for c in split)==[2,2]
    assert len({c['id'] for c in split})==2
