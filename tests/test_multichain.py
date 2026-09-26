"""MC-1: synthetic adapters are confined to this test module."""
import asyncio
from dataclasses import replace
import json
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from greedy_collector.chains import registry as cr
from greedy_collector.chains.registry import ChainRegistry,ChainDefinition,ChainFamily,Capability as C,ChainError,UnsupportedCapability
from greedy_collector.chains.evm import EvmAdapter
from greedy_collector.chains import BitcoinAdapter,EthereumAdapter
from greedy_collector.resolver import resolve_identifier
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base,Address,Transaction,WatchlistWallet,Label
from greedy_collector.schemas import LookupRequest,ManualLabelCreate,NormalizedTransaction
from greedy_collector.services import GreedyCollectorService
from greedy_collector.graph import GraphStore
from greedy_collector.discovery.domain import canonical_subject,query_fingerprint
from greedy_collector.discovery.registry import REGISTRY,TransformDescriptor
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.manual_source import ManualSourceService
from greedy_collector.attribution.domain import ClaimInput

ETH='0x'+'aB'*20
BTC='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
BECH='BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KYGT080'

class TestAdapter(EvmAdapter):
    __test__=False
    chain='test_chain'

def test_definition(capabilities=None):
    return ChainDefinition('test_chain','Test only','TST',ChainFamily.ACCOUNT,TestAdapter,
        frozenset(capabilities or {C.ADDRESS_VALIDATION,C.DISCOVERY,C.LABELS,C.ATTRIBUTION,C.CASES,C.GRAPH}),18,True)
test_definition.__test__=False

@pytest.fixture
def third(monkeypatch):
    registry=ChainRegistry(cr.list_chains());registry.register(test_definition())
    monkeypatch.setattr(cr,'REGISTRY',registry)
    return registry

@pytest.fixture
def db():
    engine=create_fk_enabled_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:yield session
    finally:engine.dispose()

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*a,**kw):pytest.fail('MC-1 must not call a provider')
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request',fail)
    monkeypatch.setattr('httpx.HTTPTransport.handle_request',fail)

def test_production_registry_order_and_safe_metadata(monkeypatch):
    monkeypatch.setenv('ETHERSCAN_API_KEY','secret-not-public')
    rows=[d.public_metadata() for d in cr.list_chains()]
    assert [r['id'] for r in rows]==['bitcoin','ethereum','base','arbitrum','bsc','polygon','tron','solana']
    assert [r['native_symbol'] for r in rows]==['BTC','ETH','ETH','ETH','BNB','POL','TRX','SOL']
    assert [r['family'] for r in rows]==['utxo','account','account','account','account','account','account','account']
    assert 'secret' not in json.dumps(rows) and 'adapter' not in json.dumps(rows)
    assert cr.is_supported_chain('ethereum') and not cr.is_supported_chain('test_chain')

@pytest.mark.parametrize('change',[{'chain_id':'Bad ID'},{'chain_id':''},{'display_name':''},{'native_symbol':''},
    {'family':'utxo'},{'adapter':None},{'capabilities':frozenset({'random'})},{'native_decimals':-1},
    {'capabilities':frozenset({C.ADDRESS_VALIDATION,C.MONITORING})},
    {'capabilities':frozenset({C.ADDRESS_VALIDATION,C.BALANCE})}])
def test_invalid_definitions_rejected(change):
    with pytest.raises(ValueError):replace(test_definition(),**change)

def test_duplicate_and_unknown_are_safe():
    registry=ChainRegistry([test_definition()])
    with pytest.raises(ValueError,match='Duplicate'):registry.register(test_definition())
    with pytest.raises(ChainError,match='^unsupported_chain$'):registry.get_chain('secret-unknown')
    with pytest.raises(ValueError):registry.register({})

@pytest.mark.parametrize('chain,address,expected',[('bitcoin',BTC,BTC),('bitcoin',BECH,BECH.lower()),('ethereum',ETH,ETH.lower())])
def test_identity_normalization(chain,address,expected):
    assert cr.wallet_identity(chain,address)==(chain,expected)
    assert resolve_identifier(address)['normalized']==address

@pytest.mark.parametrize('value,chain,kind',[(BTC,'bitcoin','address'),(ETH,'ethereum','address'),('A'*64,'bitcoin','transaction'),('0x'+'A'*64,'ethereum','transaction')])
def test_explicit_hint(value,chain,kind):
    result=resolve_identifier(' '+value+' ',chain_hint=chain)
    assert result['kind']==kind and result['chain']==chain

def test_hint_unknown_mismatch_and_ambiguity(third):
    with pytest.raises(ChainError):resolve_identifier(ETH,'not_registered')
    assert resolve_identifier(ETH,'bitcoin')['kind']=='unknown'
    assert resolve_identifier('arbitrary text')['kind']=='unknown'
    assert resolve_identifier(ETH)['chain']=='ethereum'
    assert resolve_identifier(ETH,'test_chain')['chain']=='test_chain'
    assert LookupRequest.model_json_schema()['properties']['chain']['enum']==['bitcoin','ethereum','base','arbitrum','bsc','polygon','tron','solana','test_chain']
    assert resolve_identifier(ETH,'ethereum')['chain']=='ethereum'

@pytest.mark.parametrize('chain,has,absent',[('bitcoin',C.PENDING_TRANSACTIONS,C.TOKEN_TRANSFERS),('ethereum',C.TOKEN_TRANSFERS,C.PENDING_TRANSACTIONS)])
def test_real_capabilities(chain,has,absent):
    caps=cr.get_chain_capabilities(chain)
    assert has in caps and absent not in caps
    assert {C.BALANCE,C.MONITORING,C.TRANSACTION_HISTORY,C.TRANSACTION_LOOKUP,C.GRAPH}<=caps

@pytest.mark.parametrize('capability',[C.MONITORING,C.BALANCE,C.TRANSACTION_LOOKUP,C.RISK])
def test_unsupported_capability_is_distinct(third,capability):
    with pytest.raises(UnsupportedCapability,match='unsupported_chain_capability'):third.adapter('test_chain',capability)

def test_no_ethereum_fallback_or_monitoring_state(third,db):
    from greedy_collector.monitoring import monitor_chain,_chain_locks
    with pytest.raises(UnsupportedCapability):asyncio.run(monitor_chain('test_chain'))
    assert 'test_chain' not in _chain_locks
    svc=GreedyCollectorService()
    with pytest.raises(UnsupportedCapability):asyncio.run(svc.lookup_address(db,LookupRequest(chain='test_chain',address=ETH)))
    with pytest.raises(UnsupportedCapability):asyncio.run(svc.lookup_transaction('test_chain','0x'+'1'*64))

def test_chain_identity_storage_graph_and_cache(third,db):
    for chain in ('ethereum','test_chain'):
        address=cr.wallet_identity(chain,ETH)[1]
        db.add(Address(chain=chain,address=address));db.add(WatchlistWallet(chain=chain,address=address))
        db.add(Transaction(chain=chain,tx_hash='0x'+'1'*64,from_address=address,to_address='0x'+'2'*40,source_api='test'))
    db.commit()
    assert len(db.scalars(select(Address)).all())==len(db.scalars(select(WatchlistWallet)).all())==len(db.scalars(select(Transaction)).all())==2
    assert cr.transaction_identity('ethereum','0x'+'A'*64)!=cr.transaction_identity('test_chain','0x'+'A'*64)
    txs=[NormalizedTransaction(chain=c,tx_hash='0x'+'1'*64,from_address=ETH,to_address='0x'+'2'*40,source_api='test') for c in ('ethereum','test_chain')]
    graph=GraphStore.response_graph(ETH,txs,[])
    assert len({n['id'] for n in graph['nodes']})==4
    assert len({e['id'] for e in graph['edges']})==2
    subjects=[canonical_subject('blockchain_address',c,ETH) for c in ('ethereum','test_chain')]
    transform=REGISTRY.transforms['wallet.public_code_mentions'];source=REGISTRY.sources['github']
    assert subjects[0]['identity_sha256']!=subjects[1]['identity_sha256']
    assert query_fingerprint(subjects[0],transform,source,{})!=query_fingerprint(subjects[1],transform,source,{})

def test_labels_are_scoped_and_base58_stays_sensitive(db):
    svc=GreedyCollectorService()
    for chain,address in [('ethereum',ETH),('bitcoin',ETH),('any',ETH),('bitcoin',BTC.lower()),('bitcoin',BTC)]:
        db.add(Label(chain=chain,address=address,label=chain+address,type='Unknown',source='test'))
    db.commit()
    tx=NormalizedTransaction(chain='ethereum',tx_hash='x',from_address=ETH,source_api='test')
    assert {r['chain'] for r in svc._labels_for_transactions(db,[tx])}=={'ethereum','any'}
    tx=tx.model_copy(update={'chain':'bitcoin','from_address':BTC})
    assert [r['address'] for r in svc._labels_for_transactions(db,[tx])]==[BTC]

def test_future_subject_labels_and_claim_inputs(third,db):
    label=ManualLabelCreate(chain='test_chain',address=ETH,label='Test',type='Unknown')
    db.add(Label(**label.model_dump()));db.commit()
    subject=DiscoveryService(db,metadata_only=True).get_or_create_subject('blockchain_address','test_chain',ETH)
    assert subject['namespace']=='test_chain' and subject['canonical_value']==ETH.lower()
    claim=ClaimInput(entity_id='entity',chain='test_chain',subject_ref=ETH,relationship='operated_by',scope_note='test')
    assert claim.subject_ref==ETH.lower()
    from tests.test_discovery_manual_source import data
    capture=data();capture['subject']={'chain':'test_chain','address':ETH}
    preview=ManualSourceService(db,metadata_only=True).preview(capture)
    assert preview
    from greedy_collector.discovery.registry import Registry
    definitions=[]
    for t in REGISTRY.transforms.values():
        values=t.model_dump()
        if t.id not in ('wallet.ens_primary_name','wallet.graphsense_public_tags'):
            values.pop('chains')
        definitions.append(values)
    registry=Registry([s.model_dump() for s in REGISTRY.sources.values()],definitions)
    service=ManualSourceService(db,metadata_only=True,registry=registry)
    row=service.capture({'capture':capture,'expected_preview_fingerprint':preview['preview_fingerprint']})
    assert row['observation']['source_snapshot']['subject']['chain']=='test_chain'
    from greedy_collector.schemas import CaseEntityCreate
    ref=CaseEntityCreate(entity_type='wallet',entity_ref=ETH,metadata={'chain':'test_chain','address':ETH})
    assert ref.metadata['chain']=='test_chain'

def test_discovery_transform_limits(third):
    assert REGISTRY.transforms['wallet.ens_primary_name'].chains==('ethereum',)
    assert REGISTRY.transforms['wallet.graphsense_public_tags'].chains==('bitcoin','ethereum')
    fields=REGISTRY.transforms['wallet.manual_source_observation'].model_dump(exclude={'chains'})
    assert 'test_chain' in TransformDescriptor(**fields).chains
    assert 'test_chain' not in REGISTRY.transforms['wallet.ens_primary_name'].chains
    assert 'test_chain' not in REGISTRY.transforms['wallet.graphsense_public_tags'].chains

def test_monitoring_adapter_policies():
    from greedy_collector.config import GreedyCollectorSettings
    settings=GreedyCollectorSettings()
    pending={'tx_hash':'p','timestamp':None};confirmed={'tx_hash':'c','timestamp':'2026-01-01'}
    btc=BitcoinAdapter();eth=EthereumAdapter()
    assert btc.monitoring_baseline([pending,confirmed])==confirmed
    assert btc.monitoring_baseline([pending]) is None
    assert eth.monitoring_baseline([pending,confirmed])==pending
    assert btc.monitoring_interval(settings)==settings.bitcoin_monitor_minutes
    assert eth.monitoring_interval(settings)==settings.ethereum_monitor_minutes

def test_metadata_and_controlled_route_errors():
    import main
    with TestClient(main.app) as client:
        rows=client.get('/api/greedy-collector/chains').json()['chains']
        assert [r['id'] for r in rows]==['bitcoin','ethereum','base','arbitrum','bsc','polygon','tron','solana']
        for path in ['/','/health','/docs','/openapi.json','/static/js/chains.js']:
            assert client.get(path).status_code==200
        r=client.post('/api/greedy-collector/resolve',json={'input':ETH,'chain_hint':'unknown'})
        assert r.status_code==422 and 'unsupported_chain' in r.text
        assert client.get('/api/greedy-collector/address/unknown/value/graph').status_code==422


def test_existing_scoped_discovery_transforms_remain_limited():
    from greedy_collector.discovery.domain import fingerprint
    from greedy_collector.discovery.registry import REGISTRY
    digests={key:fingerprint(item.model_dump(mode='json')) for key,item in REGISTRY.transforms.items()}
    assert digests['wallet.graphsense_public_tags']=='250c55c5d1802b92e8e3f0d81c8021d8acbedcce6241a63f5fff924ce847ece5'
    assert digests['wallet.ens_primary_name']=='d2a00085bafd6a10946e9eef7e24759cafecd37021b6ef49f9e2916ad93c589e'
    assert set(REGISTRY.transforms['wallet.graphsense_public_tags'].chains)=={'bitcoin','ethereum'}
    assert REGISTRY.transforms['wallet.ens_primary_name'].chains==('ethereum',)
    for transform_id in ('wallet.local_labels','wallet.manual_exact_web','wallet.manual_source_observation','wallet.public_code_mentions'):
        item=REGISTRY.transforms[transform_id]
        assert {'base','arbitrum','bsc','polygon'}<=set(item.chains)
        source=REGISTRY.sources[item.source_ids[0]]
        subject=canonical_subject('blockchain_address','base',ETH)
        first=query_fingerprint(subject,item,source,{'max_results':item.max_results})
        second=query_fingerprint(subject,item,source,{'max_results':item.max_results})
        assert first==second
