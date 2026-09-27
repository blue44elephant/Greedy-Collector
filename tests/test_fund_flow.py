"""FL-1 uses only isolated stored provider fixtures; no external transport."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
import random
import pytest
from sqlalchemy import select,text,func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
import main
from greedy_collector.database import create_fk_enabled_engine,get_db
from greedy_collector.models import Base,Transaction,Label,Case,CaseEntity
from greedy_collector.chains import get_chain
from greedy_collector.transaction_identity import persist_normalized_event
from greedy_collector.fund_flow.models import Base as FlowBase,FlowRun
from greedy_collector.fund_flow.schemas import FlowQuery
from greedy_collector.fund_flow.service import FlowService
from greedy_collector.fund_flow.domain import FlowError,VERSION
from greedy_collector.chains.registry import UnsupportedCapability
from greedy_collector.reporting import case_json,case_markdown,case_html,case_pdf
from tests.test_clustering import raw,address as utxo_address

A='0x'+'1'*40
B='0x'+'2'*40
C='0x'+'3'*40
D='0x'+'4'*40
TOKEN='0x'+'a'*40
OTHER='0x'+'b'*40
T=datetime(2026,9,1,tzinfo=timezone.utc)

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError('FL-1 must never call a provider')
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request',deny)
    monkeypatch.setattr('httpx.HTTPTransport.handle_request',deny)
    monkeypatch.setattr(main,'start_monitoring',lambda:None)
    monkeypatch.setattr(main,'stop_monitoring',lambda:None)

@pytest.fixture
def db():
    engine=create_fk_enabled_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine);FlowBase.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as session:yield session
    engine.dispose()

def event(db,source=A,target=B,value='5',number=1,second=0,chain='ethereum',token=None,failed=False):
    row={'hash':'0x'+f'{number:064x}','from':source,'to':target,'value':str(int(value)*10**(6 if token else 18)),
         'timeStamp':str(int((T+timedelta(seconds=second)).timestamp())),'blockNumber':'100','isError':'1' if failed else '0','txreceipt_status':'0' if failed else '1'}
    adapter=get_chain(chain).adapter()
    if token:row.update({'contractAddress':token,'tokenDecimal':'6','tokenSymbol':'SAME','logIndex':number});tx=adapter._normalize_token(row,source)
    else:tx=adapter._normalize(row,source)
    persist_normalized_event(db,tx);db.commit();return tx

def query(db,**kwargs):
    return FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=C,**kwargs))


def test_direct_and_two_hop_provenance(db):
    event(db,target=B);event(db,source=B,target=C,number=2,second=1)
    result=query(db)
    path=result['paths'][0]
    assert path['addresses']==[A,B,C] and path['hops']==2
    assert path['steps'][0]['event_key']=='tx' and path['steps'][0]['raw_amount']=='5000000000000000000'
    assert path['observed_path_capacity']=='5'
    direct=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=B))
    assert direct['paths'][0]['hops']==1


def test_shortest_equal_paths_deterministic(db):
    event(db,A,B,number=1);event(db,B,C,number=2,second=1)
    event(db,A,D,number=3);event(db,D,C,number=4,second=1)
    result=query(db)
    assert {tuple(p['addresses']) for p in result['paths']}=={(A,B,C),(A,D,C)}
    event(db,A,C,number=5)
    assert [p['hops'] for p in query(db)['paths']]==[1]


def test_cycle_terminates_and_hops_respected(db):
    event(db,A,B);event(db,B,A,number=2);event(db,B,C,number=3)
    assert not query(db,max_hops=1)['paths']
    assert all(len(set(p['addresses']))==len(p['addresses']) for p in query(db,algorithm='simple')['paths'])

@pytest.mark.parametrize('bound,reason',[('max_paths','max_paths'),('max_nodes','max_explored_nodes'),('max_edges','max_explored_edges')])
def test_exploration_bounds_explicit(db,bound,reason):
    event(db,A,B);event(db,A,D,number=2);event(db,B,C,number=3);event(db,D,C,number=4)
    result=query(db,**{bound:2 if bound=='max_nodes' else 1})
    assert result['truncated'] and reason in result['limiting_reasons']


def test_chain_isolation(db):
    event(db,A,B);event(db,B,C,number=2,chain='base')
    assert not query(db)['paths']


def test_monero_controlled_unsupported(db):
    with pytest.raises(UnsupportedCapability):FlowService(db).analyze(FlowQuery(chain='monero',source='anything',target='anything'))

@pytest.mark.parametrize('temporal,expected',[(True,0),(False,1)])
def test_reverse_time_mode(db,temporal,expected):
    event(db,A,B,second=10);event(db,B,C,number=2,second=0)
    assert len(query(db,temporal_order=temporal)['paths'])==expected


def test_time_window_and_equal_timestamps(db):
    event(db,A,B);event(db,B,C,number=2)
    assert len(query(db,start_time=T,end_time=T)['paths'])==1
    assert not query(db,start_time=T+timedelta(seconds=1))['paths']


def test_widest_capacity_minimum_not_sum(db):
    event(db,A,B,value='10');event(db,B,C,value='4',number=2)
    event(db,A,D,value='6',number=3);event(db,D,C,value='6',number=4)
    result=query(db,algorithm='widest',asset='native')
    assert [p['observed_path_capacity'] for p in result['paths']]==['6','4']
    assert result['paths'][0]['addresses']==[A,D,C]


def test_assets_never_mix_or_merge_on_symbol(db):
    event(db,A,B,token=TOKEN);event(db,B,C,token=OTHER,number=2)
    event(db,B,C,number=3)
    assert not query(db)['paths']
    event(db,B,C,token=TOKEN,number=4,value='2')
    paths=query(db)['paths']
    assert len(paths)==1 and paths[0]['asset']=='ethereum:token:'+TOKEN and paths[0]['observed_path_capacity']=='2'


def test_duplicate_events_count_once(db):
    event(db,A,B);event(db,A,B)
    result=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A),'neighborhood')
    assert result['analytics']['fan_in_out'][0]['event_count']==1
    assert db.scalar(select(func.count()).select_from(Transaction))==1

@pytest.mark.parametrize('chain',['bitcoin','litecoin'])
def test_utxo_connectivity_without_value_allocation(db,chain):
    adapter=get_chain(chain).adapter();a,b,c=[utxo_address(n,chain) for n in [1,2,3]]
    payload=raw([a,b],1,[{'scriptpubkey_address':c,'value':190000},{'scriptpubkey_address':b,'value':9000}])
    tx=adapter._normalize(payload,a,'test-only');persist_normalized_event(db,tx);db.commit()
    result=FlowService(db).analyze(FlowQuery(chain=chain,source=a,target=c))
    step=result['paths'][0]['steps'][0]
    assert step['amount'] is None and step['raw_amount'] is None
    assert step['output_amount']=='0.0019' and step['input_count']==2
    assert result['utxo_transactions'][0]['sources']==sorted([a,b])
    assert result['utxo_transactions'][0]['stored_event_keys']==[tx.event_key or ('tx' if chain=='litecoin' else db.scalar(select(Transaction.event_key)))]
    assert result['paths'][0]['observed_path_capacity'] is None
    assert 'Exact input-to-output' in result['paths'][0]['explanation']
    assert all(m['observed_amount'] is None for m in result['analytics']['fan_in_out'])


def test_utxo_chain_separation_and_no_same_tx_reuse(db):
    a,b,c=[utxo_address(n) for n in [1,2,3]]
    payload=raw([a,b],1,[{'scriptpubkey_address':b,'value':1},{'scriptpubkey_address':c,'value':2}])
    tx=get_chain('bitcoin').adapter()._normalize(payload,a,'test-only');persist_normalized_event(db,tx);db.commit()
    result=FlowService(db).analyze(FlowQuery(chain='bitcoin',source=a,target=c,algorithm='simple'))
    assert [p['hops'] for p in result['paths']]==[1]
    assert all(s['chain']=='bitcoin' for p in result['paths'] for s in p['steps'])


def test_metrics_separate_assets_repeated_counterparties(db):
    event(db,A,B,value='5');event(db,A,B,value='6',number=2,second=2)
    event(db,D,A,value='3',number=3);event(db,B,A,value='2',number=4)
    event(db,A,B,value='100',number=5,token=TOKEN)
    result=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A),'neighborhood')
    rows={(r['asset'],r['direction']):r for r in result['analytics']['fan_in_out']}
    assert rows[('ethereum:native','outgoing')]['observed_amount']=='11'
    assert rows[('ethereum:native','incoming')]['distinct_counterparties']==2
    assert rows[('ethereum:token:'+TOKEN,'outgoing')]['observed_amount']=='100'
    repeated=result['analytics']['repeated_counterparties'][0]
    assert repeated['count']==2 and repeated['observed_amount']=='11' and repeated['first_observed']<repeated['last_observed']


def test_labels_select_targets_without_topology_or_side_effects(db):
    event(db,A,B);event(db,B,C,number=2)
    db.add(Label(chain='ethereum',address=C,label='Local exchange',type='Exchange',source='test-only'));db.commit()
    tables=['labels','risk_results','watchlist_wallets','wallet_alerts','attribution_entities','attribution_claims']
    before={t:db.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in tables};db.rollback()
    result=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,label_category='Exchange'))
    assert result['resolved_targets']==[C] and result['paths'][0]['addresses']==[A,B,C]
    assert {t:db.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in tables}==before


def test_history_case_pin_and_algorithm_retained(db):
    event(db,A,B);event(db,B,C,number=2)
    first=query(db);second=query(db)
    assert first['result_fingerprint']==second['result_fingerprint'] and first['id']!=second['id']
    db.add(Case(id='flow-case',title='Observed flow'));db.commit()
    pinned=FlowService(db).pin('flow-case',first['id'])
    event(db,A,C,number=3)
    assert query(db)['paths'][0]['hops']==1
    assert FlowService(db).run(first['id'])==first
    assert first['algorithm_version']==VERSION
    assert db.get(CaseEntity,pinned['id']).metadata_json['fund_flow_pin']==first

@pytest.mark.parametrize('seed',range(3))
def test_shuffled_insertion_same_order_and_fingerprint(db,seed):
    values=[(A,B,1),(B,C,2),(A,D,3),(D,C,4)];random.Random(seed).shuffle(values)
    for source,target,n in values:event(db,source,target,number=n)
    result=query(db)
    # Query and event ordering is independent of random SQL primary keys/insertion order.
    assert [p['addresses'] for p in result['paths']]==[[A,B,C],[A,D,C]]
    assert result['result_fingerprint']==query(db)['result_fingerprint']

@pytest.mark.parametrize('invalid',[{'max_hops':7},{'max_paths':101},{'start_time':T,'end_time':T-timedelta(seconds=1)},{'asset':'base:native'},{'asset':'ethereum:token:bad'}])
def test_query_bounds_validation(invalid):
    with pytest.raises(ValueError):FlowQuery(chain='ethereum',source=A,target=C,**invalid)


def test_failed_unknown_and_missing_token_identity_excluded(db):
    event(db,A,C,failed=True)
    tx=event(db,A,C,number=2)
    row=db.scalar(select(Transaction).where(Transaction.tx_hash==tx.tx_hash));row.raw_payload={};db.commit()
    assert not query(db)['paths']


def test_byte_row_and_timeout_bounds(db,monkeypatch):
    event(db,A,C)
    monkeypatch.setattr('greedy_collector.fund_flow.service.MAX_ROWS',0)
    result=query(db);assert result['truncated'] and 'max_stored_rows' in result['limiting_reasons']
    monkeypatch.setattr('greedy_collector.fund_flow.service.MAX_ROWS',5000)
    monkeypatch.setattr('greedy_collector.fund_flow.service.TIMEOUT',-1)
    result=query(db);assert result['truncated'] and 'execution_timeout' in result['limiting_reasons']


def test_reports_pin_observed_results(db):
    event(db,A,C);run=query(db)
    entities=[{'entity_type':'fund_flow','entity_ref':run['id'],'metadata_json':{'fund_flow_pin':run}}]
    case={'title':'Flow','status':'Open','description':''}
    markdown=case_markdown(case,entities,[],[])
    assert VERSION in markdown and run['source_data_fingerprint'] in markdown and 'Truncated: False' in markdown
    assert 'do not establish ownership' in markdown
    assert json.loads(case_json(case,entities,[],[]))['entities'][0]['metadata_json']['fund_flow_pin']==run
    assert VERSION in case_html(case,entities,[],[]) and case_pdf(case,entities,[],[]).startswith(b'%PDF')


def test_api_monero_routes_assets_and_pin(db):
    event(db,A,C);db.add(Case(id='case',title='Test'));db.commit()
    def sessions():
        with Session(db.get_bind()) as session:yield session
    previous=main.app.dependency_overrides.copy();main.app.dependency_overrides[get_db]=sessions
    try:
        with TestClient(main.app) as client:
            p='/api/greedy-collector/fund-flow'
            assert len(client.get(p+'/capabilities').json()['chains'])==9
            result=client.post(p+'/path',json={'chain':'ethereum','source':A,'target':C})
            assert result.status_code==200,result.text
            run=result.json();assert client.get(p+'/runs/'+run['id']).json()==run
            assert client.post(p+'/cases/case/pin',json={'run_id':run['id']}).status_code==200
            response=client.post(p+'/path',json={'chain':'monero','source':'x','target':'y'})
            assert response.status_code==422 and response.json()['detail']=='unsupported_chain_capability'
            assert client.get('/static/js/fund_flow.js').status_code==200
            assert all(word not in result.text for word in ['API_KEY','Authorization','https://'])
    finally:main.app.dependency_overrides.clear();main.app.dependency_overrides.update(previous)


@pytest.mark.parametrize('chain',['base','arbitrum','bsc','polygon'])
def test_other_evm_chains_use_same_precise_transfer_contract(db,chain):
    event(db,A,C,chain=chain)
    run=FlowService(db).analyze(FlowQuery(chain=chain,source=A,target=C))
    assert run['paths'][0]['asset']==chain+':native'
    assert run['paths'][0]['steps'][0]['chain']==chain

@pytest.mark.parametrize('token',[False,True])
def test_tron_success_evidence_and_token_identity(db,token):
    from tests.test_tron import native_row,trc20_row,OTHER,FOCUS,TOKEN
    adapter=get_chain('tron').adapter()
    if token:tx=adapter._normalize_trc20(trc20_row(),OTHER)
    else:
        raw=native_row();raw['ret']=[{'contractRet':'SUCCESS'}]
        tx=adapter._normalize_account_transaction(raw,OTHER)
    persist_normalized_event(db,tx);db.commit()
    run=FlowService(db).analyze(FlowQuery(chain='tron',source=OTHER,target=FOCUS))
    assert run['paths'][0]['asset']==('tron:token:'+TOKEN if token else 'tron:native')
    assert run['paths'][0]['observed_path_capacity']==('1.234567' if token else '1.25')

@pytest.mark.parametrize('token',[False,True])
def test_solana_parsed_success_events(db,token):
    from tests.test_solana import tx_result,system_transfer,token_transfer,token_balances,FOCUS,OTHER,MINT,SIG
    adapter=get_chain('solana').adapter()
    raw=tx_result([token_transfer() if token else system_transfer()],token_balances=token_balances())
    for tx in adapter.parse_transaction(raw,signature=SIG):persist_normalized_event(db,tx)
    db.commit()
    run=FlowService(db).analyze(FlowQuery(chain='solana',source=FOCUS,target=OTHER))
    assert run['paths'][0]['asset']==('solana:token:'+MINT if token else 'solana:native')
    assert run['paths'][0]['steps'][0]['event_key']=='solana-ix:0'


def test_unknown_timestamps_excluded_by_default_but_connectivity_allowed(db):
    tx=event(db,A,C);row=db.scalar(select(Transaction));row.timestamp=None;db.commit()
    assert not query(db)['paths']
    assert query(db,temporal_order=False)['paths'][0]['first_timestamp'] is None


def test_label_scope_and_empty_targets(db):
    event(db,A,C);db.add(Label(chain='base',address=C,label='Wrong chain',type='Exchange',source='test'));db.commit()
    run=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,label_category='Exchange'))
    assert not run['resolved_targets'] and not run['paths']


def test_widest_requires_asset_and_rejects_utxo(db):
    with pytest.raises(FlowError,match='explicit asset'):query(db,algorithm='widest')
    with pytest.raises(FlowError,match='precise account'):FlowService(db).analyze(FlowQuery(chain='bitcoin',source=utxo_address(1),target=utxo_address(2),algorithm='widest',asset='native'))


def test_source_byte_bound_is_explicit(db,monkeypatch):
    event(db,A,C);monkeypatch.setattr('greedy_collector.fund_flow.service.MAX_BYTES',1)
    result=query(db);assert result['truncated'] and 'max_source_bytes' in result['limiting_reasons']


def test_utxo_representative_pair_without_inputs_is_not_used(db):
    a,b=utxo_address(1),utxo_address(2)
    db.add(Transaction(chain='bitcoin',tx_hash='a'*64,from_address=a,to_address=b,value_native='100',timestamp=T,block_number='1',raw_payload={}));db.commit()
    run=FlowService(db).analyze(FlowQuery(chain='bitcoin',source=a,target=b))
    assert not run['paths'] and run['excluded_records']


def test_self_transfer_is_not_a_distinct_counterparty(db):
    event(db,A,A)
    result=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A),'neighborhood')
    assert all(m['distinct_counterparties']==0 for m in result['analytics']['fan_in_out'])


def test_metric_disclosure_bound_is_explicit():
    from greedy_collector.fund_flow.algorithms import metrics
    edges=[{'id':str(i),'semantics':'observed_transfer','source':A,'target':B,'asset':f'ethereum:token:{i}','amount':'1','timestamp':None} for i in range(5)]
    result=metrics(edges,A,limit=2)
    assert len(result['fan_in_out'])==2 and result['limiting_reasons']==['max_metric_rows']


def test_temporal_path_search_keeps_alternate_arrivals(db):
    event(db,A,B,second=10);event(db,A,D,number=2,second=0);event(db,D,B,number=3,second=1);event(db,B,C,number=4,second=2)
    assert query(db)['paths'][0]['addresses']==[A,D,B,C]


def test_large_utxo_provenance_stored_once_per_run(db):
    chain='bitcoin';members=[utxo_address(n) for n in range(1,101)];targets=[utxo_address(n) for n in range(201,211)]
    payload=raw(members,1,[{'scriptpubkey_address':target,'value':1000} for target in targets])
    tx=get_chain(chain).adapter()._normalize(payload,members[0],'test-only');persist_normalized_event(db,tx);db.commit()
    run=FlowService(db).analyze(FlowQuery(chain=chain,source=members[0],max_paths=10),'neighborhood')
    assert len(run['paths'])==10 and len(run['utxo_transactions'])==1
    assert len(run['utxo_transactions'][0]['sources'])==100
    assert all('input_addresses' not in p['steps'][0] and p['steps'][0]['transaction_provenance_ref']==run['utxo_transactions'][0]['id'] for p in run['paths'])
