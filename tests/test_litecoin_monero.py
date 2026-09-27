"""MC-5 Litecoin transparent-chain and Monero observation-only contracts."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from greedy_collector.attribution.domain import ClaimInput
from greedy_collector.chains import Capability, get_chain, get_chain_adapter, list_chains
from greedy_collector.chains.base import ChainDataError
from greedy_collector.chains.base58 import base58_encode
from greedy_collector.chains.litecoin import LitecoinAdapter, validate_litecoin_address
from greedy_collector.chains.monero import (
    MoneroAdapter,
    _encode_block,
    keccak_256,
    validate_monero_address,
)
from greedy_collector.discovery.registry import REGISTRY as DISCOVERY
from greedy_collector.discovery.domain import canonical_subject
from greedy_collector.discovery.manual_source import ManualSourceInput
from greedy_collector.resolver import resolve_identifier
from greedy_collector.reporting import case_html, case_json, case_markdown, case_pdf
from greedy_collector.schemas import CaseEntityCreate, ManualLabelCreate, NormalizedTransaction
from tests.test_ui import no_monitoring, ui_client


@pytest.fixture(autouse=True)
def no_provider_traffic(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("MC-5 tests must not make live provider requests")
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", fail)
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", fail)


LTC_P2PKH = base58_encode(bytes([48]) + bytes(range(20)) + hashlib.sha256(hashlib.sha256(bytes([48]) + bytes(range(20))).digest()).digest()[:4])
LTC_P2SH_AMBIGUOUS = base58_encode(bytes([5]) + bytes(range(20)) + hashlib.sha256(hashlib.sha256(bytes([5]) + bytes(range(20))).digest()).digest()[:4])
LTC_P2SH_ALT = base58_encode(bytes([50]) + bytes(range(20)) + hashlib.sha256(hashlib.sha256(bytes([50]) + bytes(range(20))).digest()).digest()[:4])
LTC_BECH32 = "ltc1qqqqsyqcyq5rqwzqfpg9scrgwpugpzysn3s44dy"
MONERO_POINT = b"\x58" + b"\x66" * 31


def monero_address(prefix: int, extra: bytes = b"") -> str:
    payload = bytes([prefix]) + MONERO_POINT + MONERO_POINT + extra
    payload += keccak_256(payload)[:4]
    return "".join(_encode_block(payload[index:index + 8]) for index in range(0, len(payload), 8))


def monero_address_with_keys(prefix: int, spend: bytes, view: bytes) -> str:
    payload = bytes([prefix]) + spend + view
    payload += keccak_256(payload)[:4]
    return "".join(_encode_block(payload[index:index + 8]) for index in range(0, len(payload), 8))


MONERO_STANDARD = monero_address(18)
MONERO_SUBADDRESS = monero_address(42)
MONERO_INTEGRATED = monero_address(19, bytes.fromhex("0102030405060708"))


def test_litecoin_address_forms_and_resolver_precedence():
    for address in (LTC_P2PKH, LTC_P2SH_ALT, LTC_BECH32):
        assert validate_litecoin_address(address)
        resolved = resolve_identifier(address)
        assert resolved["kind"] == "address" and resolved["chain"] == "litecoin"
    assert resolve_identifier(LTC_BECH32.upper())["kind"] == "ambiguous"
    assert resolve_identifier(LTC_BECH32.upper(), chain_hint="litecoin")["chain"] == "litecoin"
    with pytest.raises(ValueError, match="checksum"):
        validate_litecoin_address(LTC_P2PKH[:-1] + ("1" if LTC_P2PKH[-1] != "1" else "2"))
    with pytest.raises(ValueError, match="MWEB"):
        validate_litecoin_address("ltcmweb1" + "q" * 60)
    ambiguous = resolve_identifier(LTC_P2SH_AMBIGUOUS)
    assert ambiguous["kind"] == "ambiguous"
    assert {item["chain"] for item in ambiguous["possibilities"]} == {"bitcoin", "litecoin"}
    assert resolve_identifier("a" * 64)["chain"] == "bitcoin"
    assert resolve_identifier("a" * 64, chain_hint="litecoin")["chain"] == "litecoin"


@pytest.mark.parametrize(
    "address,kind",
    [(MONERO_STANDARD, "standard"), (MONERO_SUBADDRESS, "subaddress"), (MONERO_INTEGRATED, "integrated")],
)
def test_monero_mainnet_address_forms_validate_locally(address, kind):
    assert validate_monero_address("  " + address + " ") == (address, kind)
    assert resolve_identifier(address, chain_hint="monero")["chain"] == "monero"
    assert canonical_subject("blockchain_address", "monero", address)["canonical_value"] == address


def test_monero_rejects_bad_checksum_and_non_mainnet_prefix():
    with pytest.raises(ValueError, match="checksum"):
        validate_monero_address(MONERO_STANDARD[:-1] + ("1" if MONERO_STANDARD[-1] != "1" else "2"))
    with pytest.raises(ValueError, match="prefix"):
        validate_monero_address(monero_address(53))
    with pytest.raises(ValueError):
        validate_monero_address(MONERO_STANDARD[:-1])
    noncanonical_y = b"\xed" + b"\xff" * 30 + b"\x7f"
    with pytest.raises(ValueError, match="public key"):
        validate_monero_address(monero_address_with_keys(18, noncanonical_y, MONERO_POINT))


def test_registry_capabilities_keep_monero_observation_only_and_metadata_secret_free(monkeypatch):
    monkeypatch.setenv("LITECOIN_API_URL", "https://private.invalid/path")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "do-not-expose-this")
    litecoin = get_chain("litecoin")
    monero = get_chain("monero")
    assert {Capability.BALANCE, Capability.TRANSACTION_HISTORY, Capability.TRANSACTION_LOOKUP,
            Capability.COUNTERPARTIES, Capability.GRAPH, Capability.MONITORING, Capability.RISK} <= litecoin.capabilities
    assert Capability.TOKEN_TRANSFERS not in litecoin.capabilities
    assert monero.capabilities == frozenset({Capability.ADDRESS_VALIDATION, Capability.DISCOVERY,
        Capability.LABELS, Capability.CASES, Capability.ATTRIBUTION})
    metadata = json.dumps([item.public_metadata() for item in list_chains()])
    assert "do-not-expose-this" not in metadata and "private.invalid" not in metadata
    with pytest.raises(ValueError, match="unsupported_chain_capability"):
        get_chain_adapter("monero", Capability.BALANCE)


def test_litecoin_provider_normalization_uses_bounded_esplora_pages(monkeypatch):
    adapter = LitecoinAdapter()
    calls = []

    def tx(txid, confirmed):
        return {
            "txid": txid,
            "status": {"confirmed": confirmed, **({"block_height": 900, "block_time": 1_750_000_000} if confirmed else {})},
            "vin": [{"prevout": {"scriptpubkey_address": LTC_P2PKH, "value": 250_000_000}}],
            "vout": [{"scriptpubkey_address": LTC_P2SH_ALT, "value": 200_000_000}],
            "fee": 1000,
        }

    mempool = tx("f" * 64, False)
    pages = [[tx(f"{page * 25 + index + 1:064x}", True) for index in range(25)] for page in range(3)]

    async def response(path, *, params=None):
        calls.append((path, params))
        if path.endswith("/txs"):
            return [mempool, *pages[len([item for item in calls if item[0].endswith('/txs')]) - 1]]
        if "/address/" in path and not path.endswith("/txs"):
            return {"chain_stats": {"funded_txo_sum": 350_000_000, "spent_txo_sum": 100_000_000, "tx_count": 30},
                    "mempool_stats": {"funded_txo_sum": 20_000_000, "spent_txo_sum": 5_000_000, "tx_count": 1}}
        return tx("e" * 64, True)

    monkeypatch.setattr(adapter, "_request_json", response)
    profile = asyncio.run(adapter.lookup_address(LTC_P2PKH))
    assert profile["balance_native"] == "2.65" and profile["transaction_count"] == 31
    rows = asyncio.run(adapter.transactions(LTC_P2PKH))
    assert len(rows) == 76  # One mempool plus the configured 75 confirmed records.
    assert rows[0].timestamp is None and rows[0].block_number == ""
    assert rows[1].from_address == LTC_P2PKH and rows[1].to_address == LTC_P2SH_ALT
    assert rows[1].direction == "outgoing" and rows[1].fee == "0.00001"
    looked_up = asyncio.run(adapter.lookup_transaction("e" * 64))
    assert looked_up.tx_hash == "e" * 64 and looked_up.source_api == "litecoinspace"
    pages_called = [params for path, params in calls if path.endswith("/txs")]
    assert len(pages_called) == 3 and pages_called[0] is None
    assert pages_called[1] == {"after_txid": pages[0][-1]["txid"]}


def test_litecoin_complex_utxo_rows_do_not_infer_one_counterparty_pair():
    adapter = LitecoinAdapter()
    row = {
        "txid": "a" * 64,
        "status": {"confirmed": True, "block_height": 1, "block_time": 1_750_000_000},
        "vin": [{"prevout": {"scriptpubkey_address": LTC_P2PKH, "value": 100}},
                {"prevout": {"scriptpubkey_address": LTC_P2SH_ALT, "value": 100}}],
        "vout": [{"scriptpubkey_address": LTC_P2PKH, "value": 150},
                 {"scriptpubkey_address": LTC_P2SH_ALT, "value": 40}],
        "fee": 10,
    }
    normalized = adapter._normalize(row, LTC_P2PKH, "litecoinspace")
    assert normalized.from_address == normalized.to_address == ""
    assert normalized.raw_payload["_public"]["participant_pair_available"] is False


def test_litecoin_lookup_runs_through_service_with_provider_methods_mocked(ui_client, no_monitoring, monkeypatch):
    address = LTC_P2PKH
    profile = {"chain": "litecoin", "address": address, "balance_native": "2.65",
               "transaction_count": 31, "source_api": "litecoinspace"}
    tx = NormalizedTransaction(tx_hash="a" * 64, chain="litecoin", from_address=LTC_P2SH_ALT,
        to_address=address, value_native="1.25", token_symbol="LTC",
        timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc), block_number="900", fee="0.00001",
        direction="incoming", source_api="litecoinspace")
    monkeypatch.setattr(LitecoinAdapter, "lookup_address", AsyncMock(return_value=profile))
    monkeypatch.setattr(LitecoinAdapter, "transactions", AsyncMock(return_value=[tx]))
    client, _ = ui_client
    response = client.post("/api/greedy-collector/lookup/address", json={"chain": "litecoin", "address": address})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["address"]["chain"] == "litecoin" and data["address"]["balance_native"] == "2.65"
    assert data["transactions"][0]["source_api"] == "litecoinspace"
    assert data["risk"]["findings"] is not None and data["provenance"]["source_api"] == "litecoinspace"


def test_litecoin_transaction_lookup_uses_existing_api(ui_client, no_monitoring, monkeypatch):
    tx = NormalizedTransaction(tx_hash="e" * 64, chain="litecoin", from_address=LTC_P2PKH,
        to_address=LTC_P2SH_ALT, value_native="1", token_symbol="LTC", fee="0.00001",
        timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc), block_number="900",
        direction="unknown", source_api="litecoinspace")
    lookup = AsyncMock(return_value=tx)
    monkeypatch.setattr(LitecoinAdapter, "lookup_transaction", lookup)
    response = ui_client[0].post("/api/greedy-collector/lookup/tx", json={"chain":"litecoin", "tx_hash":"e" * 64})
    assert response.status_code == 200, response.text
    assert response.json()["chain"] == "litecoin" and response.json()["token_symbol"] == "LTC"
    lookup.assert_awaited_once_with("e" * 64)


def test_monero_capability_boundaries_labels_cases_discovery_and_reports(ui_client, no_monitoring):
    client, _ = ui_client
    label = ManualLabelCreate(chain="monero", address=MONERO_STANDARD, label="Test-only fixture",
                              type="Unknown", source="Automated test")
    assert label.address == MONERO_STANDARD
    assert CaseEntityCreate(entity_type="wallet", entity_ref=MONERO_STANDARD,
                            metadata={"chain": "monero", "address": MONERO_STANDARD})
    with pytest.raises(ValidationError):
        CaseEntityCreate(entity_type="transaction", entity_ref="a" * 64, metadata={"chain": "monero"})
    with pytest.raises(ValidationError):
        CaseEntityCreate(entity_type="graph_snapshot", entity_ref="monero-graph", metadata={"chain": "monero"})
    assert "monero" in DISCOVERY.transforms["wallet.manual_source_observation"].chains
    assert "monero" in DISCOVERY.transforms["wallet.public_code_mentions"].chains
    assert "monero" not in DISCOVERY.transforms["wallet.ens_primary_name"].chains
    assert "monero" not in DISCOVERY.transforms["wallet.graphsense_public_tags"].chains
    assert {"monero", "litecoin"} <= set(DISCOVERY.transforms["wallet.local_labels"].chains)
    assert {"monero", "litecoin"} <= set(DISCOVERY.transforms["wallet.manual_source_observation"].chains)
    assert {"monero", "litecoin"} <= set(DISCOVERY.transforms["wallet.public_code_mentions"].chains)
    assert ClaimInput(entity_id="test-entity", chain="monero", subject_ref=MONERO_STANDARD,
                      relationship="operated_by", scope_note="Test-only analyst scope").subject_ref == MONERO_STANDARD
    capture = ManualSourceInput(subject={"chain":"monero", "address":MONERO_STANDARD},
        source_type="webpage", observed_at="2026-09-27T00:00:00Z", context="Public page mentions an address.",
        analyst_note="Record the test fixture only.", source_reference="fixture:monero-address")
    assert capture.subject.chain == "monero"

    resolved = client.post("/api/greedy-collector/resolve", json={"input": MONERO_STANDARD})
    assert resolved.status_code == 200 and resolved.json()["chain"] == "monero"
    for path, body in [
        ("/api/greedy-collector/lookup/address", {"chain": "monero", "address": MONERO_STANDARD}),
        (f"/api/greedy-collector/address/monero/{MONERO_STANDARD}/transactions", None),
        (f"/api/greedy-collector/address/monero/{MONERO_STANDARD}/graph", None),
        ("/api/greedy-collector/watchlist", {"chain": "monero", "address": MONERO_STANDARD}),
    ]:
        result = client.post(path, json=body) if body is not None else client.get(path)
        assert result.status_code == 422, (path, result.text)

    entities = [{"entity_type": "wallet", "entity_ref": MONERO_STANDARD,
                 "metadata_json": {"chain": "monero", "address": MONERO_STANDARD}}]
    case = {"title": "Observation only", "status": "Open", "description": ""}
    limitation = "Public address-level transaction reconstruction unavailable. This limitation does not indicate inactivity."
    assert limitation in case_markdown(case, entities, [], [])
    assert limitation in case_html(case, entities, [], [])
    assert limitation in case_json(case, entities, [], [])
    assert case_pdf(case, entities, [], []).startswith(b"%PDF-")
