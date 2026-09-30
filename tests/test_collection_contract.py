"""BC-1 regressions: deterministic fixtures only, no external provider calls."""
from decimal import Decimal
import pytest
from greedy_collector.chains.ethereum import EthereumAdapter
from greedy_collector.chains.tron import _decimal_amount
from greedy_collector.chains.solana import _amount
from greedy_collector.graph import GraphStore

A = "0x" + "1" * 40
B = "0x" + "2" * 40
C = "0x" + "3" * 40
H = "0x" + "a" * 64

def token(**changes):
    return dict(hash=H, **{"from": A, "to": B}, value="123456789012345678901234567890123456789", tokenDecimal="18", contractAddress=C, tokenSymbol="SAME", logIndex="1", blockNumber="1", **changes)

@pytest.mark.parametrize("convert", [lambda n: EthereumAdapter()._normalize_token(token(), A).value_native, lambda n: _decimal_amount(n, 18), lambda n: _amount(n, 18)])
def test_atomic_precision_above_decimal_context(convert):
    raw="123456789012345678901234567890123456789"
    assert Decimal(convert(raw)) == Decimal("123456789012345678901.234567890123456789")

def test_missing_decimals_is_not_zero_decimals():
    row=token(); row.pop("tokenDecimal")
    tx=EthereumAdapter()._normalize_token(row, A)
    assert tx.value_native == ""
    assert tx.raw_payload["_public"]["token_decimals"] is None
    assert tx.raw_payload["_public"]["raw_value"] == row["value"]

def test_failed_evm_record_never_becomes_value_edge():
    row=token(); row["isError"]="1"
    tx=EthereumAdapter()._normalize(row, A)
    assert not GraphStore.response_graph(A, [tx], [])["edges"]

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from greedy_collector.collection import (atomic_amount, utc_timestamp, prepare_event,
    validate_collection, collection_summary, execution_status)
from greedy_collector.chains import get_chain, get_chain_adapter, Capability
from greedy_collector.chains.base import ChainDataError
from greedy_collector.chains.bitcoin import BitcoinAdapter
from greedy_collector.chains.litecoin import LitecoinAdapter
from greedy_collector.chains.tron import TronAdapter
from greedy_collector.chains.solana import SolanaAdapter, TOKEN_2022_PROGRAM
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, Transaction
from greedy_collector.schemas import LookupRequest, NormalizedTransaction
from greedy_collector.services import GreedyCollectorService
from greedy_collector.transaction_identity import build_event_key, persist_normalized_event
from greedy_collector.resolver import resolve_identifier
from greedy_collector.fund_flow.edges import project
from tests.test_tron import trc20_row, native_row, FOCUS as TRON
from tests.test_solana import FOCUS as SOLANA, SIG
from tests.test_litecoin_monero import MONERO_STANDARD, LTC_P2PKH

BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
BTC_TO = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail("BC-1 tests must not use live providers")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)

@pytest.fixture
def db():
    engine=create_fk_enabled_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session: yield session
    engine.dispose()

@pytest.mark.parametrize("raw,decimals,expected", [(1, 255, "0." + "0"*254 + "1"),
    (10**77+1, 18, str(10**59)+"."+"0"*17+"1"), (0, 18, "0"), (1234567,6,"1.234567")])
def test_exact_atomic_scaling(raw,decimals,expected):
    assert atomic_amount(raw,decimals)==expected

@pytest.mark.parametrize("raw", [1.0, True, -1, "NaN", "Infinity", "1.5", None])
def test_invalid_atomic_values_rejected(raw):
    with pytest.raises(ChainDataError): atomic_amount(raw,18)

@pytest.mark.parametrize("value", [None, "", 0, "0"])
def test_missing_or_zero_timestamp_is_unavailable(value):
    assert utc_timestamp(value) is None

@pytest.mark.parametrize("value", [True, -1, "nonsense", 1.5, 10**100])
def test_invalid_timestamp_is_safe(value):
    with pytest.raises(ChainDataError): utc_timestamp(value)

def test_seconds_and_milliseconds_are_utc():
    assert utc_timestamp("1700000000") == utc_timestamp(1700000000000, milliseconds=True)
    assert utc_timestamp(1700000000123, milliseconds=True).microsecond == 123000
    assert utc_timestamp(1700000000).tzinfo is timezone.utc

@pytest.mark.parametrize("chain", ["ethereum","base","arbitrum","bsc","polygon"])
def test_account_contract_parity_and_scope(db,chain):
    tx=get_chain_adapter(chain)._normalize_token(token(), A)
    prepare_event(tx, requested_chain=chain)
    row,new=persist_normalized_event(db,tx);db.flush()
    assert new and row.chain==chain
    assert tx.raw_payload["_public"]["asset_id"]==chain+":token:"+C
    assert tx.raw_payload["_collection"]["provider"]=="etherscan_token"
    assert tx.raw_payload["_collection"]["retrieved_at"]
    assert tx.raw_payload["value"]==token()["value"]
    assert not validate_collection([tx],requested_chain=chain)
    with pytest.raises(ValueError,match="chain mismatch"):prepare_event(tx,requested_chain="tron")

def test_same_symbol_distinct_assets_and_reingestion(db):
    adapter=EthereumAdapter()
    rows=[]
    for index, contract in enumerate((C,B)):
        raw=token();raw.update(contractAddress=contract,logIndex=str(index),value="1")
        tx=prepare_event(adapter._normalize_token(raw,A))
        rows.append(tx)
        persist_normalized_event(db,tx)
        assert not persist_normalized_event(db,tx)[1]
    db.commit()
    assert len(db.scalars(select(Transaction)).all())==2
    graph=GraphStore.response_graph(A,rows,[])
    assert len({e["id"] for e in graph["edges"]})==2
    flow,excluded=project(db.scalars(select(Transaction)).all(),get_chain("ethereum"))
    assert len({e["asset"] for e in flow})==2 and not excluded

def test_missing_scaling_can_improve_without_changing_identity(db):
    raw=token(); raw.pop("logIndex");raw.pop("tokenDecimal")
    first=prepare_event(EthereumAdapter()._normalize_token(raw,A))
    stored,_=persist_normalized_event(db,first);db.flush(); row_id=stored.id
    raw["tokenDecimal"]="18";raw["tokenSymbol"]="RENAMED"
    improved=prepare_event(EthereumAdapter()._normalize_token(raw,A))
    assert build_event_key(first)==build_event_key(improved)
    row,new=persist_normalized_event(db,improved)
    db.commit()
    assert not new and row.id==row_id and row.value_native==improved.value_native

@pytest.mark.parametrize("key,value", [("isError","1"),("txreceipt_status","0")])
def test_failed_records_retained_but_no_graph_or_flow(db,key,value):
    raw=token();raw[key]=value
    tx=prepare_event(EthereumAdapter()._normalize(raw,A))
    row,_=persist_normalized_event(db,tx);db.commit()
    assert execution_status(tx)=="failed" and row.raw_payload[key]==value
    assert not GraphStore.response_graph(A,[tx],[])["edges"]
    assert project([row],get_chain("ethereum"))[0]==[]

def test_tron_failed_ret_and_missing_token_scaling(db):
    raw=native_row();raw["ret"]=[{"contractRet":"REVERT"}]
    tx=prepare_event(TronAdapter()._normalize_account_transaction(raw,TRON))
    assert execution_status(tx)=="failed"
    assert not GraphStore.response_graph(TRON,[tx],[])["edges"]
    raw=trc20_row();raw["token_info"].pop("decimals")
    tx=prepare_event(TronAdapter()._normalize_trc20(raw,TRON))
    assert tx.value_native=="" and tx.asset_contract==raw["token_info"]["address"]
    assert tx.raw_payload["_public"]["token_decimals"] is None


def utxo_row(focus=BTC,recipient=BTC_TO,confirmed=False):
    return {"txid":"a"*64,"vin":[{"prevout":{"scriptpubkey_address":focus,"value":100000001}}],
        "vout":[{"scriptpubkey_address":recipient,"value":100000000}],"fee":1,
        "status":{"confirmed":confirmed,**({"block_time":1700000000,"block_height":1} if confirmed else {})}}

@pytest.mark.parametrize("chain,focus,recipient",[("bitcoin",BTC,BTC_TO),("litecoin",LTC_P2PKH,LTC_P2PKH)])
def test_utxo_confirmation_refresh_has_stable_event_and_row(db,chain,focus,recipient):
    adapter=get_chain_adapter(chain)
    pending=prepare_event(adapter._normalize(utxo_row(focus,recipient),focus,"fixture"))
    row,_=persist_normalized_event(db,pending);db.flush(); row_id=row.id
    confirmed=prepare_event(adapter._normalize(utxo_row(focus,recipient,True),focus,"fixture"))
    assert build_event_key(pending)==build_event_key(confirmed)
    row,created=persist_normalized_event(db,confirmed);db.commit()
    assert row.id==row_id and not created and row.timestamp is not None
    assert row.raw_payload["_public"]["finality"]=="confirmed"
    assert pending.raw_payload["_public"]["finality"]=="unconfirmed"

def test_complex_utxo_query_graph_and_flow_preserve_connectivity(db):
    raw=utxo_row(confirmed=True);raw["vout"].append({"scriptpubkey_address":BTC,"value":1})
    tx=prepare_event(BitcoinAdapter()._normalize(raw,BTC,"fixture"))
    assert tx.from_address==tx.to_address==""
    assert tx.raw_payload["_public"]["wallet_input_raw"]=="100000001"
    persist_normalized_event(db,tx);db.commit()
    service=GreedyCollectorService()
    assert len(service.address_transactions(db,"bitcoin",BTC))==1
    graph=service.address_graph(db,"bitcoin",BTC,1)
    assert not graph["edges"] and graph["utxo_transactions"][0]["allocation"]=="not_inferred"
    assert {n["id"] for n in graph["nodes"]}=={BTC,BTC_TO}
    events,_=project(db.scalars(select(Transaction)).all(),get_chain("bitcoin"))
    assert events[0]["amount"] is None and len(events[0]["outputs"])==2

@pytest.mark.parametrize("value,chains", [(A,{"ethereum","base","arbitrum","bsc","polygon"}),
    (H,{"ethereum","base","arbitrum","bsc","polygon"}), ("a"*64,{"bitcoin","litecoin","tron"}),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",{"bitcoin","litecoin"})])
def test_ambiguity_requires_hint_without_network(value,chains):
    resolved=resolve_identifier(value)
    assert resolved["kind"]=="ambiguous" and {c["chain"] for c in resolved["possibilities"]}==chains
    for chain in chains: assert resolve_identifier(value,chain)["chain"]==chain

def test_bitcoin_checksums_and_mixed_case_rejected():
    valid="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
    assert BitcoinAdapter().normalize_address(valid.upper())==valid
    for value in (valid[:-1]+"q", "bC"+valid[2:], BTC[:-1]+"b"):
        with pytest.raises(ValueError): BitcoinAdapter().validate_address(value)

@pytest.mark.parametrize("method", ["lookup_address","transactions","monitoring_interval"])
def test_monero_never_returns_fake_state(method):
    adapter=get_chain_adapter("monero")
    assert adapter.validate_address(MONERO_STANDARD)==MONERO_STANDARD
    with pytest.raises(ValueError,match="unsupported_chain_capability"):
        result=getattr(adapter,method)(MONERO_STANDARD)
        if hasattr(result,"__await__"): asyncio.run(result)

def test_local_integrity_diagnostic_reports_missing_identity_and_duplicates():
    tx=prepare_event(EthereumAdapter()._normalize_token(token(),A))
    assert validate_collection([tx,tx])[0]["issues"]==["duplicate_event_identity"]
    assert validate_collection([tx],requested_chain="base")[0]["issues"]==["chain_mismatch"]
    bad=tx.model_copy(update={"tx_hash":"", "chain":""})
    assert validate_collection([bad])

@pytest.mark.asyncio
async def test_native_stream_survives_failed_token_stream(monkeypatch,db):
    async def query(self,params):
        if params["action"]=="tokentx":raise ChainDataError("rate_limited")
        return {"result":[{**token(),"isError":"0"}]}
    monkeypatch.setattr(EthereumAdapter,"_etherscan",query)
    monkeypatch.setattr(EthereumAdapter,"lookup_address",AsyncMock(return_value={"balance_native":"1","source_api":"fixture"}))
    result=await GreedyCollectorService().lookup_address(db,LookupRequest(chain="ethereum",address=A))
    assert result["collection"]["partial"] and result["collection"]["stored_new"]==1
    assert result["collection"]["streams"]["tokentx"]["reason"]=="rate_limited"
    assert result["transactions"][0]["collection_provenance"]["chain"]=="ethereum"

@pytest.mark.asyncio
async def test_evm_repeated_page_and_bounds(monkeypatch):
    adapter=EthereumAdapter()
    monkeypatch.setattr(adapter,"_etherscan",AsyncMock(return_value={"result":[token()]}))
    rows=await adapter._paginate_account_action("txlist",A,max_pages=3,page_size=1)
    assert len(rows)==1 and adapter.collection_streams["txlist"]["reason"]=="repeated_page"
    assert adapter._etherscan.await_count==2

@pytest.mark.asyncio
async def test_get_transport_does_not_leak_credential_url(monkeypatch):
    async def fail(*a,**k):raise httpx.ConnectError("https://provider/key-secret")
    monkeypatch.setattr(httpx.AsyncClient,"get",fail)
    with pytest.raises(ChainDataError) as exc:await EthereumAdapter()._get("https://provider/key-secret")
    assert str(exc.value)=="network_error" and "key-secret" not in str(exc.value)

def test_token2022_program_id_is_official_literal():
    assert TOKEN_2022_PROGRAM=="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def test_pending_duplicate_with_autoflush_disabled_is_idempotent(db):
    db.autoflush=False
    tx=prepare_event(EthereumAdapter()._normalize_token(token(),A))
    first,one=persist_normalized_event(db,tx)
    second,two=persist_normalized_event(db,tx)
    db.commit()
    assert one and not two and first.id==second.id
    assert len(db.scalars(select(Transaction)).all())==1

def test_unique_legacy_utxo_view_upgrades_without_breaking_id(db):
    tx=BitcoinAdapter()._normalize(utxo_row(),BTC,"fixture")
    old=tx.model_copy(deep=True);old.raw_payload.pop("_wallet_view")
    original,_=persist_normalized_event(db,old);db.commit();row_id=original.id
    row,created=persist_normalized_event(db,tx);db.commit()
    assert not created and row.id==row_id and row.event_key==build_event_key(tx)

def test_tron_index_spelling_and_scaling_do_not_change_identity():
    first=trc20_row();first["event_index"]="0x1"
    second=trc20_row();second["event_index"]="01";second["token_info"].pop("decimals")
    adapter=TronAdapter()
    assert build_event_key(adapter._normalize_trc20(first,TRON))==build_event_key(adapter._normalize_trc20(second,TRON))

def test_tron_approval_is_not_value_movement():
    raw=trc20_row();raw["type"]="Approval"
    tx=prepare_event(TronAdapter()._normalize_trc20(raw,TRON))
    assert not GraphStore.response_graph(TRON,[tx],[])["edges"]

def test_failed_solana_retains_provider_evidence():
    from tests.test_solana import tx_result, system_transfer
    raw=tx_result([system_transfer()],err={"InstructionError":[0,"Custom"]})
    tx=prepare_event(SolanaAdapter().parse_transaction(raw,signature=SIG)[0])
    assert tx.raw_payload["provider"]==raw and execution_status(tx)=="failed"
    assert tx.value_native=="" and not GraphStore.response_graph(SOLANA,[tx],[])["edges"]

def test_missing_solana_meta_is_unavailable_with_raw_evidence():
    from tests.test_solana import tx_result, system_transfer
    raw=tx_result([system_transfer()]);raw["meta"]=None
    tx=prepare_event(SolanaAdapter().parse_transaction(raw,signature=SIG)[0])
    assert tx.raw_payload["provider"]==raw and execution_status(tx)=="unavailable"
    assert tx.value_native==""


@pytest.mark.asyncio
@pytest.mark.parametrize("value",[1.1,True,None,"1"])
async def test_bitcoin_balance_rejects_non_integer_atomic_provider_values(monkeypatch,value):
    adapter=BitcoinAdapter()
    monkeypatch.setattr(adapter,"_fetch",AsyncMock(return_value=({"chain_stats":{"funded_txo_sum":value,"spent_txo_sum":0,"tx_count":0},"mempool_stats":{"funded_txo_sum":0,"spent_txo_sum":0,"tx_count":0}},"fixture")))
    with pytest.raises(ChainDataError):await adapter.lookup_address(BTC)
