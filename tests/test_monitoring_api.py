"""Real monitoring API/state transitions with external lookup mocked only in tests."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from greedy_collector import monitoring
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import Base, MonitoringRun, WalletAlert, WatchlistWallet
from greedy_collector.router import router
from greedy_collector.services import GreedyCollectorService

PREFIX = "/api/greedy-collector"
BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ETH = "0x" + "1" * 40


@pytest.fixture
def env(monkeypatch):
    engine = create_fk_enabled_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    def db():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = db
    monkeypatch.setattr(monitoring, "SessionLocal", factory)
    lookup = AsyncMock()
    monkeypatch.setattr(GreedyCollectorService, "lookup_address", lookup)
    try:
        with TestClient(app) as client:
            yield client, factory, lookup
    finally:
        engine.dispose()


def watch(client, chain="bitcoin", **extra):
    response = client.post(PREFIX + "/watchlist", json={"chain": chain, "address": BTC if chain == "bitcoin" else ETH, **extra})
    assert response.status_code == 200
    return response.json()


def tx(hash_, confirmed=True):
    return {"tx_hash": hash_, "timestamp": "2026-09-11T00:00:00+00:00" if confirmed else None,
            "block_number": "123" if confirmed else "", "direction": "incoming",
            "from_address": "counterparty", "to_address": BTC, "value_native": "1", "token_symbol": "BTC"}


def result(rows, score=0):
    return {"transactions": rows, "risk": {"score": score, "findings": []}}


def test_invalid_watch_returns_422(env):
    client, _, lookup = env
    response = client.post(PREFIX + "/watchlist", json={"chain": "bitcoin", "address": "bad-address"})
    assert response.status_code == 422
    lookup.assert_not_called()


def test_watch_patch_preserves_history_and_clears_case(env):
    client, factory, _ = env
    case = client.post(PREFIX + "/cases", json={"title": "Test case"}).json()
    wallet = watch(client)
    with factory() as db:
        db.add(MonitoringRun(wallet_id=wallet["id"], status="completed")); db.commit()
    payload = {"enabled": False, "priority": "high", "label": "Reviewed wallet", "notes": "Pause checks", "case_id": case["id"]}
    updated = client.patch(PREFIX + f"/watchlist/{wallet['id']}", json=payload)
    assert updated.status_code == 200
    for key, value in payload.items(): assert updated.json()[key] == value
    assert client.patch(PREFIX + f"/watchlist/{wallet['id']}", json={"case_id": None}).json()["case_id"] is None
    assert client.get(PREFIX + f"/watchlist/{wallet['id']}/runs").json()["total"] == 1
    assert client.patch(PREFIX + f"/watchlist/{wallet['id']}", json={"enabled": True}).json()["enabled"] is True


@pytest.mark.parametrize("body", [{"priority": "invalid"}, {"enabled": None}, {"label": None}])
def test_invalid_watch_patch(env, body):
    client, _, _ = env
    wallet = watch(client)
    assert client.patch(PREFIX + f"/watchlist/{wallet['id']}", json=body).status_code == 422


def test_missing_watch_and_case(env):
    client, _, _ = env
    assert client.patch(PREFIX + "/watchlist/missing", json={"enabled": False}).status_code == 404
    assert client.post(PREFIX + "/watchlist/missing/check").status_code == 404
    assert client.get(PREFIX + "/watchlist/missing/runs").status_code == 404
    assert client.post(PREFIX + "/watchlist", json={"chain":"bitcoin", "address":BTC, "case_id":"missing"}).status_code == 404
    wallet = watch(client)
    assert client.patch(PREFIX + f"/watchlist/{wallet['id']}", json={"case_id":"missing"}).status_code == 404


def test_delete_with_history_is_conflict(env):
    client, factory, _ = env
    wallet = watch(client)
    with factory() as db:
        db.add(MonitoringRun(wallet_id=wallet["id"], status="completed")); db.commit()
    assert client.delete(PREFIX + f"/watchlist/{wallet['id']}").status_code == 409
    with factory() as db:
        assert db.get(WatchlistWallet, wallet["id"])
        assert db.scalar(select(MonitoringRun))


def test_delete_without_history(env):
    client, _, _ = env
    wallet = watch(client)
    assert client.delete(PREFIX + f"/watchlist/{wallet['id']}").json() == {"deleted": wallet["id"]}


@pytest.mark.parametrize("chain,rows,boundary", [
    ("bitcoin", [tx("pending", False), tx("confirmed")], "confirmed"),
    ("bitcoin", [tx("pending", False)], None),
    ("ethereum", [tx("confirmed")], "confirmed"),
    ("ethereum", [], None),
])
def test_manual_first_run_is_silent(env, chain, rows, boundary):
    client, factory, lookup = env
    wallet = watch(client, chain)
    lookup.return_value = result(rows)
    response = client.post(PREFIX + f"/watchlist/{wallet['id']}/check")
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "completed"
    assert response.json()["run"]["new_transactions"] == 0
    assert response.json()["wallet"]["last_seen_tx"] == boundary
    assert response.json()["wallet"]["last_checked"]
    assert client.get(PREFIX + "/alerts").json()["alerts"] == []
    assert client.get(PREFIX + "/watchlist").json()["wallets"][0]["last_monitoring_status"] == "completed"


def test_manual_only_checks_selected_enabled_watch(env):
    client, _, lookup = env
    wallet = watch(client)
    client.post(PREFIX + "/watchlist", json={"chain":"bitcoin", "address":"1BoatSLRHtKNngkdXEeobR76b53LETtpyT"})
    lookup.return_value = result([])
    assert client.post(PREFIX + f"/watchlist/{wallet['id']}/check").status_code == 200
    assert lookup.await_count == 1
    client.patch(PREFIX + f"/watchlist/{wallet['id']}", json={"enabled":False})
    assert client.post(PREFIX + f"/watchlist/{wallet['id']}/check").status_code == 409
    assert lookup.await_count == 1


def test_manual_and_scheduled_share_deduplication_and_continuity(env):
    client, factory, lookup = env
    wallet = watch(client)
    path = PREFIX + f"/watchlist/{wallet['id']}/check"
    lookup.return_value = result([tx("baseline")]); client.post(path)
    lookup.return_value = result([tx("new", False), tx("baseline")], 20); client.post(path)
    lookup.return_value = result([tx("new"), tx("baseline")], 25)
    asyncio.run(monitoring.monitor_chain("bitcoin"))
    alerts = client.get(PREFIX + "/alerts").json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["tx_hash"] == "new"
    lookup.return_value = result([tx("unrelated")])
    response = client.post(path).json()
    assert response["run"]["status"] == "continuity_loss"
    assert response["wallet"]["last_seen_tx"] == "new"
    assert len(client.get(PREFIX + "/alerts").json()["alerts"]) == 1


def test_run_history_sanitizes_errors_and_paginates(env):
    client, _, lookup = env
    wallet = watch(client)
    lookup.side_effect = RuntimeError("https://provider.invalid/secret-test-key")
    response = client.post(PREFIX + f"/watchlist/{wallet['id']}/check")
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "failed"
    assert "secret-test-key" not in response.text
    history = client.get(PREFIX + f"/watchlist/{wallet['id']}/runs?limit=1").json()
    assert history["total"] == 1
    assert len(history["runs"]) == 1
    assert "secret-test-key" not in str(history)
    assert client.get(PREFIX + f"/watchlist/{wallet['id']}/runs?offset=1").json()["runs"] == []


def test_overlapping_manual_check_returns_conflict(env):
    client, _, lookup = env
    wallet = watch(client)
    with monitoring._chain_locks["bitcoin"]:
        assert client.post(PREFIX + f"/watchlist/{wallet['id']}/check").status_code == 409
    lookup.assert_not_called()
