import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import httpx
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from greedy_collector.chains.registry import Capability, get_chain
from greedy_collector.chains.solana import (
    SolanaAdapter, TOKEN_PROGRAM, TOKEN_2022_PROGRAM, SYSTEM_PROGRAM,
    base58_decode, base58_encode, validate_pubkey, validate_signature,
)
from greedy_collector.chains.base import ChainDataError, RpcReadError
from greedy_collector.resolver import resolve_identifier
from greedy_collector.transaction_identity import build_event_key, event_identity
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import Base, Transaction, WatchlistWallet, WalletAlert, MonitoringRun
from greedy_collector.graph import GraphStore
from greedy_collector.schemas import ManualLabelCreate, NormalizedTransaction
from greedy_collector.discovery.registry import REGISTRY as DISCOVERY_REGISTRY

FOCUS = "11111111111111111111111111111111"
OTHER = base58_encode(bytes(range(32)))
MINT = base58_encode(bytes(range(32, 64)))
SIG = base58_encode(bytes(range(64)))
SIG_2 = base58_encode(bytes(range(1, 65)))
TOKEN_ACCOUNT_A = base58_encode(bytes(range(2, 34)))
TOKEN_ACCOUNT_B = base58_encode(bytes(range(3, 35)))


def adapter():
    return SolanaAdapter()


def tx_result(instructions, *, inner=None, err=None, version="legacy", token_balances=None):
    return {
        "slot": 123,
        "blockTime": 1_700_000_000,
        "version": version,
        "transaction": {"signatures": [SIG], "message": {"accountKeys": [FOCUS, OTHER, TOKEN_ACCOUNT_A, TOKEN_ACCOUNT_B, MINT], "instructions": instructions}},
        "meta": {"err": err, "fee": 5000, "innerInstructions": inner or [],
                 "preTokenBalances": (token_balances or {}).get("pre", []),
                 "postTokenBalances": (token_balances or {}).get("post", [])},
    }


def system_transfer(source=FOCUS, destination=OTHER, lamports=1250000000):
    return {"program": "system", "programId": SYSTEM_PROGRAM, "parsed": {"type": "transfer", "info": {"source": source, "destination": destination, "lamports": lamports}}}


def token_transfer(program_id=TOKEN_PROGRAM, kind="transferChecked", amount="125", decimals=2):
    info = {"source": TOKEN_ACCOUNT_A, "destination": TOKEN_ACCOUNT_B, "mint": MINT,
            "tokenAmount": {"amount": amount, "decimals": decimals, "uiAmountString": "1.25"}}
    if kind == "transfer":
        info.pop("tokenAmount")
        info.pop("mint")
        info["amount"] = amount
    return {"program": "spl-token", "programId": program_id, "parsed": {"type": kind, "info": info}}


def token_balances(owner_a=FOCUS, owner_b=OTHER):
    def row(index, owner):
        return {"accountIndex": index, "mint": MINT, "owner": owner, "uiTokenAmount": {"amount": "0", "decimals": 2}}
    return {"pre": [row(2, owner_a), row(3, owner_b)], "post": [row(2, owner_a), row(3, owner_b)]}


def test_pubkey_and_transaction_signature_decode_to_expected_sizes():
    assert len(base58_decode(validate_pubkey(FOCUS))) == 32
    assert len(base58_decode(validate_signature(SIG))) == 64
    with pytest.raises(ValueError):
        validate_pubkey("0" + FOCUS[1:])
    with pytest.raises(ValueError):
        validate_pubkey("1" * 31)
    with pytest.raises(ValueError):
        validate_signature(FOCUS)


def test_registry_resolver_and_existing_chain_precedence_are_local(monkeypatch):
    definition = get_chain("solana")
    assert (definition.display_name, definition.native_symbol, definition.family.value, definition.native_decimals) == ("Solana", "SOL", "account", 9)
    assert definition.explorer_url == "https://explorer.solana.com"
    assert Capability.MONITORING in definition.capabilities
    assert resolve_identifier(FOCUS, "solana")["chain"] == "solana"
    assert resolve_identifier("\n" + OTHER + "\t")["chain"] == "solana"
    assert resolve_identifier(SIG)["kind"] == "transaction"
    assert "Solana transaction signature" in resolve_identifier("not-a-chain-value")["supported"]
    assert resolve_identifier(SIG, "solana")["chain"] == "solana"
    assert resolve_identifier("1BoatSLRHtKNngkdXEeobR76b53LETtpyT")["chain"] == "bitcoin"
    tron = "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"
    assert resolve_identifier(tron, "tron")["chain"] == "tron"
    instance = adapter()
    monkeypatch.setattr(instance, "_rpc", AsyncMock(side_effect=AssertionError("address resolution must be local")))
    assert instance.validate_address(FOCUS) == FOCUS
    instance._rpc.assert_not_awaited()


def test_unknown_version_and_invalid_signature_are_not_misparsed():
    with pytest.raises(ValueError):
        adapter().normalize_transaction_id("0" * 88)
    result = adapter().parse_transaction(tx_result([system_transfer()], version=2), signature=SIG)
    assert len(result) == 1
    assert result[0].from_address == result[0].to_address == ""
    assert result[0].raw_payload["_public"]["transaction_version_status"] == "unsupported"
    current = adapter().parse_transaction(tx_result([system_transfer()], version=1), signature=SIG)
    assert current[0].from_address == FOCUS and current[0].to_address == OTHER


def test_balance_exact_and_rpc_configuration_url_is_not_reflected(monkeypatch):
    instance = adapter()
    calls = []
    async def rpc(method, params, **kwargs):
        calls.append((method, params, kwargs))
        return {"context": {"slot": 99}, "value": 1234567891}
    monkeypatch.setattr(instance, "_rpc", rpc)
    value = asyncio.run(instance.lookup_address(FOCUS))
    assert value["balance_native"] == "1.234567891"
    assert calls[0][0] == "getBalance" and calls[0][1][1]["commitment"] == "finalized"
    secret_url = "https://rpc.example/key?secret=do-not-leak"
    monkeypatch.setattr(instance.settings, "solana_rpc_url", secret_url)
    async def fail(*args, **kwargs):
        raise RpcReadError("rate_limited")
    monkeypatch.setattr(instance, "_post_bounded", fail)
    with pytest.raises(ChainDataError) as exc:
        asyncio.run(SolanaAdapter._rpc(instance, "getBalance", [FOCUS]))
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(("status", "category"), [(403, "configuration_unavailable"), (429, "rate_limited"), (503, "transport_failed")])
def test_rpc_transport_http_failures_are_safe(monkeypatch, status, category):
    actual = httpx.AsyncClient
    monkeypatch.setattr("greedy_collector.chains.base.httpx", SimpleNamespace(
        AsyncClient=lambda **kwargs: actual(transport=httpx.MockTransport(lambda request: httpx.Response(status, headers={"Retry-After": "2"}, content=b"secret")), **kwargs),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError,
    ))
    with pytest.raises(RpcReadError) as exc:
        asyncio.run(adapter()._post_bounded("https://rpc.example/key?secret=hidden", {"method": "getBalance"}))
    assert exc.value.category == category
    if status == 429:
        assert exc.value.retry_after_seconds == 2
    assert "secret" not in str(exc.value)


def test_short_retry_after_is_honored_once_without_unbounded_retry(monkeypatch):
    instance = adapter()
    post = AsyncMock(side_effect=[RpcReadError("rate_limited", retry_after_seconds=0),
        {"jsonrpc": "2.0", "id": 1, "result": {"value": 7}}])
    sleep = AsyncMock()
    monkeypatch.setattr(instance, "_post_bounded", post)
    monkeypatch.setattr("greedy_collector.chains.solana.asyncio.sleep", sleep)
    result = asyncio.run(instance._rpc("getBalance", [FOCUS]))
    assert result["value"] == 7 and post.await_count == 2 and sleep.await_count == 1


@pytest.mark.parametrize(("mode", "category"), [("timeout", "timeout"), ("malformed", "invalid_provider_response")])
def test_rpc_timeout_and_malformed_json_are_sanitized(monkeypatch, mode, category):
    actual = httpx.AsyncClient
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("https://rpc.example/?secret=hidden", request=request)
        return httpx.Response(200, content=b"not-json")
    monkeypatch.setattr("greedy_collector.chains.base.httpx", SimpleNamespace(
        AsyncClient=lambda **kwargs: actual(transport=httpx.MockTransport(handler), **kwargs),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError,
    ))
    with pytest.raises(RpcReadError) as exc:
        asyncio.run(adapter()._post_bounded("https://rpc.example/?secret=hidden", {"method": "getBalance"}))
    assert exc.value.category == category
    assert "hidden" not in str(exc.value)


def test_json_rpc_error_objects_and_get_transaction_parameters_are_safe(monkeypatch):
    instance = adapter()
    calls = []
    async def post(_url, payload, **kwargs):
        method, params = payload["method"], payload["params"]
        calls.append((method, params))
        return ({"jsonrpc":"2.0", "id":1, "result":{"_activity":True}} if method == "getTransaction"
                else {"jsonrpc":"2.0", "id":1, "error":{"code":-1,"message":"credential hidden"}})
    monkeypatch.setattr(instance, "_post_bounded", post)
    with pytest.raises(ChainDataError, match="^solana_provider_rejected_request$") as exc:
        asyncio.run(instance.lookup_address(FOCUS))
    assert "hidden" not in str(exc.value)
    value = asyncio.run(instance._get_transaction(SIG))
    assert value == {"_activity":True}
    assert calls[-1][0] == "getTransaction"
    assert calls[-1][1][1] == {"commitment":"confirmed", "encoding":"jsonParsed", "maxSupportedTransactionVersion":1}


def test_rpc_signature_history_is_capped_and_before_cursor_is_supported(monkeypatch):
    instance = adapter()
    calls = []
    async def rpc(method, params, **kwargs):
        calls.append((method, params))
        return [{"signature": SIG, "slot": 9, "err": None}]
    monkeypatch.setattr(instance, "_rpc", rpc)
    rows = asyncio.run(instance._signatures(FOCUS, limit=100, before=SIG_2))
    assert rows[0]["signature"] == SIG
    assert calls[0][0] == "getSignaturesForAddress"
    assert calls[0][1][1]["limit"] == 100 and calls[0][1][1]["before"] == SIG_2


def test_system_transfers_have_instruction_event_keys_and_failed_rows_have_no_flow():
    instance = adapter()
    parsed = instance.parse_transaction(tx_result([system_transfer(), system_transfer(OTHER, FOCUS, 5)]), focus_address=FOCUS)
    assert len(parsed) == 2
    assert [build_event_key(item) for item in parsed] == ["solana-ix:0", "solana-ix:1"]
    assert event_identity(parsed[0]).startswith(f"solana:{SIG}:solana-ix:0")
    assert parsed[0].value_native == "1.25" and parsed[0].direction == "outgoing"
    assert parsed[1].direction == "incoming"
    graph = GraphStore.response_graph(FOCUS, parsed, [])
    assert len(graph["edges"]) == 2
    assert {node["chain"] for node in graph["nodes"]} == {"solana"}
    assert {edge["event_key"] for edge in graph["edges"]} == {"solana-ix:0", "solana-ix:1"}
    failed = instance.parse_transaction(tx_result([system_transfer()], err={"InstructionError": [0, "Custom"]}), signature=SIG)
    assert len(failed) == 1 and failed[0].from_address == "" and failed[0].to_address == ""
    assert failed[0].raw_payload["_public"]["execution_status"] == "failed"


def test_inner_system_transfer_uses_outer_and_inner_instruction_positions():
    value = tx_result([], inner=[{"index": 3, "instructions": [system_transfer(), system_transfer(OTHER, FOCUS, 7)]}])
    parsed = adapter().parse_transaction(value, focus_address=FOCUS)
    assert [build_event_key(item) for item in parsed] == ["solana-inner:3:0", "solana-inner:3:1"]


@pytest.mark.parametrize(("program", "kind"), [(TOKEN_PROGRAM, "transfer"), (TOKEN_PROGRAM, "transferChecked"), (TOKEN_2022_PROGRAM, "transferChecked")])
def test_spl_transfer_owner_mint_decimals_and_program_family(program, kind):
    value = tx_result([token_transfer(program, kind)], token_balances=token_balances())
    parsed = adapter().parse_transaction(value, focus_address=FOCUS)
    assert len(parsed) == 1
    tx = parsed[0]
    assert tx.from_address == FOCUS and tx.to_address == OTHER and tx.direction == "outgoing"
    assert tx.asset_contract == MINT and tx.value_native == "1.25"
    assert tx.raw_payload["_public"]["asset_type"] in {"spl_token", "token2022"}
    assert tx.raw_payload["_public"]["source_token_account"] == TOKEN_ACCOUNT_A


def test_repeated_spl_transfers_keep_instruction_identity_unknown_owners_do_not_form_edges():
    item = token_transfer()
    value = tx_result([item, item], token_balances=token_balances())
    parsed = adapter().parse_transaction(value, focus_address=FOCUS)
    assert [build_event_key(tx) for tx in parsed] == ["solana-ix:0", "solana-ix:1"]
    again = adapter().parse_transaction(value, focus_address=FOCUS)
    assert [event_identity(tx) for tx in parsed] == [event_identity(tx) for tx in again]
    unknown = adapter().parse_transaction(tx_result([item]), focus_address=FOCUS)[0]
    assert unknown.from_address == unknown.to_address == ""
    assert unknown.raw_payload["_public"]["source_owner_known"] is False
    graph = GraphStore.response_graph(FOCUS, parsed, [])
    assert graph["edges"][0]["event_provenance"]["source_token_account"] == TOKEN_ACCOUNT_A
    assert graph["edges"][0]["event_provenance"]["token_mint"] == MINT


def test_inner_token_transfer_and_duplicate_instruction_path_dedupe():
    item = token_transfer()
    value = tx_result([], inner=[{"index": 4, "instructions": [item, item]}], token_balances=token_balances())
    parsed = adapter().parse_transaction(value, focus_address=FOCUS)
    assert [build_event_key(tx) for tx in parsed] == ["solana-inner:4:0", "solana-inner:4:1"]


def test_monitoring_delta_fetches_only_new_signatures_and_reports_lost_boundary(monkeypatch):
    instance = adapter()
    monkeypatch.setattr(instance, "_signatures", AsyncMock(return_value=[{"signature": SIG_2}, {"signature": SIG}]))
    monkeypatch.setattr(instance, "_get_transaction", AsyncMock(return_value=tx_result([system_transfer()])))
    result = asyncio.run(instance.monitoring_delta(FOCUS, f"solana:{SIG}:solana-ix:0"))
    assert result["boundary_found"] is True and len(result["transactions"]) == 1
    assert instance._get_transaction.await_count == 1
    instance._signatures.return_value = [{"signature": SIG_2}]
    lost = asyncio.run(instance.monitoring_delta(FOCUS, f"solana:{SIG}:solana-ix:0"))
    assert lost == {"transactions": [], "boundary_found": False}


def test_generic_discovery_labels_and_risk_boundaries_accept_solana():
    label = ManualLabelCreate(chain="solana", address=FOCUS, label="Review", type="Unknown")
    assert label.chain == "solana"
    transforms = DISCOVERY_REGISTRY.transforms
    assert "solana" in transforms["wallet.local_labels"].chains
    assert "solana" in transforms["wallet.manual_source_observation"].chains
    assert "solana" in transforms["wallet.public_code_mentions"].chains
    assert transforms["wallet.ens_primary_name"].chains == ("ethereum",)
    assert transforms["wallet.graphsense_public_tags"].chains == ("bitcoin", "ethereum")
    assert adapter().behavioral_risk is False


def test_lookup_address_and_transaction_api_keep_multiple_solana_events(monkeypatch):
    import main
    from greedy_collector.chains.solana import SolanaAdapter

    engine = create_fk_enabled_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def memory_db():
        with Session(engine) as session:
            yield session
    previous = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db] = memory_db
    monkeypatch.setattr(main, "start_monitoring", lambda: None)
    monkeypatch.setattr(main, "stop_monitoring", lambda: None)
    async def noop_start(_app):
        return None
    async def noop_stop(_app):
        return None
    monkeypatch.setattr(main, "start_discovery", noop_start)
    monkeypatch.setattr(main, "stop_discovery", noop_stop)

    rows = adapter().parse_transaction(tx_result([system_transfer(), system_transfer(OTHER, FOCUS, 9)]), focus_address=FOCUS)
    async def fake_balance(self, address):
        return {"chain": "solana", "address": address, "balance_native": "1.25", "source_api": "solana-json-rpc"}
    async def fake_transactions(self, address, **_kwargs):
        return rows
    async def fake_lookup_events(self, signature):
        return rows
    monkeypatch.setattr(SolanaAdapter, "lookup_address", fake_balance)
    monkeypatch.setattr(SolanaAdapter, "transactions", fake_transactions)
    monkeypatch.setattr(SolanaAdapter, "lookup_transaction_events", fake_lookup_events)
    try:
        with TestClient(main.app) as client:
            resolved = client.post("/api/greedy-collector/resolve", json={"input": OTHER}).json()
            assert resolved["chain"] == "solana" and resolved["kind"] == "address"
            response = client.post("/api/greedy-collector/lookup/address", json={"chain": "solana", "address": OTHER})
            assert response.status_code == 200
            body = response.json()
            assert body["address"]["chain"] == "solana" and body["address"]["balance_native"] == "1.25"
            assert [tx["event_key"] for tx in body["transactions"]] == ["solana-ix:0", "solana-ix:1"]
            client.post("/api/greedy-collector/lookup/address", json={"chain": "solana", "address": OTHER})
            with Session(engine) as session:
                assert len(session.scalars(select(Transaction).where(Transaction.chain == "solana")).all()) == 2
            tx_response = client.post("/api/greedy-collector/lookup/tx", json={"chain": "solana", "tx_hash": SIG})
            assert tx_response.status_code == 200 and len(tx_response.json()["events"]) == 2
            assert SIG not in tx_response.text or "secret" not in tx_response.text
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        engine.dispose()


def test_sol_monitor_silent_baseline_event_alerts_dedup_and_boundary_loss(monkeypatch):
    from greedy_collector import monitoring
    from greedy_collector.services import GreedyCollectorService

    engine = create_fk_enabled_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        watch = WatchlistWallet(chain="solana", address=OTHER, label="test", enabled=True)
        db.add(watch); db.commit(); watch_id = watch.id

    baseline = [GreedyCollectorService._tx_dict(tx) for tx in adapter().parse_transaction(
        tx_result([system_transfer(), system_transfer(OTHER, FOCUS, 11)]), focus_address=OTHER, signature=SIG)]
    recent = [GreedyCollectorService._tx_dict(tx) for tx in adapter().parse_transaction(
        tx_result([system_transfer(OTHER, FOCUS, 13), system_transfer(OTHER, FOCUS, 17)]), focus_address=OTHER, signature=SIG_2)]
    instance = adapter()
    outcomes = [
        {"transactions": recent, "boundary_found": True},
        {"transactions": recent, "boundary_found": True},
        {"transactions": [], "boundary_found": False},
    ]
    async def delta(_address, _cursor):
        return outcomes.pop(0)
    async def balance(_address):
        return {"chain":"solana", "balance_native":"1", "source_api":"solana-json-rpc"}
    async def service_lookup(_db, _request, *, profile_override=None, transactions_override=None):
        rows = baseline if transactions_override is None else transactions_override
        return {"transactions":rows, "risk":{"score":0, "findings":[]}}
    monkeypatch.setattr(instance, "monitoring_delta", delta)
    monkeypatch.setattr(instance, "lookup_address", balance)
    monkeypatch.setattr(monitoring, "get_chain_adapter", lambda _chain, *_caps: instance)
    monkeypatch.setattr(monitoring, "SessionLocal", sessions)
    monkeypatch.setattr(monitoring, "GreedyCollectorService", lambda: SimpleNamespace(lookup_address=service_lookup))

    first = asyncio.run(monitoring._monitor_chain("solana", watch_id))
    with sessions() as db:
        wallet = db.get(WatchlistWallet, watch_id)
        assert wallet.last_seen_tx == SIG
        assert db.query(WalletAlert).count() == 0
    assert first["processed"] == 1

    second = asyncio.run(monitoring._monitor_chain("solana", watch_id))
    with sessions() as db:
        wallet = db.get(WatchlistWallet, watch_id)
        assert wallet.last_seen_tx == SIG_2
        assert db.query(WalletAlert).count() == 2
        assert len({row.dedupe_key for row in db.query(WalletAlert).all()}) == 2
        assert db.query(MonitoringRun).filter_by(status="completed").count() == 2
    assert second["processed"] == 1

    repeated = asyncio.run(monitoring._monitor_chain("solana", watch_id))
    assert repeated["processed"] == 1
    with sessions() as db:
        assert db.query(WalletAlert).count() == 2
        assert db.query(MonitoringRun).filter_by(status="completed").count() == 3

    asyncio.run(monitoring._monitor_chain("solana", watch_id))
    with sessions() as db:
        assert db.query(WalletAlert).count() == 2
        assert db.query(MonitoringRun).filter_by(status="continuity_loss").count() == 1
        assert db.get(WatchlistWallet, watch_id).last_seen_tx == SIG_2
    engine.dispose()
