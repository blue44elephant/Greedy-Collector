"""Add stable event identity to normalized transaction activity rows."""
from __future__ import annotations

import hashlib
import json
import re

import sqlalchemy as sa
from alembic import op

revision = "20260923_02"
down_revision = "20260923_01"
branch_labels = None
depends_on = None

OLD_UNIQUE = "uq_transaction_transfer"
NEW_UNIQUE = "uq_transaction_event_identity"
EVENT_INDEX = "ix_transactions_event_index"
ASSET_CONTRACT_INDEX = "ix_transactions_asset_contract"
EVENT_ID = re.compile(r"[a-z0-9_-]{1,24}:[0-9a-f]{64}\Z")


def _index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and len(value) <= 20:
        if re.fullmatch(r"[0-9]+", value):
            number = int(value, 10)
        elif re.fullmatch(r"0x[0-9a-fA-F]{1,16}", value):
            number = int(value, 16)
        else:
            return None
    else:
        return None
    return str(number) if 0 <= number < 2**64 else None


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _legacy_key(row, *, prefix="legacy", contract=None):
    values = [row.get(key) for key in (
        "chain", "tx_hash", "from_address", "to_address", "value_native", "token_symbol"
    )]
    values.append(contract)
    return prefix + ":" + _digest(values)


def _payload(row):
    value = row.get("raw_payload")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}
    return value if isinstance(value, dict) else {}


def _provider_fields(row):
    payload = _payload(row)
    provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else payload
    public = payload.get("_public") if isinstance(payload.get("_public"), dict) else {}

    if row.get("chain") == "bitcoin":
        return _legacy_key(row, prefix="activity"), None, None

    old_identity = payload.get("_gc_event_identity")
    if isinstance(old_identity, dict) and isinstance(old_identity.get("event_key"), str):
        return old_identity["event_key"], _index(old_identity.get("event_index")), old_identity.get("asset_contract")

    provider_event = payload.get("_event_id")
    if isinstance(provider_event, str) and EVENT_ID.fullmatch(provider_event):
        index = _index(provider.get("event_index", provider.get("log_index")))
        contract = public.get("token_contract") or payload.get("asset_contract")
        return "provider:" + provider_event, index, contract

    is_token = row.get("source_api") == "etherscan_token" or row.get("source_api") == "trongrid_trc20"
    if row.get("chain") == "ethereum" and is_token:
        raw_index = provider.get("logIndex", provider.get("log_index"))
        index = _index(raw_index)
        contract = provider.get("contractAddress", provider.get("tokenContractAddress"))
        if isinstance(contract, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", contract):
            contract = contract.lower()
        elif not isinstance(contract, str) or not contract or len(contract) > 128:
            contract = None
        if index is not None:
            return "evm-log:" + index, index, contract
        return _legacy_key(row, contract=contract), None, contract

    if is_token:
        contract = public.get("token_contract")
        index = _index(provider.get("event_index", provider.get("log_index")))
        return _legacy_key(row, contract=contract), index, contract

    return None, None, None


def _capture_triggers(connection):
    rows = connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='trigger'").all()
    return [(name, sql) for name, sql in rows if sql]


def _rebuild(upgrade):
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        raise RuntimeError("MC-3A currently supports the project's SQLite migration path only")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one():
        raise RuntimeError("Run MC-3A using the dedicated SQLite Alembic connection with foreign keys disabled")
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    if not upgrade:
        conflict = connection.exec_driver_sql(
            "SELECT 1 FROM transactions GROUP BY chain, tx_hash, from_address, to_address, value_native, token_symbol HAVING COUNT(*) > 1 LIMIT 1"
        ).first()
        if conflict:
            raise RuntimeError("Cannot downgrade MC-3A while distinct normalized events conflict with the legacy transaction uniqueness rule")

    triggers = _capture_triggers(connection)
    for name, _ in triggers:
        connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')

    if upgrade:
        op.add_column("transactions", sa.Column("event_key", sa.String(160), nullable=True))
        op.add_column("transactions", sa.Column("event_index", sa.String(80), nullable=True))
        op.add_column("transactions", sa.Column("asset_contract", sa.String(128), nullable=True))
        rows = [dict(row) for row in connection.exec_driver_sql(
            "SELECT id, chain, tx_hash, from_address, to_address, value_native, token_symbol, source_api, raw_payload FROM transactions"
        ).mappings()]
        counts = {}
        for row in rows:
            pair = (row["chain"], row["tx_hash"])
            counts[pair] = counts.get(pair, 0) + 1
        assigned = set()
        for row in rows:
            key, index, contract = _provider_fields(row)
            if key is None:
                if counts[(row["chain"], row["tx_hash"])] == 1:
                    key = "tx"
                else:
                    key = _legacy_key(row)
            identity = (row["chain"], row["tx_hash"], key)
            if identity in assigned:
                raise RuntimeError("Existing transaction rows cannot be assigned unique deterministic event keys")
            assigned.add(identity)
            connection.execute(sa.text(
                "UPDATE transactions SET event_key=:event_key, event_index=:event_index, asset_contract=:asset_contract WHERE id=:id"
            ), {"event_key": key, "event_index": index, "asset_contract": contract, "id": row["id"]})

        with op.batch_alter_table("transactions", recreate="always") as batch:
            batch.drop_constraint(OLD_UNIQUE, type_="unique")
            batch.alter_column("event_key", existing_type=sa.String(160), nullable=False,
                               server_default=sa.text("'tx'"))
            batch.create_unique_constraint(NEW_UNIQUE, ["chain", "tx_hash", "event_key"])
            batch.create_index(EVENT_INDEX, ["event_index"], unique=False)
            batch.create_index(ASSET_CONTRACT_INDEX, ["asset_contract"], unique=False)
    else:
        rows = connection.exec_driver_sql(
            "SELECT id, raw_payload, event_key, event_index, asset_contract FROM transactions"
        ).mappings().all()
        for row in rows:
            payload = _payload(dict(row))
            payload = dict(payload)
            payload["_gc_event_identity"] = {
                "event_key": row["event_key"],
                "event_index": row["event_index"],
                "asset_contract": row["asset_contract"],
            }
            connection.execute(sa.text("UPDATE transactions SET raw_payload=:payload WHERE id=:id"),
                {"payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")), "id": row["id"]})
        with op.batch_alter_table("transactions", recreate="always") as batch:
            batch.drop_index(ASSET_CONTRACT_INDEX)
            batch.drop_index(EVENT_INDEX)
            batch.drop_constraint(NEW_UNIQUE, type_="unique")
            batch.drop_column("asset_contract")
            batch.drop_column("event_index")
            batch.drop_column("event_key")
            batch.create_unique_constraint(OLD_UNIQUE, ["chain", "tx_hash", "from_address", "to_address", "value_native", "token_symbol"])

    for _, sql in triggers:
        connection.exec_driver_sql(sql)
    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("MC-3A transaction migration failed foreign_key_check")


def upgrade():
    _rebuild(True)


def downgrade():
    _rebuild(False)
