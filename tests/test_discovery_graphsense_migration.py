"""ED9B constraint-only successor; every database temporary."""
from datetime import datetime,timezone
from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy.orm import Session
from greedy_collector.models import Base
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.discovery.graphsense import require_schema,observation,parse_pack,file_candidate,TRANSFORM_ID
from greedy_collector.discovery.domain import canonical_subject,SchemaUnavailable
from greedy_collector.discovery.manual_source import ManualSourceService
from greedy_collector.discovery.service import DiscoveryService
from tests.test_discovery_ens_migration import database,snapshot,triggers,seed_history
from tests.test_discovery_promotion_migration import signature
from tests.test_discovery_manual_source import data
from tests.graphsense_fixture import pack,material,ETH
from tests.test_discovery_ens_foundation import ens_registry,store_ens

HEAD='20260922_02'
PARENT='20260922_01'

def test_clean_upgrade_parity_no_seeds(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,HEAD);orm=create_fk_enabled_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(orm)
        for table in Base.metadata.tables:
            if table.startswith(('discovery_','attribution_')):assert signature(engine,table)==signature(orm,table),table
        assert triggers(engine)==triggers(orm) and all(not rows for rows in snapshot(engine).values())
        assert ScriptDirectory.from_config(cfg).get_heads()==[HEAD]
        with Session(engine) as db:require_schema(db)
    finally:engine.dispose();orm.dispose()

def test_populated_upgrade_and_guarded_downgrade(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine)
        with Session(engine) as db:store_ens(DiscoveryService(db,registry=ens_registry()))
        with Session(engine) as db:
            svc=ManualSourceService(db);p=svc.preview(data());svc.capture({'capture':data(),'expected_preview_fingerprint':p['preview_fingerprint']})
        before=snapshot(engine);protected=triggers(engine);schemas={t:signature(engine,t) for t in Base.metadata.tables}
        command.upgrade(cfg,HEAD)
        assert snapshot(engine)==before and triggers(engine)==protected
        for table,old in schemas.items():
            actual=signature(engine,table)
            if table=='discovery_results':actual['checks']=[(n,s.replace(", 'publicly_labeled_as'",'')) for n,s in actual['checks']]
            assert actual==old,table
        with Session(engine) as db:
            require_schema(db);ManualSourceService(db)
            svc=DiscoveryService(db);subject=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
            row=svc.create_run(subject['id'],[{'transform_id':TRANSFORM_ID,'source_id':'github','parameters':{'max_results':100}}],idempotency_key='migration-public-tag')
            row=svc.transition_run(row['id'],'running',expected_version=row['version'])
            sid=row['sources'][0]['id'];svc.transition_source(sid,'running',expected_run_version=row['version'])
            item,blob=material(pack());import base64
            canonical=canonical_subject('blockchain_address','ethereum',ETH)
            tag=parse_pack(base64.b64decode(blob['content']),canonical)[0][0]
            candidate=observation(tag,file_candidate(item),canonical,datetime.now(timezone.utc))
            row=svc.get_run(row['id']);svc.record_batch(sid,[candidate],expected_run_version=row['version'])
        retained=snapshot(engine)
        with pytest.raises(RuntimeError,match='retained'):command.downgrade(cfg,PARENT)
        assert snapshot(engine)==retained
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()

def test_old_schema_stamp_only_and_ed9a_compatibility(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        with Session(engine) as db:
            ManualSourceService(db)
            with pytest.raises(SchemaUnavailable):require_schema(db)
        with engine.begin() as c:c.exec_driver_sql("UPDATE alembic_version SET version_num='20260922_02'")
        with Session(engine) as db:
            with pytest.raises(SchemaUnavailable):require_schema(db)
    finally:engine.dispose()

def test_empty_public_downgrade_roundtrip(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine);before=snapshot(engine);schema=signature(engine,'discovery_results')
        command.upgrade(cfg,HEAD);command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before and signature(engine,'discovery_results')==schema
        command.upgrade(cfg,HEAD)
        with Session(engine) as db:require_schema(db)
    finally:engine.dispose()
