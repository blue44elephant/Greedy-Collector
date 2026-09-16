"""ED-8A0 migrations operate only on isolated SQLite files, never the user DB."""
import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, DiscoverySubject, DiscoveryRun, DiscoveryResult
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.domain import SchemaUnavailable
from greedy_collector.discovery.promotion import PromotionService
from greedy_collector.discovery.graph import graph_summary
from greedy_collector.attribution.service import AttributionService
from tests.test_attribution_migration import config
from tests.test_discovery_promotion_migration import signature
from tests.test_discovery_promotion import material
from tests.test_discovery_ens_foundation import block_network, ens_registry, store_ens, ETH

REVISION='20260916_01'
PARENT='20260915_01'
ROOT=Path(__file__).resolve().parents[1]


def database(tmp_path,monkeypatch,revision):
    url='sqlite:///'+(tmp_path/'migration.db').as_posix()
    cfg=config(url,monkeypatch);command.upgrade(cfg,revision)
    return cfg,create_fk_enabled_engine(url)


def snapshot(engine):
    with engine.connect() as c:
        return {t:sorted(c.exec_driver_sql('SELECT * FROM "'+t+'"').all(),key=repr)
                for t in inspect(c).get_table_names() if t!='alembic_version'}


def triggers(engine):
    with engine.connect() as c:return dict(c.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").all())


def checks(engine):return {c['name']:c['sqltext'] for c in inspect(engine).get_check_constraints('discovery_subjects')}


def seed_history(engine):
    sessions=sessionmaker(engine,autoflush=False,expire_on_commit=False)
    label=material((None,sessions,None),'label')
    code=material((None,sessions,None),'github')
    with sessions() as db:
        at=AttributionService(db)
        entity=at.create_entity({'canonical_name':'Test explicit entity'})
        claim=at.create_claim(dict(entity_id=entity['id'],chain='ethereum',subject_ref=ETH,
            relationship='operated_by',scope_note='Test explicit claim'))
        promotion=PromotionService(db);preview=promotion.preview(code['id'])
        saved=promotion.promote(code['id'],dict(result_id=code['result_id'],claim_id=claim['id'],expected_claim_version=1,
            expected_source_fingerprint=preview['source_fingerprint'],
            link=dict(stance='context',directness='context',rationale='Test explicit context')))
        svc=DiscoveryService(db)
        for run in db.scalars(select(DiscoveryRun)).all():
            svc.transition_run(run.id,'completed',expected_version=run.version)
        graphs={r.id:graph_summary(svc,r.id).model_dump() for r in db.scalars(select(DiscoveryRun)).all()}
    return label,code,saved,graphs


def test_clean_upgrade_discovery_attribution_parity_and_no_seeds(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,REVISION)
    orm=create_fk_enabled_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(orm)
        for table in Base.metadata.tables:
            # Legacy tables have pre-existing ORM/server-default differences.
            # Assert exact parity for both migrated families; the populated
            # upgrade test separately proves every other table is unchanged.
            if table.startswith(('discovery_','attribution_')):
                assert signature(engine,table)==signature(orm,table),table
        assert triggers(engine)==triggers(orm)
        assert all(not rows for rows in snapshot(engine).values())
        with engine.connect() as c:
            assert c.exec_driver_sql('PRAGMA foreign_keys').scalar_one()==1
            assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        scripts=ScriptDirectory.from_config(cfg)
        assert scripts.get_heads()==[REVISION]
        assert [r.revision for r in scripts.walk_revisions()]==[REVISION,PARENT,'20260913_01','20260912_01','20260630_01']
    finally:engine.dispose();orm.dispose()


def test_upgrade_preserves_populated_history_promotions_and_graphs(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        label,code,promotion,graphs=seed_history(engine)
        before=snapshot(engine);old_triggers=triggers(engine)
        old_schema={t:signature(engine,t) for t in Base.metadata.tables}
        command.upgrade(cfg,REVISION)
        assert snapshot(engine)==before
        assert triggers(engine)==old_triggers
        for table in Base.metadata.tables:
            current=signature(engine,table)
            if table=='discovery_subjects':
                current_checks=dict(current['checks'])
                assert current_checks.pop('ck_discovery_subjects_8')=="kind != 'ens_name' OR namespace = 'ethereum'"
                assert current_checks['ck_discovery_subjects_1']=="kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation', 'ens_name')"
                current_checks['ck_discovery_subjects_1']=dict(old_schema[table]['checks'])['ck_discovery_subjects_1']
                current['checks']=sorted(current_checks.items())
            assert current==old_schema[table]
        with Session(engine) as db:
            svc=DiscoveryService(db)
            assert {r.id:graph_summary(svc,r.id).model_dump() for r in db.scalars(select(DiscoveryRun)).all()}==graphs
            assert PromotionService(db).history(code['result_id'])['items'][0]['id']==promotion['promotion']['id']
            # Newly explicit promotion after upgrade still uses the ED-6 path.
            p=PromotionService(db);preview=p.preview(label['id'])
            p.promote(label['id'],dict(result_id=label['result_id'],claim_id=promotion['claim']['id'],expected_claim_version=2,
                expected_source_fingerprint=preview['source_fingerprint'],link=dict(stance='context',directness='context',rationale='Test after upgrade')))
            assert AttributionService(db).get_claim(promotion['claim']['id'])['assessment']=='unassessed'
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()


@pytest.mark.parametrize('revision',[PARENT,REVISION])
def test_partial_revision_services_and_ens_gate(tmp_path,monkeypatch,revision):
    cfg,engine=database(tmp_path,monkeypatch,revision)
    try:
        with Session(engine) as db:
            assert AttributionService(db).list_entities()['total']==0
            assert DiscoveryService(db).list_runs()['total']==0
            PromotionService(db)
            svc=DiscoveryService(db,registry=ens_registry())
            if revision==PARENT:
                with pytest.raises(SchemaUnavailable,match='ED-8A0'):
                    svc.get_or_create_subject('ens_name','ethereum','fixture.eth')
                # Actual persisted constraint also rejects direct insertion.
                with pytest.raises(IntegrityError,match='ck_discovery_subjects_1'):
                    db.execute(DiscoverySubject.__table__.insert().values(kind='ens_name',namespace='ethereum',
                        canonical_value='fixture.eth',display_value='fixture.eth',identity_sha256='0'*64))
                db.rollback()
                seed_history(engine)  # All previously delivered operations remain available.
            else:
                run,ob,result=store_ens(svc)
                assert svc.get_subject(result['from_subject_id'])['kind']=='ens_name'
            assert db.connection().exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()==revision
    finally:engine.dispose()


def test_stamp_alone_cannot_enable_ens_storage(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        with engine.begin() as c:c.exec_driver_sql("UPDATE alembic_version SET version_num='20260916_01'")
        with Session(engine) as db:
            with pytest.raises(SchemaUnavailable):DiscoveryService(db).get_or_create_subject('ens_name','ethereum','fixture.eth')
        assert not snapshot(engine)['discovery_subjects']
    finally:engine.dispose()


def test_downgrade_and_reupgrade_preserve_existing_history(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine);before=snapshot(engine);old_checks=checks(engine);old_triggers=triggers(engine)
        command.upgrade(cfg,REVISION);command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before and checks(engine)==old_checks and triggers(engine)==old_triggers
        command.upgrade(cfg,REVISION)
        assert snapshot(engine)==before
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()


def test_downgrade_refuses_even_unreferenced_ens_without_any_data_loss(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,REVISION)
    try:
        with Session(engine) as db:DiscoveryService(db).get_or_create_subject('ens_name','ethereum','fixture.eth')
        before=snapshot(engine);schema=signature(engine,'discovery_subjects')
        with pytest.raises(RuntimeError,match='typed ENS endpoints exist'):command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before and signature(engine,'discovery_subjects')==schema
        with engine.connect() as c:
            assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()==REVISION
            assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()


def test_rebuilt_table_references_remain_enforced(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,REVISION)
    try:
        with Session(engine) as db:
            svc=DiscoveryService(db,registry=ens_registry());run,ob,result=store_ens(svc)
            subjects=[result['query_subject_id'],result['from_subject_id']]
        for id in subjects:
            with pytest.raises(IntegrityError):
                with engine.begin() as c:c.exec_driver_sql('DELETE FROM discovery_subjects WHERE id=?',(id,))
        with pytest.raises(IntegrityError):
            with engine.begin() as c:c.exec_driver_sql("UPDATE discovery_results SET from_subject_id='missing'")
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()


def test_previous_migrations_remain_byte_identical():
    expected=PRIOR_MIGRATION_HASHES
    for name,digest in expected.items():
        assert hashlib.sha256((ROOT/'migrations'/'versions'/name).read_bytes()).hexdigest()==digest


def test_failed_fk_validation_rolls_back_table_rebuild_and_revision(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine)
        # Simulate existing corrupt input using a separate test-only connection.
        import sqlite3
        with sqlite3.connect(tmp_path/'migration.db') as c:
            c.execute("UPDATE discovery_results SET from_subject_id='missing'")
        before=snapshot(engine);old_schema=signature(engine,'discovery_subjects');old_triggers=triggers(engine)
        with pytest.raises(RuntimeError,match='foreign-key validation'):command.upgrade(cfg,REVISION)
        assert snapshot(engine)==before
        assert signature(engine,'discovery_subjects')==old_schema and triggers(engine)==old_triggers
        with engine.connect() as c:
            assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()==PARENT
            assert c.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'").all()==[]
    finally:engine.dispose()


PRIOR_MIGRATION_HASHES = {
    '20260630_01_greedy_collector.py':'557d047f3ebdd50c2c8fbc21d5da1319149674bd65875429a7b6bf014de3b782',
    '20260912_01_attribution.py':'ee709c59f5520f03eaa38b4af010f1286436f03d3885e6ed62eb7f7193ebfcb8',
    '20260913_01_discovery.py':'bb8cd33e2a91cfa5b9cbb90428bf18b6dd0ee8623bf916a13a8e7ffdcc6eb2ec',
    '20260915_01_discovery_promotions.py':'daec59aa4f49b79081f64bd79b5b6072d0f71a91864921fecbc0605e0bb84ece',
}
