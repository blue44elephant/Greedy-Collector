"""FL-1 upgrade/downgrade against isolated SQLite with old history preserved."""
import hashlib
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text,inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Case
from greedy_collector.clustering.service import ClusteringService
from greedy_collector.fund_flow.service import FlowService
from greedy_collector.fund_flow.schemas import FlowQuery
from greedy_collector.fund_flow.domain import FlowError
from tests.test_fund_flow import event,A,C
from tests.test_clustering import store,address
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def migration(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'flow.db').as_posix();monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'))
    command.upgrade(cfg,'20260927_01');engine=create_fk_enabled_engine(url)
    yield cfg,engine
    engine.dispose()


def test_upgrade_preserves_transactions_clusters_and_old_migrations(migration):
    cfg,engine=migration
    historical={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'migrations/versions').glob('*.py') if not p.name.startswith('20260927_02')}
    with Session(engine) as db:
        event(db,A,C);store(db,[address(1),address(2)]);ClusteringService(db).analyze('bitcoin')
    with engine.connect() as c:
        rows=c.execute(text('SELECT * FROM transactions')).all();clusters=c.execute(text('SELECT * FROM technical_cluster_versions')).all()
        triggers=dict(c.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all())
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(text('SELECT * FROM transactions')).all()==rows
        assert c.execute(text('SELECT * FROM technical_cluster_versions')).all()==clusters
        assert c.execute(text('PRAGMA foreign_key_check')).all()==[]
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='20261013_01_narcotics_network_intelligence'
        after=dict(c.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all())
        assert all(after[k]==v for k,v in triggers.items())
        indexes={row[0] for row in c.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions'"))}
        assert {'ix_flow_from','ix_flow_to','ix_flow_from_folded','ix_flow_to_folded','ix_flow_asset_time'} <= indexes
        plan=c.execute(text("EXPLAIN QUERY PLAN SELECT id FROM transactions WHERE chain='ethereum' AND from_address=:source AND timestamp>=:time"),{'source':A,'time':'2026-01-01'}).all()
        assert any('ix_flow_from' in str(row) for row in plan)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==value for p,value in historical.items())
    with Session(engine) as db:assert FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=C))['paths']


def test_run_and_case_pin_immutable(migration):
    cfg,engine=migration;command.upgrade(cfg,'head')
    with Session(engine) as db:
        event(db,A,C);run=FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=C))
        db.add(Case(id='flow-case',title='Flow'));db.commit();FlowService(db).pin('flow-case',run['id'])
    for sql in ["UPDATE fund_flow_runs SET snapshot='{}'","DELETE FROM fund_flow_runs","UPDATE case_entities SET metadata_json='{}'"]:
        with engine.connect() as c:
            with pytest.raises(IntegrityError,match='immutable'):c.execute(text(sql))
            c.rollback()
    with engine.connect() as c:assert c.execute(text('PRAGMA foreign_key_check')).all()==[]


def test_downgrade_empty_only(migration):
    cfg,engine=migration;command.upgrade(cfg,'head');command.downgrade(cfg,'20260927_01')
    assert 'fund_flow_runs' not in inspect(engine).get_table_names()
    command.upgrade(cfg,'head')
    with Session(engine) as db:
        event(db,A,C);FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=C))
    with pytest.raises(RuntimeError,match='retained'):command.downgrade(cfg,'20260927_01')


def test_no_implicit_storage_creation(migration):
    cfg,engine=migration
    with Session(engine) as db:
        with pytest.raises(FlowError,match='migration'):FlowService(db).analyze(FlowQuery(chain='ethereum',source=A,target=C))
    assert 'fund_flow_runs' not in inspect(engine).get_table_names()
