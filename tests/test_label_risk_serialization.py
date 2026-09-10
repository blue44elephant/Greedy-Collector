"""Regression coverage for label evidence through lookup, SQLite, and HTTP."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from greedy_collector.chains import BitcoinAdapter, EthereumAdapter
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import Base, Label, RiskResult
from greedy_collector.router import router, service
from greedy_collector.schemas import NormalizedTransaction


@pytest.fixture
def lookup_client():
    engine = create_fk_enabled_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def memory_db():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = memory_db
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("chain,label_type,rule_id,score", [
    ("ethereum", "Sanctioned", "direct_sanctioned", 40),
    ("bitcoin", "Sanctioned", "direct_sanctioned", 40),
    ("bitcoin", "Mixer", "direct_mixer", 25),
    ("bitcoin", "Scam", "direct_scam", 30),
    ("ethereum", "Bridge", "cross_chain_bridge", 5),
    ("ethereum", "Exchange", "exchange_pattern", 5),
])
def test_lookup_persists_label_evidence_as_json(
    lookup_client, monkeypatch, chain, label_type, rule_id, score
):
    client, engine = lookup_client
    if chain == "bitcoin":
        address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        counterparty = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
        adapter = BitcoinAdapter()
    else:
        address = "0x" + "1" * 40
        counterparty = "0x" + "2" * 40
        adapter = EthereumAdapter()

    prefix = "/api/greedy-collector"
    created = client.post(f"{prefix}/labels/manual", json={
        "chain": chain, "address": counterparty, "label": "Regression fixture",
        "type": label_type, "source": "Automated test fixture", "confidence": 0.8,
    })
    assert created.status_code == 200
    label_id = created.json()["id"]
    with Session(engine) as session:
        label = session.get(Label, label_id)
        label.last_updated = datetime(2026, 9, 11, 12, 30, 45, 123456, tzinfo=timezone.utc)
        session.commit()
        session.refresh(label)
        assert isinstance(label.last_updated, datetime)
        # SQLite reloads this as a naive datetime; match the existing API convention.
        expected_timestamp = label.last_updated.isoformat()

    transaction = NormalizedTransaction(
        chain=chain, tx_hash=("0x" if chain == "ethereum" else "") + "a" * 64,
        from_address=counterparty, to_address=address, value_native="1",
        token_symbol="BTC" if chain == "bitcoin" else "ETH", direction="incoming",
        timestamp=datetime(2026, 9, 11, tzinfo=timezone.utc), block_number="123",
        source_api="blockstream" if chain == "bitcoin" else "etherscan",
    )
    adapter.lookup_address = AsyncMock(return_value={
        "balance_native": "1", "source_api": transaction.source_api,
    })
    adapter.transactions = AsyncMock(return_value=[transaction])
    monkeypatch.setattr("greedy_collector.services.get_chain_adapter", lambda _: adapter)
    monkeypatch.setattr(service.graph_store, "store_transactions", lambda _: None)

    # Real router -> service -> risk engine -> SQLite commit -> FastAPI response.
    response = client.post(f"{prefix}/lookup/address", json={"chain": chain, "address": address})
    assert response.status_code == 200
    data = response.json()
    assert data["address"]["balance_native"] == "1"
    assert data["risk"]["score"] == score
    assert data["address"]["risk_score"] == score
    assert len(data["risk"]["findings"]) == 1
    finding = data["risk"]["findings"][0]
    assert finding["rule_id"] == rule_id
    assert finding["score_contribution"] == score
    assert finding["evidence"]["tx_hash"] == transaction.tx_hash
    assert finding["evidence"]["label"] == data["labels"][0]
    assert finding["evidence"]["label"]["id"] == label_id
    assert finding["evidence"]["label"]["last_updated"] == expected_timestamp
    assert finding["evidence"]["label"]["confidence"] == 0.8

    with Session(engine) as session:
        stored = session.scalar(select(RiskResult))
        assert stored.findings == data["risk"]["findings"]
        assert isinstance(session.get(Label, label_id).last_updated, datetime)
    stored_response = client.get(f"{prefix}/address/{chain}/{address}/risk")
    assert stored_response.status_code == 200
    assert stored_response.json()["findings"] == data["risk"]["findings"]
    adapter.lookup_address.assert_awaited_once_with(address)
    adapter.transactions.assert_awaited_once_with(address)
