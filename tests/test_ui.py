"""Lightweight application route and real API response-contract checks; no live requests."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main
from greedy_collector.chains import BitcoinAdapter, EthereumAdapter
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import Base


@pytest.fixture
def ui_client():
    engine = create_fk_enabled_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def memory_db():
        with Session(engine) as session:
            yield session

    previous = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db] = memory_db
    try:
        # Startup/shutdown are patched below so no monitoring jobs run.
        with TestClient(main.app) as client:
            yield client, engine
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        engine.dispose()


@pytest.fixture(autouse=True)
def no_monitoring(monkeypatch):
    monkeypatch.setattr(main, "start_monitoring", lambda: None)
    monkeypatch.setattr(main, "stop_monitoring", lambda: None)


def test_ui_page(ui_client):
    client, _ = ui_client
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for expected in (
        'id="lookup-form"', 'placeholder="Search wallet address or transaction hash"',
        'id="wallet-address"', '>Search</button>', 'id="transaction-rows"',
        'id="risk-findings"', 'id="counterparties"',
        "Use public blockchain identifiers only. Never enter a private key or recovery phrase.",
        '/static/js/app.js', '/static/app.css',
    ):
        assert expected in response.text


@pytest.mark.parametrize("filename,media_type", [
    *[(f"js/{name}.js", "javascript") for name in
      ["api", "ui", "app", "wallet", "graph", "graph_layout", "monitoring", "alerts"]],
    ("app.css", "text/css"),
])
def test_ui_assets(ui_client, filename, media_type):
    client, _ = ui_client
    response = client.get(f"/static/{filename}")
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    assert response.text.strip()


def test_unified_search_has_no_mandatory_chain(ui_client):
    client, _ = ui_client
    assert 'id="chain"' not in client.get("/").text


def test_ui_preserves_root(ui_client):
    client, _ = ui_client
    response = client.get("/")
    assert response.status_code == 200
    assert "Greedy Collector" in response.text
    assert response.headers["content-type"].startswith("text/html")
    assert client.get("/demo").status_code == 404
    for asset in ["demo.html", "demo.js", "demo.css"]:
        assert client.get(f"/static/{asset}").status_code == 404


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json"])
def test_ui_preserves_existing_routes(ui_client, path):
    client, _ = ui_client
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("chain", ["bitcoin", "ethereum"])
def test_ui_lookup_response_contract(ui_client, monkeypatch, chain):
    """Exercise normalization, service persistence/risk, and HTTP serialization.

    These are the fields consumed by js/wallet.js; provider methods alone are mocked.
    """
    client, _ = ui_client
    if chain == "bitcoin":
        address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        counterparty = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        adapter = BitcoinAdapter()
        transactions = [adapter._normalize({
            "txid": digit * 64,
            "vin": [{"prevout": {"scriptpubkey_address": counterparty, "value": 10000001000}}],
            "vout": [{"scriptpubkey_address": address, "value": 10000000000}],
            "status": status,
        }, address, "blockstream") for digit, status in [
            ("a", {"confirmed": False}),
            ("b", {"confirmed": True, "block_height": 900000, "block_time": 1780000000}),
        ]]
        provider = "blockstream"
    else:
        address = "0x" + "1" * 40
        counterparty = "0x" + "2" * 40
        adapter = EthereumAdapter()
        row = {"hash": "0x" + "a" * 64, "from": counterparty, "to": address,
               "value": "100000000000000000000", "timeStamp": "1780000000", "blockNumber": "25000000"}
        transactions = [adapter._normalize(row, address), adapter._normalize_token({
            **row, "hash": "0x" + "b" * 64, "value": "1234567",
            "tokenSymbol": "TEST", "tokenDecimal": "6",
        }, address)]
        provider = "etherscan"
    adapter.lookup_address = AsyncMock(return_value={
        "balance_native": "1.000000000000000001", "source_api": provider,
        "transaction_count": 2,
    })
    adapter.transactions = AsyncMock(return_value=transactions)
    monkeypatch.setattr("greedy_collector.services.get_chain_adapter", lambda _: adapter)
    # Keep the fixture independent of optional external graph configuration.
    from greedy_collector.router import service
    monkeypatch.setattr(service.graph_store, "store_transactions", lambda _: None)
    response = client.post("/api/greedy-collector/lookup/address", json={"chain": chain, "address": address})
    assert response.status_code == 200
    data = response.json()
    assert data["address"]["chain"] == chain
    assert data["address"]["address"] == address
    assert data["address"]["balance_native"] == "1.000000000000000001"
    assert {"first_seen", "last_activity", "metadata_json"} <= data["address"].keys()
    assert data["provenance"]["source_api"] == provider
    assert data["provenance"]["retrieved_at"]
    assert len(data["transactions"]) == 2
    for tx in data["transactions"]:
        assert {"tx_hash", "direction", "from_address", "to_address", "value_native",
                "token_symbol", "timestamp", "block_number"} <= tx.keys()
        assert isinstance(tx["value_native"], str)
        assert tx["value_usd"] is None
        assert "raw_payload" not in tx
    assert data["counterparties"] == [{"address": counterparty, "transaction_count": 2}]
    assert data["risk"]["score"] == 22
    assert data["risk"]["level"] == "Low"
    assert data["risk"]["disclaimer"]
    assert {"rule_id", "rule_name", "severity", "confidence", "score_contribution",
            "explanation", "evidence"} <= data["risk"]["findings"][0].keys()
    if chain == "bitcoin":
        assert data["transactions"][0]["timestamp"] is None
        assert data["transactions"][0]["block_number"] == ""
        assert data["transactions"][0]["token_symbol"] == "BTC"
    else:
        assert data["transactions"][0]["token_symbol"] == "ETH"
        assert data["transactions"][1]["token_symbol"] == "TEST"
        assert data["transactions"][1]["value_native"] == "1.234567"
    # Stored GETs consume the same persisted result without further provider requests.
    path = f"/api/greedy-collector/address/{chain}/{address}"
    profile = client.get(path).json()
    assert profile["balance_native"] == data["address"]["balance_native"]
    assert profile["updated_at"]
    stored_txs = client.get(path + "/transactions").json()["transactions"]
    assert {tx["tx_hash"] for tx in stored_txs} == {tx["tx_hash"] for tx in data["transactions"]}
    stored_risk = client.get(path + "/risk").json()
    assert stored_risk["findings"] == data["risk"]["findings"]
    assert stored_risk["calculated_at"]
    adapter.lookup_address.assert_awaited_once_with(address)
    adapter.transactions.assert_awaited_once_with(address)


@pytest.mark.parametrize("chain", ["bitcoin", "ethereum"])
def test_lookup_provider_errors_do_not_expose_keys(ui_client, monkeypatch, chain):
    from greedy_collector.chains.base import ChainDataError
    from greedy_collector.router import service
    client, _ = ui_client
    monkeypatch.setattr(service, "lookup_address", AsyncMock(side_effect=ChainDataError("https://provider.invalid/v2/secret-test-key")))
    response = client.post("/api/greedy-collector/lookup/address", json={"chain": chain, "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"})
    assert response.status_code == 502
    assert "secret-test-key" not in response.text
    assert "https://" not in response.text


def test_research_unavailable_errors_are_sanitized(ui_client, monkeypatch):
    from greedy_collector.router import service
    client, _ = ui_client
    monkeypatch.setattr(service.kyc_engine, "screen", AsyncMock(return_value={
        "query": {"name": "Test subject"}, "matches": [], "checked_sources": [], "manual_sources": [],
        "unavailable_sources": [{"id":"urlscan", "reason":"https://provider.invalid?key=secret-test-key"}],
        "disclaimer": "Test fixture disclaimer",
    }))
    response = client.post("/api/greedy-collector/kyc/screen", json={"name":"Test subject"})
    assert response.status_code == 200
    assert response.json()["unavailable_sources"][0]["id"] == "urlscan"
    assert "secret-test-key" not in response.text


def test_core_api_and_empty_graph_remain_available(ui_client):
    client, _ = ui_client
    assert client.get("/api/greedy-collector/status").status_code == 200
    result = client.get("/api/greedy-collector/address/bitcoin/unknown/graph?hops=3").json()
    assert result["nodes"] == result["edges"] == []
    assert result["requested_hops"] == 3


@pytest.mark.parametrize("workspace", ["cases", "labels", "research"])
def test_out_of_scope_frontend_is_not_exposed(ui_client, workspace):
    client, _ = ui_client
    assert f'data-workspace="{workspace}"' not in client.get("/").text
    assert f'./{workspace}.js' not in client.get("/static/js/app.js").text
    assert client.get(f"/static/js/{workspace}.js").status_code == 404


@pytest.mark.parametrize("chain", ["bitcoin", "ethereum"])
@pytest.mark.parametrize("hops", [1, 2, 3])
def test_ui_graph_contract_from_real_sqlite(ui_client, monkeypatch, chain, hops):
    from datetime import datetime, timezone
    from greedy_collector.models import Transaction
    from greedy_collector.router import service
    client, engine = ui_client
    monkeypatch.setattr(service.graph_store, "query_graph", lambda *_: None)
    monkeypatch.setattr("greedy_collector.services.get_chain_adapter", lambda _: pytest.fail("Stored graph must not fetch a provider"))
    addresses = (["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "bc1qtestfixture", "bc1qanotherfixture"]
                 if chain == "bitcoin" else ["0x" + digit * 40 for digit in "1234"])
    with Session(engine) as db:
        for index in range(3):
            db.add(Transaction(chain=chain, tx_hash=str(index) * 64, from_address=addresses[index],
                               to_address=addresses[index + 1], value_native="0.000000000000000001",
                               token_symbol="BTC" if chain == "bitcoin" else "TEST",
                               timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        db.commit()
    response = client.get(f"/api/greedy-collector/address/{chain}/{addresses[0]}/graph?hops={hops}")
    assert response.status_code == 200
    graph = response.json()
    assert graph["requested_hops"] == graph["available_hops"] == hops
    assert graph["backend"] == "sqlite"
    assert graph["note"]
    assert {node["id"] for node in graph["nodes"]} == set(addresses[:hops + 1])
    assert [node["id"] for node in graph["nodes"] if node["is_focus"]] == [addresses[0]]
    assert all({"id", "label", "chain", "type", "is_focus"} <= node.keys() for node in graph["nodes"])
    assert len(graph["edges"]) == hops
    for index, edge in enumerate(graph["edges"]):
        assert edge["source"] == addresses[index]
        assert edge["target"] == addresses[index + 1]
        assert edge["tx_hash"] == str(index) * 64
        assert edge["value_native"] == "0.000000000000000001"
        assert edge["token_symbol"] == ("BTC" if chain == "bitcoin" else "TEST")
        assert edge["timestamp"].startswith("2026-01-01T00:00:00")


@pytest.mark.parametrize("chain", ["bitcoin", "ethereum"])
def test_ui_stored_missing_and_no_risk_contract(ui_client, monkeypatch, chain):
    from greedy_collector.models import Address
    client, engine = ui_client
    monkeypatch.setattr("greedy_collector.services.get_chain_adapter", lambda _: pytest.fail("Stored views must not fetch a provider"))
    address = "0x" + "1" * 40 if chain == "ethereum" else "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    path = f"/api/greedy-collector/address/{chain}/{address}"
    assert client.get(path).status_code == 404
    assert client.get(path + "/risk").status_code == 404
    assert client.get(path + "/transactions").json() == {"transactions": []}
    with Session(engine) as db:
        db.add(Address(chain=chain, address=address, balance_native="0"))
        db.commit()
    assert client.get(path).status_code == 200
    assert client.get(path + "/risk").status_code == 404


def test_monitoring_workspace_navigation(ui_client):
    client, _ = ui_client
    html = client.get("/").text
    assert 'data-workspace="monitoring"' in html
    assert 'id="monitoring-workspace"' in html
    assert 'import {initMonitoring} from "./monitoring.js"' in client.get("/static/js/app.js").text
    module = client.get("/static/js/monitoring.js").text
    assert "No wallets are being monitored." in module
    assert "No monitoring history for this wallet." in module
    assert "No alerts for this wallet." in module


def test_monitoring_ui_routes_and_consumed_fields_exist(ui_client):
    client, _ = ui_client
    schema = client.get("/openapi.json").json()
    prefix = "/api/greedy-collector"
    for route, methods in {"/watchlist": ["get", "post"], "/watchlist/{wallet_id}": ["patch"],
                           "/watchlist/{wallet_id}/check": ["post"], "/watchlist/{wallet_id}/runs": ["get"],
                           "/alerts": ["get"], "/status": ["get"]}.items():
        assert all(method in schema["paths"][prefix + route] for method in methods)
    for model in ["WatchlistCreate", "WatchlistUpdate"]:
        assert {"enabled", "priority", "label", "notes", "case_id"} <= schema["components"]["schemas"][model]["properties"].keys()
    params = {item["name"]: item for item in schema["paths"][prefix + "/watchlist/{wallet_id}/runs"]["get"]["parameters"]}
    assert params["limit"]["schema"]["maximum"] >= 25
    assert params["offset"]["schema"]["minimum"] == 0
    module = client.get("/static/js/monitoring.js").text
    assert 'request(`${watchPath(id)}/check`, {method:"POST"})' in module
    assert '/runs?limit=${PAGE_SIZE}&offset=${offset}' in module
    assert 'request("/alerts")' in module
    assert 'request("/watchlist", {method:"POST"' in module
    assert 'method:"PATCH"' in module
    assert 'method:"DELETE"' not in module


def test_monitoring_assets_and_status_keep_credentials_private(ui_client, monkeypatch):
    client, _ = ui_client
    secret = "dummy-monitoring-secret-not-for-production"
    monkeypatch.setattr(main.settings, "etherscan_api_key", secret)
    monkeypatch.setattr(main.settings, "alchemy_api_key", secret)
    for path in ["/", "/api/greedy-collector/status", "/static/app.css",
                 *[f"/static/js/{name}.js" for name in ["api", "ui", "app", "wallet", "graph", "graph_layout", "monitoring", "alerts"]]]:
        response = client.get(path)
        assert response.status_code == 200
        assert secret not in response.text


def test_global_alerts_workspace_and_api_contract(ui_client):
    client, _ = ui_client
    html = client.get("/").text
    assert 'data-workspace="alerts"' in html and 'id="alerts-workspace"' in html
    assert 'initAlerts(navigate)' in client.get("/static/js/app.js").text
    module = client.get("/static/js/alerts.js").text
    assert "No alerts have been generated." in module
    assert '"/alerts"' in module and '/alerts?status=${encodeURIComponent(filter.value)}' in module
    assert 'request(`/alerts/${encodeURIComponent(alert.id)}`, {method:"PATCH"' in module
    assert 'method:"DELETE"' not in module
    schema = client.get("/openapi.json").json()
    assert "get" in schema["paths"]["/api/greedy-collector/alerts"]
    assert "patch" in schema["paths"]["/api/greedy-collector/alerts/{alert_id}"]
    assert set(schema["components"]["schemas"]["AlertUpdate"]["properties"]) == {"status", "notes"}
    assert client.get("/api/greedy-collector/alerts").json() == {"alerts": []}


@pytest.mark.parametrize("status", ["New", "Reviewed", "Dismissed", "Escalated"])
def test_alert_review_and_filter_response_contract(ui_client, status):
    from datetime import datetime, timezone
    from greedy_collector.models import WalletAlert
    client, engine = ui_client
    with Session(engine) as db:
        risk = WalletAlert(wallet="0x"+"1"*40, chain="ethereum", trigger_type="High velocity",
                           severity="High", explanation="Test-only risk finding", dedupe_key="risk-test",
                           timestamp=datetime(2026,1,1,tzinfo=timezone.utc))
        tx = WalletAlert(wallet="0x"+"2"*40, chain="ethereum", tx_hash="0x"+"a"*64,
                         counterparty="0x"+"3"*40, amount="0.000000000000000001", token="ETH",
                         trigger_type="New incoming transaction", severity="Medium", explanation="Test-only transaction",
                         dedupe_key="tx-test", timestamp=datetime(2026,1,2,tzinfo=timezone.utc))
        db.add_all([risk,tx]); db.commit(); risk_id=risk.id; tx_id=tx.id
    data = client.get("/api/greedy-collector/alerts").json()["alerts"]
    assert [row["id"] for row in data] == [tx_id, risk_id]
    assert data[1]["tx_hash"] is data[1]["counterparty"] is data[1]["amount"] is None
    assert data[0]["amount"] == "0.000000000000000001"
    response = client.patch(f"/api/greedy-collector/alerts/{risk_id}", json={"status":status,"notes":"Persisted analyst test note"})
    assert response.status_code == 200
    assert response.json()["notes"] == "Persisted analyst test note"
    rows = client.get("/api/greedy-collector/alerts", params={"status":status}).json()["alerts"]
    assert all(row["status"] == status for row in rows)
    assert any(row["id"] == risk_id for row in rows)
    assert client.patch(f"/api/greedy-collector/alerts/{risk_id}", json={"notes":""}).json()["notes"] == ""


def test_alert_update_missing_and_invalid_status(ui_client):
    client, _ = ui_client
    assert client.patch("/api/greedy-collector/alerts/missing", json={"status":"Reviewed"}).status_code == 404
    assert client.patch("/api/greedy-collector/alerts/missing", json={"status":"unsupported"}).status_code == 422
