"""MC-3A regression coverage for persisted chain transaction events."""
from io import StringIO
from pathlib import Path
import json

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from greedy_collector.chains.ethereum import EthereumAdapter
from greedy_collector.chains.tron import TronAdapter
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.graph import GraphStore
from greedy_collector.models import Base, Case, CaseEntity, Transaction
from greedy_collector.schemas import NormalizedTransaction
from greedy_collector.transaction_identity import (
    build_event_key, event_identity, normalize_event_index, persist_normalized_event,
)

ROOT = Path(__file__).resolve().parents[1]
ADDR = "0x" + "2" * 40
TO = "0x" + "3" * 40
CONTRACT = "0x" + "4" * 40
HASH = "0x" + "1" * 64


@pytest.fixture
def db():
    engine = create_fk_enabled_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _config(url, monkeypatch):
    monkeypatch.setenv("GREEDY_COLLECTOR_DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"), stdout=StringIO())
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def _migration_db(tmp_path, monkeypatch, revision="20260923_01"):
    url = "sqlite:///" + (tmp_path / "event-identity.db").as_posix()
    cfg = _config(url, monkeypatch)
    command.upgrade(cfg, revision)
    return cfg, create_fk_enabled_engine(url)


def _insert_legacy(connection, *, row_id, chain, tx_hash, sender, recipient, value, symbol, source, payload):
    connection.execute(text("""
        INSERT INTO transactions (id, tx_hash, chain, from_address, to_address, value_native,
            value_usd, token_symbol, timestamp, block_number, fee, direction, source_api, raw_payload)
        VALUES (:id, :tx_hash, :chain, :sender, :recipient, :value, NULL, :symbol, NULL, '', '0', 'unknown', :source, :payload)
    """), {"id": row_id, "tx_hash": tx_hash, "chain": chain, "sender": sender,
           "recipient": recipient, "value": value, "symbol": symbol, "source": source,
           "payload": json.dumps(payload)})


def _triggers(engine):
    with engine.connect() as connection:
        return dict(connection.execute(text(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        )).all())


def _token_row(log_index, *, contract=CONTRACT, value="1000000", symbol="SAME"):
    return {
        "hash": HASH, "from": ADDR, "to": TO, "value": value,
        "tokenSymbol": symbol, "tokenDecimal": "6", "contractAddress": contract,
        "logIndex": log_index, "timeStamp": "1700000000", "blockNumber": "19000000",
    }


def test_identical_token_transfers_at_different_log_indexes_can_persist(db):
    adapter = EthereumAdapter()
    first = adapter._normalize_token(_token_row("0x1"), ADDR)
    second = adapter._normalize_token(_token_row("0x2"), ADDR)
    one, inserted_one = persist_normalized_event(db, first)
    two, inserted_two = persist_normalized_event(db, second)
    again, inserted_again = persist_normalized_event(db, first.model_copy(deep=True))
    db.commit()
    assert (inserted_one, inserted_two, inserted_again) == (True, True, False)
    assert one.id == again.id and one.id != two.id
    assert len(db.scalars(select(Transaction).where(Transaction.tx_hash == HASH)).all()) == 2
    assert {row.event_index for row in db.scalars(select(Transaction)).all()} == {"1", "2"}
    graph = GraphStore.response_graph(ADDR, [first, second], [])
    assert len(graph["edges"]) == 2 and len({edge["id"] for edge in graph["edges"]}) == 2
    assert {edge["event_key"] for edge in graph["edges"]} == {"evm-log:1", "evm-log:2"}


def test_same_tuple_with_different_contracts_has_distinct_event_identity(db):
    first = NormalizedTransaction(tx_hash=HASH, chain="ethereum", from_address=ADDR, to_address=TO,
        value_native="1", token_symbol="SAME", source_api="etherscan_token", asset_contract=CONTRACT)
    second_contract = "0x" + "5" * 40
    second = first.model_copy(update={"asset_contract": second_contract})
    assert build_event_key(first) != build_event_key(second)
    persist_normalized_event(db, first)
    persist_normalized_event(db, second)
    db.commit()
    rows = db.scalars(select(Transaction)).all()
    assert len(rows) == 2 and {row.asset_contract for row in rows} == {CONTRACT, second_contract}


def test_cross_chain_event_keys_are_scoped_and_native_rows_use_tx(db):
    eth = NormalizedTransaction(tx_hash=HASH, chain="ethereum", from_address=ADDR,
        to_address=TO, value_native="1", token_symbol="ETH", source_api="etherscan")
    eth_again = eth.model_copy(deep=True)
    base = eth.model_copy(update={"chain": "base"})
    assert build_event_key(eth) == "tx"
    assert event_identity(eth) == HASH
    persist_normalized_event(db, eth)
    _, repeated = persist_normalized_event(db, eth_again)
    persist_normalized_event(db, base)
    db.commit()
    assert not repeated and len(db.scalars(select(Transaction)).all()) == 2


def test_event_index_validation_and_database_not_null_unique_default(db):
    assert normalize_event_index("0x10") == "16"
    assert normalize_event_index("016") == "16"
    for malformed in (True, -1, "0xz", "9" * 30, 2**64):
        with pytest.raises(ValueError):
            normalize_event_index(malformed)
    row = Transaction(tx_hash=HASH, chain="ethereum", from_address=ADDR, to_address=TO,
        value_native="1", token_symbol="ETH", source_api="test")
    db.add(row); db.flush()
    assert row.event_key == "tx"
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO transactions (id,tx_hash,chain,from_address,to_address,value_native,token_symbol,event_key) VALUES ('null-event',:hash,'ethereum',:from,:to,'1','ETH',NULL)"),
                   {"hash": HASH, "from": ADDR, "to": TO})
    db.rollback()


def test_bitcoin_keeps_wallet_relative_tuple_deduplication(db):
    first = NormalizedTransaction(tx_hash="b" * 64, chain="bitcoin", from_address="A",
        to_address="B", value_native="1", token_symbol="BTC", source_api="blockstream")
    different_view = first.model_copy(update={"from_address": "C"})
    a, inserted = persist_normalized_event(db, first)
    b, inserted_b = persist_normalized_event(db, different_view)
    again, duplicate = persist_normalized_event(db, first.model_copy(deep=True))
    db.commit()
    assert inserted and inserted_b and not duplicate
    assert a.id == again.id and a.id != b.id
    assert build_event_key(first).startswith("activity:")
    assert event_identity(first) == first.tx_hash
    assert len(db.scalars(select(Transaction)).all()) == 2


def test_tron_provider_identity_survives_event_key_adaptation(db):
    from tests.test_tron import FOCUS, OTHER, TOKEN, TX, trc20_row, adapter
    tron = adapter()
    a = tron._normalize_trc20({**trc20_row(), "event_index": 2}, FOCUS)
    b = tron._normalize_trc20({**trc20_row(), "event_index": 3}, FOCUS)
    assert a.raw_payload["_event_id"] != b.raw_payload["_event_id"]
    assert event_identity(a) == a.raw_payload["_event_id"]
    persist_normalized_event(db, a); persist_normalized_event(db, b)
    persist_normalized_event(db, a.model_copy(deep=True)); db.commit()
    rows = db.scalars(select(Transaction).where(Transaction.chain == "tron")).all()
    assert len(rows) == 2 and {row.asset_contract for row in rows} == {TOKEN}
    graph = GraphStore.response_graph(FOCUS, [a, b], [])
    assert len(graph["edges"]) == 2 and len({edge["id"] for edge in graph["edges"]}) == 2


def test_migration_preserves_legacy_rows_case_references_and_sqlite_structure(tmp_path, monkeypatch):
    cfg, engine = _migration_db(tmp_path, monkeypatch)
    ids = {
        "btc": ("btc-id", "b" * 64), "eth-native": ("eth-native-id", "0x" + "1" * 64),
        "eth-token": ("eth-token-id", "0x" + "2" * 64), "tron-native": ("tron-native-id", "3" * 64),
        "tron-token": ("tron-token-id", "4" * 64), "legacy-token": ("legacy-token-id", "0x" + "5" * 64),
    }
    try:
        with engine.begin() as connection:
            _insert_legacy(connection, row_id=ids["btc"][0], chain="bitcoin", tx_hash=ids["btc"][1], sender="from-btc", recipient="to-btc", value="1", symbol="BTC", source="blockstream", payload={})
            _insert_legacy(connection, row_id=ids["eth-native"][0], chain="ethereum", tx_hash=ids["eth-native"][1], sender=ADDR, recipient=TO, value="1", symbol="ETH", source="etherscan", payload={})
            _insert_legacy(connection, row_id=ids["eth-token"][0], chain="ethereum", tx_hash=ids["eth-token"][1], sender=ADDR, recipient=TO, value="1.25", symbol="SAME", source="etherscan_token", payload={"hash": ids["eth-token"][1], "from": ADDR, "to": TO, "value": "1250000", "tokenSymbol": "SAME", "contractAddress": CONTRACT, "logIndex": "0x2"})
            _insert_legacy(connection, row_id=ids["tron-native"][0], chain="tron", tx_hash=ids["tron-native"][1], sender="T-source", recipient="T-target", value="1", symbol="TRX", source="trongrid", payload={"_event_id": "native:" + "a" * 64})
            _insert_legacy(connection, row_id=ids["tron-token"][0], chain="tron", tx_hash=ids["tron-token"][1], sender="T-source", recipient="T-target", value="1.25", symbol="SAME", source="trongrid_trc20", payload={"_event_id": "trc20:" + "b" * 64, "_public": {"token_contract": "T-contract"}, "provider": {"event_index": "7"}})
            _insert_legacy(connection, row_id=ids["legacy-token"][0], chain="ethereum", tx_hash=ids["legacy-token"][1], sender=ADDR, recipient=TO, value="1.25", symbol="SAME", source="etherscan_token", payload={"hash": ids["legacy-token"][1], "from": ADDR, "to": TO, "value": "1250000", "tokenSymbol": "SAME", "contractAddress": CONTRACT})
        with Session(engine) as db:
            case = Case(id="case-event", title="Event migration", description="")
            db.add(case); db.flush()
            db.add(CaseEntity(case_id=case.id, entity_type="transaction", entity_ref=ids["eth-token"][1], metadata_json={"chain": "ethereum"}))
            db.commit()
        old_triggers = _triggers(engine)
        command.upgrade(cfg, "20260923_02")
        with Session(engine) as db:
            rows = {row.id: row for row in db.scalars(select(Transaction)).all()}
            assert set(rows) == {item[0] for item in ids.values()}
            assert rows[ids["btc"][0]].event_key.startswith("activity:")
            assert rows[ids["eth-native"][0]].event_key == "tx"
            assert rows[ids["eth-token"][0]].event_key == "evm-log:2"
            assert rows[ids["eth-token"][0]].event_index == "2" and rows[ids["eth-token"][0]].asset_contract == CONTRACT
            assert rows[ids["tron-native"][0]].event_key == "provider:native:" + "a" * 64
            assert rows[ids["tron-token"][0]].event_key == "provider:trc20:" + "b" * 64
            assert rows[ids["tron-token"][0]].event_index == "7" and rows[ids["tron-token"][0]].asset_contract == "T-contract"
            assert rows[ids["legacy-token"][0]].event_key.startswith("legacy:")
            assert db.scalar(select(CaseEntity).where(CaseEntity.entity_ref == ids["eth-token"][1])).case_id == "case-event"
            assert db.scalar(select(Transaction).where(Transaction.tx_hash == ids["eth-token"][1])).id == ids["eth-token"][0]
            btc = NormalizedTransaction(tx_hash=ids["btc"][1], chain="bitcoin", from_address="from-btc",
                to_address="to-btc", value_native="1", token_symbol="BTC", source_api="blockstream")
            reused, inserted = persist_normalized_event(db, btc)
            assert reused.id == ids["btc"][0] and not inserted
            native = NormalizedTransaction(tx_hash=ids["eth-native"][1], chain="ethereum", from_address=ADDR,
                to_address=TO, value_native="1", token_symbol="ETH", source_api="etherscan")
            reused, inserted = persist_normalized_event(db, native)
            assert reused.id == ids["eth-native"][0] and not inserted
            tron_native = NormalizedTransaction(tx_hash=ids["tron-native"][1], chain="tron",
                from_address="T-source", to_address="T-target", value_native="1", token_symbol="TRX",
                source_api="trongrid", raw_payload={"_event_id": "native:" + "a" * 64})
            reused, inserted = persist_normalized_event(db, tron_native)
            assert reused.id == ids["tron-native"][0] and not inserted
            tron_token = NormalizedTransaction(tx_hash=ids["tron-token"][1], chain="tron",
                from_address="T-source", to_address="T-target", value_native="1.25", token_symbol="SAME",
                source_api="trongrid_trc20", event_index="7", asset_contract="T-contract",
                raw_payload={"_event_id": "trc20:" + "b" * 64})
            reused, inserted = persist_normalized_event(db, tron_token)
            assert reused.id == ids["tron-token"][0] and not inserted
            modern = NormalizedTransaction(tx_hash=ids["eth-token"][1], chain="ethereum", from_address=ADDR, to_address=TO,
                value_native="1.25", token_symbol="SAME", source_api="etherscan_token", event_index="2", asset_contract=CONTRACT)
            reused, inserted = persist_normalized_event(db, modern)
            assert reused.id == ids["eth-token"][0] and not inserted
            old_token = modern.model_copy(update={"tx_hash": ids["legacy-token"][1], "event_index": None})
            reused, inserted = persist_normalized_event(db, old_token)
            assert reused.id == ids["legacy-token"][0] and not inserted
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.execute(text("PRAGMA table_info(transactions)")).all()
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260923_02"
        assert _triggers(engine) == old_triggers
        view = inspect(engine)
        assert {column["name"] for column in view.get_columns("transactions")} == set(Transaction.__table__.columns.keys())
        assert view.get_columns("transactions")[0]["nullable"] is False
        uniques = {tuple(item["column_names"]) for item in view.get_unique_constraints("transactions")}
        assert ("chain", "tx_hash", "event_key") in uniques
        assert ("chain", "tx_hash", "from_address", "to_address", "value_native", "token_symbol") not in uniques
        assert {"ix_transactions_event_index", "ix_transactions_asset_contract"} <= {item["name"] for item in view.get_indexes("transactions")}
    finally:
        engine.dispose()


def test_downgrade_refuses_conflicting_events_before_mutation(tmp_path, monkeypatch):
    cfg, engine = _migration_db(tmp_path, monkeypatch, "20260923_02")
    try:
        with Session(engine) as db:
            base = dict(tx_hash=HASH, chain="ethereum", from_address=ADDR, to_address=TO,
                        value_native="1", token_symbol="SAME", source_api="etherscan_token", asset_contract=CONTRACT)
            db.add_all([Transaction(**base, event_key="evm-log:1", event_index="1"),
                        Transaction(**base, event_key="evm-log:2", event_index="2")])
            db.commit()
        before = _triggers(engine)
        with pytest.raises(RuntimeError, match="Cannot downgrade MC-3A"):
            command.downgrade(cfg, "20260923_01")
        with Session(engine) as db:
            assert db.query(Transaction).count() == 2
            assert {row.event_key for row in db.scalars(select(Transaction)).all()} == {"evm-log:1", "evm-log:2"}
        assert _triggers(engine) == before
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260923_02"
    finally:
        engine.dispose()


def test_safe_downgrade_restores_old_schema_and_reupgrade_identity(tmp_path, monkeypatch):
    cfg, engine = _migration_db(tmp_path, monkeypatch, "20260923_01")
    try:
        with engine.connect() as connection:
            old_columns = inspect(connection).get_columns("transactions")
            old_uniques = inspect(connection).get_unique_constraints("transactions")
            old_indexes = connection.execute(text(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='transactions' ORDER BY name"
            )).all()
            old_foreign_keys = connection.execute(text("PRAGMA foreign_key_list(transactions)")).all()
        old_triggers = _triggers(engine)
        command.upgrade(cfg, "20260923_02")
        with Session(engine) as db:
            row, inserted = persist_normalized_event(db, NormalizedTransaction(tx_hash=HASH, chain="ethereum",
                from_address=ADDR, to_address=TO, value_native="1", token_symbol="ETH", source_api="etherscan"))
            db.commit(); original_id = row.id
        command.downgrade(cfg, "20260923_01")
        with engine.connect() as connection:
            restored_columns = inspect(connection).get_columns("transactions")
            restored_uniques = inspect(connection).get_unique_constraints("transactions")
            restored_indexes = connection.execute(text(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='transactions' ORDER BY name"
            )).all()
            restored_foreign_keys = connection.execute(text("PRAGMA foreign_key_list(transactions)")).all()
        def column_signature(columns):
            return [(column["name"], str(column["type"]), column["nullable"],
                     str(column["default"]).strip("()'") if column["default"] is not None else None,
                     column["primary_key"]) for column in columns]
        assert column_signature(restored_columns) == column_signature(old_columns)
        assert {tuple(item["column_names"]) for item in restored_uniques} == {
            tuple(item["column_names"]) for item in old_uniques
        }
        assert restored_indexes == old_indexes
        assert restored_foreign_keys == old_foreign_keys
        assert _triggers(engine) == old_triggers
        assert "event_key" not in {column["name"] for column in inspect(engine).get_columns("transactions")}
        command.upgrade(cfg, "20260923_02")
        with Session(engine) as db:
            row = db.scalar(select(Transaction).where(Transaction.id == original_id))
            assert row.event_key == "tx"
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()


def test_ethereum_monitoring_distinguishes_event_alerts_and_deduplicates_repolls(monkeypatch):
    import asyncio
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker
    from greedy_collector.monitoring import _monitor_chain
    from greedy_collector.models import MonitoringRun, WalletAlert, WatchlistWallet
    from greedy_collector.services import GreedyCollectorService

    engine = create_fk_enabled_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    adapter = EthereumAdapter()
    base_tx = adapter._normalize_token(_token_row("0x1"), ADDR)
    event_a = adapter._normalize_token(_token_row("0x2"), ADDR)
    event_b = adapter._normalize_token(_token_row("0x3"), ADDR)
    # Monitoring consumes the public normalized result shape, including the
    # server-derived event identity; raw provider payload is not required.
    base_dict = GreedyCollectorService._tx_dict(base_tx)
    a_dict = GreedyCollectorService._tx_dict(event_a)
    b_dict = GreedyCollectorService._tx_dict(event_b)

    with sessions() as db:
        watch = WatchlistWallet(chain="ethereum", address=ADDR, enabled=True)
        db.add(watch); db.commit(); watch_id = watch.id

    shared_results = [[base_dict], [b_dict, a_dict, base_dict], [b_dict, a_dict, base_dict]]
    class FakeService:
        async def lookup_address(self, db, request):
            return {"transactions": shared_results.pop(0), "risk": {"score": 0, "findings": []}}

    monkeypatch.setattr("greedy_collector.monitoring.SessionLocal", sessions)
    monkeypatch.setattr("greedy_collector.monitoring.GreedyCollectorService", FakeService)
    try:
        baseline = asyncio.run(_monitor_chain("ethereum", watch_id))
        new_events = asyncio.run(_monitor_chain("ethereum", watch_id))
        repeat = asyncio.run(_monitor_chain("ethereum", watch_id))
        with sessions() as db:
            alerts = db.scalars(select(WalletAlert).where(WalletAlert.wallet == ADDR)).all()
            runs = db.scalars(select(MonitoringRun).where(MonitoringRun.wallet_id == watch_id)
                              .order_by(MonitoringRun.started_at)).all()
            assert baseline["processed"] == new_events["processed"] == repeat["processed"] == 1
            assert [run.new_transactions for run in runs] == [0, 2, 0]
            assert len(alerts) == 2 and len({alert.dedupe_key for alert in alerts}) == 2
            assert {alert.tx_hash for alert in alerts} == {HASH}
            watch = db.get(WatchlistWallet, watch_id)
            assert watch.last_seen_tx == b_dict["event_identity"]
    finally:
        engine.dispose()
