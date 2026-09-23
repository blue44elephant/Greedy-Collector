"""MC-2 TRON adapter, normalization, and generic subsystem boundaries."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from greedy_collector.chains import get_chain, get_chain_capabilities, Capability
from greedy_collector.chains.base import ChainDataError
from greedy_collector.chains.tron import (
    MAX_PAGES,
    PAGE_SIZE,
    TronAdapter,
    tron_address_from_hex,
    tron_address_to_hex,
)
from greedy_collector.discovery.registry import REGISTRY as DISCOVERY_REGISTRY
from greedy_collector.graph import GraphStore
from greedy_collector.models import Base, Label, MonitoringRun, Transaction, WalletAlert, WatchlistWallet
from greedy_collector.resolver import resolve_identifier
from greedy_collector.risk import ExplainableRiskEngine
from greedy_collector.schemas import CaseEntityCreate, LookupRequest, ManualLabelCreate, NormalizedTransaction
from greedy_collector.services import GreedyCollectorService
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.attribution.domain import ClaimInput


FOCUS = "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"
FOCUS_HEX = "415cbdd86a2fa8dc4bddd8a8f69dba48572eec07fb"
OTHER = tron_address_from_hex("41" + "11" * 20)
THIRD = tron_address_from_hex("41" + "22" * 20)
TOKEN = tron_address_from_hex("41" + "33" * 20)
TOKEN_2 = tron_address_from_hex("41" + "44" * 20)
TX = "a" * 64


def adapter(key="test-only-tron-key"):
    item = TronAdapter()
    item.settings = item.settings.model_copy(update={"tron_pro_api_key": key})
    return item


def install_transport(monkeypatch, handler):
    actual = httpx.AsyncClient
    monkeypatch.setattr(
        "greedy_collector.chains.tron.httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: actual(transport=httpx.MockTransport(handler), **kwargs),
            TimeoutException=httpx.TimeoutException,
            HTTPError=httpx.HTTPError,
        ),
    )


def native_row(tx=TX, sender=OTHER, recipient=FOCUS, amount=1_250_000, timestamp=1_700_000_000_000):
    return {
        "txID": tx,
        "block_timestamp": timestamp,
        "blockNumber": 123,
        "raw_data": {"contract": [{"type": "TransferContract", "parameter": {"value": {
            "owner_address": sender, "to_address": recipient, "amount": amount,
        }}}]},
    }


def trc20_row(*, tx=TX, sender=OTHER, recipient=FOCUS, contract=TOKEN,
              value="1234567", decimals=6, symbol="USDJ", timestamp=1_700_000_001_000):
    return {
        "transaction_id": tx,
        "block_timestamp": timestamp,
        "block": 124,
        "from": sender,
        "to": recipient,
        "value": value,
        "token_info": {"address": contract, "symbol": symbol, "name": "Test token", "decimals": decimals},
    }


@pytest.mark.parametrize("value", [
    FOCUS[:-1] + ("1" if FOCUS[-1] != "1" else "2"),
    "A" + FOCUS[1:],
    "T123",
    "0x" + FOCUS_HEX[2:],
    "T0" + "1" * 32,
])
def test_tron_address_rejects_bad_checksum_prefix_length_and_alphabet(value):
    with pytest.raises(ValueError):
        TronAdapter().validate_address(value)


def test_tron_address_codec_round_trip_and_chain_identity_separation():
    assert tron_address_to_hex("  " + FOCUS + " ") == FOCUS_HEX
    assert tron_address_from_hex(FOCUS_HEX.upper()) == FOCUS
    assert get_chain("tron").adapter().normalize_address(FOCUS) == FOCUS
    ethereum = "0x" + FOCUS_HEX[2:]
    assert ("tron", FOCUS) != ("ethereum", ethereum.lower())


def test_registry_and_resolver_are_local_and_preserve_btc_eth(monkeypatch):
    definition = get_chain("tron")
    assert (definition.display_name, definition.native_symbol, definition.family.value,
            definition.native_decimals, definition.evm_compatible) == ("TRON", "TRX", "account", 6, False)
    expected = {Capability.ADDRESS_VALIDATION, Capability.BALANCE, Capability.TRANSACTION_LOOKUP,
                Capability.TRANSACTION_HISTORY, Capability.TOKEN_TRANSFERS, Capability.COUNTERPARTIES,
                Capability.GRAPH, Capability.MONITORING, Capability.LABELS, Capability.CASES,
                Capability.ATTRIBUTION, Capability.DISCOVERY}
    assert expected <= get_chain_capabilities("tron")
    monkeypatch.setattr(httpx.AsyncClient, "request", AsyncMock(side_effect=AssertionError("provider traffic")))
    assert resolve_identifier(" \n" + FOCUS + "\t")["chain"] == "tron"
    assert resolve_identifier(TX)["chain"] == "bitcoin"
    assert resolve_identifier(TX, chain_hint="tron") == {
        "kind": "transaction", "chain": "tron", "normalized": TX, "lookup_type": "transaction"
    }
    assert resolve_identifier("0x" + "1" * 40)["chain"] == "ethereum"
    assert resolve_identifier("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")["chain"] == "bitcoin"


def test_trongrid_balance_is_exact_and_uses_secret_header(monkeypatch):
    seen = {}
    def handler(request):
        seen["header"] = request.headers.get("TRON-PRO-API-KEY")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"success": True, "data": [{"balance": 1_000_001}]})
    install_transport(monkeypatch, handler)
    result = asyncio.run(adapter().lookup_address(FOCUS))
    assert result["balance_native"] == "1.000001"
    assert result["source_api"] == "trongrid"
    assert seen["header"] == "test-only-tron-key"
    assert "test-only-tron-key" not in seen["url"]


def test_trongrid_missing_key_never_opens_transport(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "stream", AsyncMock(side_effect=AssertionError("network")))
    with pytest.raises(ChainDataError, match="^tron_configuration_unavailable$"):
        asyncio.run(adapter("").lookup_address(FOCUS))


@pytest.mark.parametrize("status,category", [
    (400, "tron_request_rejected"), (401, "tron_configuration_unavailable"),
    (403, "tron_configuration_unavailable"), (404, "tron_not_found"),
    (429, "tron_rate_limited"), (500, "tron_provider_unavailable"),
])
def test_trongrid_safe_http_errors(monkeypatch, status, category):
    install_transport(monkeypatch, lambda request: httpx.Response(status, json={"error": "secret test-only-tron-key"}))
    with pytest.raises(ChainDataError, match="^" + category + "$") as error:
        asyncio.run(adapter().lookup_address(FOCUS))
    assert "test-only-tron-key" not in str(error.value)


@pytest.mark.parametrize("mode", ["malformed", "success_false", "timeout"])
def test_trongrid_malformed_failure_and_timeout_are_safe(monkeypatch, mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("credential test-only-tron-key", request=request)
        if mode == "malformed":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json={"success": False, "Error": "test-only-tron-key"})
    install_transport(monkeypatch, handler)
    expected = "tron_timeout" if mode == "timeout" else "tron_invalid_provider_response"
    with pytest.raises(ChainDataError, match="^" + expected + "$") as error:
        asyncio.run(adapter().lookup_address(FOCUS))
    assert "test-only-tron-key" not in str(error.value)


def test_fingerprint_pagination_and_bounds(monkeypatch):
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        page = len(calls)
        return httpx.Response(200, json={
            "success": True,
            "data": [{"page": page, "row": index} for index in range(PAGE_SIZE)],
            "meta": {"fingerprint": f"cursor-{page}"},
        })
    install_transport(monkeypatch, handler)
    rows = asyncio.run(adapter()._history(f"/v1/accounts/{FOCUS}/transactions", FOCUS))
    assert len(rows) == PAGE_SIZE * MAX_PAGES
    assert len(calls) == MAX_PAGES
    assert calls[0]["limit"] == str(PAGE_SIZE) and "fingerprint" not in calls[0]
    assert calls[1]["fingerprint"] == "cursor-1"
    assert all(call["only_confirmed"] == "true" for call in calls)


def test_native_trc10_and_trc20_normalization_and_direction():
    item = adapter()
    incoming = item._normalize_account_transaction(native_row(), FOCUS)
    outgoing = item._normalize_account_transaction(native_row(sender=FOCUS, recipient=OTHER), FOCUS)
    trc10 = native_row(tx="b" * 64, amount=42)
    trc10["raw_data"]["contract"][0]["type"] = "TransferAssetContract"
    trc10["raw_data"]["contract"][0]["parameter"]["value"]["asset_name"] = "31303032303030"
    asset = item._normalize_account_transaction(trc10, FOCUS)
    token_in = item._normalize_trc20(trc20_row(), FOCUS)
    token_out = item._normalize_trc20(trc20_row(sender=FOCUS, recipient=OTHER), FOCUS)
    assert (incoming.value_native, incoming.token_symbol, incoming.direction) == ("1.25", "TRX", "incoming")
    assert outgoing.direction == "outgoing"
    assert (asset.value_native, asset.token_symbol, asset.raw_payload["_public"]["asset_type"]) == ("42", "1002000", "trc10")
    assert (token_in.value_native, token_in.direction) == ("1.234567", "incoming")
    assert token_out.direction == "outgoing"
    assert token_in.raw_payload["_public"] == {
        "asset_type": "trc20", "token_contract": TOKEN, "token_name": "Test token",
        "token_decimals": 6, "raw_value": "1234567", "confirmed": True,
        "event_id": token_in.raw_payload["_event_id"],
    }


def test_unsupported_contract_is_explicit_without_guessed_flow():
    row = native_row()
    row["raw_data"]["contract"][0]["type"] = "VoteWitnessContract"
    marker = adapter()._normalize_account_transaction(row, FOCUS)
    assert marker.from_address == marker.to_address == ""
    assert marker.direction == "unknown"
    assert marker.raw_payload["_public"]["unsupported_type"] == "VoteWitnessContract"


def test_merge_preserves_multiple_token_transfers_in_one_tx_and_sorts(monkeypatch):
    item = adapter()
    first = trc20_row(contract=TOKEN, value="100", timestamp=1_700_000_003_000, symbol="A")
    second = trc20_row(contract=TOKEN_2, value="200", timestamp=1_700_000_002_000, symbol="B")
    native = native_row(tx="c" * 64, timestamp=1_700_000_001_000)
    item._history = AsyncMock(side_effect=[[native], [second, first, first]])
    rows = asyncio.run(item.transactions(FOCUS))
    assert [row.token_symbol for row in rows] == ["A", "B", "TRX"]
    assert len({item.transfer_identity(row) for row in rows}) == 3
    assert [row.tx_hash for row in rows[:2]] == [TX, TX]


def test_direct_transaction_lookup_uses_solidified_endpoint(monkeypatch):
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=native_row())
    install_transport(monkeypatch, handler)
    row = asyncio.run(adapter().lookup_transaction(TX.upper()))
    assert row.tx_hash == TX and row.direction == "unknown"
    assert seen == {"path": "/walletsolidity/gettransactionbyid", "body": {"value": TX, "visible": True}}


def test_graph_chain_identity_and_distinct_tron_transfer_edges():
    item = adapter()
    one = item._normalize_trc20(trc20_row(contract=TOKEN, value="100", symbol="A"), FOCUS)
    two = item._normalize_trc20(trc20_row(contract=TOKEN_2, value="200", symbol="B"), FOCUS)
    ethereum = NormalizedTransaction(tx_hash="0x" + "1" * 64, chain="ethereum",
        from_address="0x" + FOCUS_HEX[2:], to_address="0x" + "2" * 40,
        token_symbol="ETH", source_api="test")
    graph = GraphStore.response_graph(FOCUS, [one, two, ethereum], [])
    assert len(graph["edges"]) == 3 and len({edge["id"] for edge in graph["edges"]}) == 3
    assert {node["chain"] for node in graph["nodes"]} == {"tron", "ethereum"}
    assert any(node["id"].startswith("tron:") for node in graph["nodes"])
    assert any(node["id"].startswith("ethereum:") for node in graph["nodes"])


def test_labels_discovery_and_risk_boundary():
    assert ManualLabelCreate(chain="tron", address=FOCUS, label="Known service", type="Exchange")
    assert "tron" in DISCOVERY_REGISTRY.transforms["wallet.local_labels"].chains
    assert "tron" in DISCOVERY_REGISTRY.transforms["wallet.manual_source_observation"].chains
    assert "tron" in DISCOVERY_REGISTRY.transforms["wallet.public_code_mentions"].chains
    assert "tron" not in DISCOVERY_REGISTRY.transforms["wallet.ens_primary_name"].chains
    assert "tron" not in DISCOVERY_REGISTRY.transforms["wallet.graphsense_public_tags"].chains
    txs = [NormalizedTransaction(tx_hash=str(i), chain="tron", from_address=FOCUS,
        to_address=OTHER, value_native="100", token_symbol="TRX", direction="outgoing", source_api="test") for i in range(6)]
    engine = ExplainableRiskEngine()
    generic = engine.evaluate(FOCUS, txs, [{"address": OTHER, "type": "Scam", "confidence": .8, "source": "test"}], include_behavioral=False)
    assert {row["rule_id"] for row in generic["findings"]} == {"direct_scam"}
    assert generic["findings"][0]["evidence"]["counterparty"] == OTHER.lower()


def test_tron_lookup_persists_public_token_metadata_and_source_label(monkeypatch):
    engine, sessions = memory_sessions()
    item = adapter()
    token = item._normalize_trc20(trc20_row(), FOCUS)
    monkeypatch.setattr(TronAdapter, "lookup_address", AsyncMock(return_value={
        "chain": "tron", "address": FOCUS, "balance_native": "2.5", "source_api": "trongrid"
    }))
    monkeypatch.setattr(TronAdapter, "transactions", AsyncMock(return_value=[token]))
    service = GreedyCollectorService.__new__(GreedyCollectorService)
    service.risk_engine = ExplainableRiskEngine()
    service.graph_store = SimpleNamespace(store_transactions=lambda rows: None)
    with sessions() as db:
        db.add(Label(chain="tron", address=OTHER, label="Reported scam", type="Scam", source="analyst", confidence=.9))
        db.commit()
        result = asyncio.run(service.lookup_address(db, LookupRequest(chain="tron", address=FOCUS)))
        assert result["address"]["balance_native"] == "2.5"
        assert result["transactions"][0]["asset_type"] == "trc20"
        assert result["transactions"][0]["token_contract"] == TOKEN
        assert result["risk"]["behavioral_supported"] is False
        assert {row["rule_id"] for row in result["risk"]["findings"]} == {"direct_scam"}
        stored = db.scalars(select(Transaction)).all()
        assert len(stored) == 1 and stored[0].chain == "tron"
        assert stored[0].raw_payload["_public"]["token_decimals"] == 6
    engine.dispose()


def test_tron_local_labels_manual_source_cases_and_attribution():
    from greedy_collector.discovery.manual_source import ManualSourceService
    engine, sessions = memory_sessions()
    with sessions() as db:
        db.add_all([
            Label(chain="tron", address=OTHER, label="TRON only", type="Unknown", source="test"),
            Label(chain="ethereum", address="0x" + "11" * 20, label="Ethereum only", type="Unknown", source="test"),
            Label(chain="any", address=OTHER, label="Any scope", type="Unknown", source="test"),
        ])
        db.commit()
        tx = NormalizedTransaction(tx_hash=TX, chain="tron", from_address=OTHER, to_address=FOCUS, source_api="test")
        service = GreedyCollectorService.__new__(GreedyCollectorService)
        assert {row["label"] for row in service._labels_for_transactions(db, [tx])} == {"TRON only", "Any scope"}
        capture = {
            "subject": {"chain": "tron", "address": FOCUS},
            "source_type": "webpage", "source_url": "https://example.invalid/tron",
            "observed_at": "2026-09-23T00:00:00Z", "context": "Exact public TRON address " + FOCUS,
            "analyst_note": "Explicit local test capture.",
        }
        manual = ManualSourceService(db, metadata_only=True)
        preview = manual.preview(capture)
        row = manual.capture({"capture": capture, "expected_preview_fingerprint": preview["preview_fingerprint"]})
        assert row["observation"]["source_snapshot"]["subject"] == {"chain": "tron", "address": FOCUS}
    assert CaseEntityCreate(entity_type="wallet", entity_ref=FOCUS, metadata={"chain": "tron", "address": FOCUS})
    claim = ClaimInput(entity_id="entity", chain="tron", subject_ref=FOCUS,
                       relationship="operated_by", scope_note="TRON mainnet")
    assert claim.subject_ref == FOCUS and claim.chain == "tron"
    engine.dispose()


def test_github_discovery_uses_exact_canonical_tron_address(monkeypatch):
    from greedy_collector.discovery import github
    seen = {}
    async def fake_api(context, url, **kwargs):
        seen.update(kwargs["params"])
        return {"total_count": 0, "incomplete_results": False, "items": []}, {}
    monkeypatch.setenv("DISCOVERY_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github, "api_json", fake_api)
    context = SimpleNamespace(
        subject={"namespace": "tron", "canonical_value": FOCUS},
        parameters={"max_results": 10}, checkpoint=lambda: None,
    )
    batch = asyncio.run(github.GitHubCodeExecutor().execute(context))
    assert seen["q"] == f'"{FOCUS}" in:file'
    assert batch["records"] == [] and batch["coverage"] == "bounded"


def memory_sessions():
    engine = create_fk_enabled_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def tx_dict(tx_hash, event_id, asset="TRX"):
    return {"tx_hash": tx_hash, "event_id": event_id, "chain": "tron", "from_address": OTHER,
            "to_address": FOCUS, "value_native": "1", "token_symbol": asset,
            "timestamp": "2026-09-23T00:00:00+00:00", "block_number": "100", "direction": "incoming"}


def test_monitoring_baseline_native_token_dedupe_and_continuity(monkeypatch):
    from greedy_collector import monitoring
    engine, sessions = memory_sessions()
    with sessions() as db:
        watch = WatchlistWallet(chain="tron", address=FOCUS)
        db.add(watch); db.commit(); watch_id = watch.id
    baseline = tx_dict("1" * 64, "native:" + "1" * 64)
    native = tx_dict("2" * 64, "native:" + "2" * 64)
    token = tx_dict("3" * 64, "trc20:" + "3" * 64, "TEST")
    responses = [
        {"transactions": [baseline], "risk": {"score": 0, "findings": []}},
        {"transactions": [token, native, baseline], "risk": {"score": 0, "findings": []}},
        {"transactions": [token, native, baseline], "risk": {"score": 0, "findings": []}},
        {"transactions": [native, baseline], "risk": {"score": 0, "findings": []}},
    ]
    fake = SimpleNamespace(lookup_address=AsyncMock(side_effect=responses))
    monkeypatch.setattr(monitoring, "SessionLocal", sessions)
    monkeypatch.setattr(monitoring, "GreedyCollectorService", lambda: fake)
    first = asyncio.run(monitoring._monitor_chain("tron", watch_id))
    second = asyncio.run(monitoring._monitor_chain("tron", watch_id))
    third = asyncio.run(monitoring._monitor_chain("tron", watch_id))
    fourth = asyncio.run(monitoring._monitor_chain("tron", watch_id))
    with sessions() as db:
        watch = db.get(WatchlistWallet, watch_id)
        alerts = db.scalars(select(WalletAlert)).all()
        runs = db.scalars(select(MonitoringRun).order_by(MonitoringRun.started_at)).all()
        assert first["processed"] == second["processed"] == third["processed"] == fourth["processed"] == 1
        assert [run.new_transactions for run in runs[:3]] == [0, 2, 0]
        assert runs[-1].status == "continuity_loss"
        assert len(alerts) == 2 and {row.token for row in alerts} == {"TRX", "TEST"}
        assert watch.last_seen_tx == token["event_id"]
    engine.dispose()


def test_no_write_operations_or_runtime_fixture_names():
    source = open("greedy_collector/chains/tron.py", encoding="utf-8").read()
    assert all(term not in source for term in ("private_key", "broadcasttransaction", "sampleWallet", "demoNodes", "mockTransactions", "cannedSearch"))
