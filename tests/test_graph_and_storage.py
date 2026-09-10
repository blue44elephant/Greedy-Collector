from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, Label, Transaction
from greedy_collector.graph import GraphStore
from greedy_collector.services import GreedyCollectorService


def test_local_graph_expands_three_hops():
    engine = create_fk_enabled_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for index, (source, target) in enumerate(
            [("a", "b"), ("b", "c"), ("c", "d")]
        ):
            db.add(
                Transaction(
                    tx_hash=f"tx{index}",
                    chain="bitcoin",
                    from_address=source,
                    to_address=target,
                    value_native="1",
                    token_symbol="BTC",
                    timestamp=datetime.now(timezone.utc),
                    source_api="fixture",
                )
            )
        db.commit()
        graph = GreedyCollectorService().address_graph(db, "bitcoin", "a", 3)
    assert graph["available_hops"] == 3
    assert {node["id"] for node in graph["nodes"]} == {"a", "b", "c", "d"}
    assert len(graph["edges"]) == 3


def test_local_exposure_path_finds_terminal_label():
    engine = create_fk_enabled_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Transaction(
                    tx_hash="tx1",
                    chain="ethereum",
                    from_address="focus",
                    to_address="middle",
                    value_native="1",
                    token_symbol="ETH",
                    source_api="fixture",
                ),
                Transaction(
                    tx_hash="tx2",
                    chain="ethereum",
                    from_address="middle",
                    to_address="terminal",
                    value_native="1",
                    token_symbol="ETH",
                    source_api="fixture",
                ),
                Label(
                    chain="ethereum",
                    address="terminal",
                    label="Fixture mixer",
                    type="Mixer",
                    source="Fixture",
                    confidence=0.9,
                ),
            ]
        )
        db.commit()
        paths = GreedyCollectorService()._exposure_paths(db, "ethereum", "focus", 3)
    assert paths[0]["hops"] == 2
    assert paths[0]["terminal_type"] == "Mixer"


def test_neo4j_request_without_url_falls_back_to_sqlite():
    settings = SimpleNamespace(
        graph_backend="neo4j",
        neo4j_url="",
        neo4j_user="neo4j",
        neo4j_password="",
        request_timeout=1,
    )
    graph = GraphStore(settings)
    assert graph.status()["active"] == "sqlite"


def test_neo4j_query_payload_is_normalized_without_driver(monkeypatch):
    settings = SimpleNamespace(
        graph_backend="neo4j",
        neo4j_url="http://neo4j.example:7474",
        neo4j_user="neo4j",
        neo4j_password="secret",
        request_timeout=1,
    )
    graph = GraphStore(settings)
    results = [
        {
            "columns": ["id", "label", "type", "chain"],
            "data": [{"row": ["focus", "focus", "Wallet", "bitcoin"]}],
        },
        {
            "columns": [
                "id",
                "source",
                "target",
                "tx_hash",
                "value_native",
                "token_symbol",
                "timestamp",
            ],
            "data": [],
        },
    ]
    monkeypatch.setattr(graph, "_execute", lambda statements: results)
    payload = graph.query_graph("bitcoin", "focus", 3)
    assert payload["backend"] == "neo4j"
    assert payload["nodes"][0]["is_focus"] is True
