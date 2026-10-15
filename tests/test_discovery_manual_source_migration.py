from tests.multichain_migration_helpers import before_mc1
"""One successor constraint change; isolated clean/populated upgrades and gates."""
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from greedy_collector.models import Base
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.discovery.manual_source import ManualSourceService
from greedy_collector.discovery.domain import SchemaUnavailable
from tests.test_discovery_ens_migration import database,snapshot,triggers,seed_history
from tests.test_discovery_promotion_migration import signature
from tests.test_discovery_manual_source import data

HEAD='20260922_01'
PARENT='20260916_01'

def test_clean_ed9a_parity_no_seeds(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,HEAD);orm=create_fk_enabled_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(orm)
        for table in Base.metadata.tables:
            if table.startswith(('discovery_','attribution_')):
                expected=before_mc1(signature(orm,table))
                if table=='discovery_results':expected['checks']=[(name,sql.replace(", 'publicly_labeled_as'",'')) for name,sql in expected['checks']]
                assert signature(engine,table)==expected,table
        assert triggers(engine)==triggers(orm) and all(not rows for rows in snapshot(engine).values())
        assert ScriptDirectory.from_config(cfg).get_heads()==['20261013_01_narcotics_network_intelligence']
    finally:engine.dispose();orm.dispose()

def test_populated_upgrade_preserves_every_record_trigger_and_prior_schema(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine);before=snapshot(engine);protected=triggers(engine)
        schemas={t:signature(engine,t) for t in Base.metadata.tables if not t.startswith('sanctions_') and t not in ('case_events','case_reports')}
        command.upgrade(cfg,HEAD)
        assert snapshot(engine)==before and triggers(engine)==protected
        for table,old in schemas.items():
            actual=signature(engine,table)
            if table=='discovery_results':actual['checks']=[(name,sql.replace(", 'mentions_wallet'",'')) for name,sql in actual['checks']]
            assert actual==old,table
        with Session(engine) as db:
            svc=ManualSourceService(db);p=svc.preview(data());saved=svc.capture({'capture':data(),'expected_preview_fingerprint':p['preview_fingerprint']})
            assert saved['observation']['source_snapshot']['source_fetched'] is False
        retained=snapshot(engine)
        with pytest.raises(RuntimeError,match='retained'):command.downgrade(cfg,PARENT)
        assert snapshot(engine)==retained
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()

def test_old_schema_and_stamp_alone_block_capture(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        with Session(engine) as db:
            with pytest.raises(SchemaUnavailable):ManualSourceService(db)
        with engine.begin() as c:c.exec_driver_sql("UPDATE alembic_version SET version_num='20260922_01'")
        with Session(engine) as db:
            with pytest.raises(SchemaUnavailable):ManualSourceService(db)
        assert all(not rows for rows in snapshot(engine).values())
    finally:engine.dispose()

def test_empty_capture_downgrade_roundtrip(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine);before=snapshot(engine);schemas=signature(engine,'discovery_results')
        command.upgrade(cfg,HEAD);command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before and signature(engine,'discovery_results')==schemas
        command.upgrade(cfg,HEAD)
        assert snapshot(engine)==before
    finally:engine.dispose()
