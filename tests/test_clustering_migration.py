"""Explicit temporary SQLite migration checks; operator database never opened."""
import hashlib
import subprocess
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Transaction, Case, CaseEntity
from greedy_collector.clustering.models import Base, Version
from greedy_collector.clustering.service import ClusteringService
from tests.test_clustering import address, store

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def migrated(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'clustering.db').as_posix()
    monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'))
    command.upgrade(cfg,'20260923_02')
    engine=create_fk_enabled_engine(url)
    yield cfg,engine
    engine.dispose()

def test_upgrade_preserves_data_schema_and_historical_migrations(migrated):
    cfg,engine=migrated
    historic={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'migrations/versions').glob('*.py') if not p.name.startswith('20260927_01')}
    with Session(engine) as db:store(db,[address(1),address(2)])
    with engine.connect() as connection:
        rows=connection.execute(text('SELECT * FROM transactions')).all()
        triggers=connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all()
        schema=connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type IN ('table','index') AND name != 'alembic_version'")).all()
    command.upgrade(cfg,'20260927_01')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT * FROM transactions')).all()==rows
        assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar()=='20260927_01'
        current=dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all())
        assert all(current[name]==sql for name,sql in triggers)
        current_schema=dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type IN ('table','index')")).all())
        assert all(current_schema[name]==sql for name,sql in schema)
    assert {i['name'] for i in inspect(engine).get_indexes('technical_cluster_members')}=={'ix_technical_member_lookup'}
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in historic.items())
    # Migration history in the worktree must also match the committed baseline.
    assert subprocess.run(['git','diff','--exit-code','HEAD','--',*[str(p.relative_to(ROOT)) for p in historic]],cwd=ROOT,capture_output=True).returncode==0
    with Session(engine) as db:
        result=ClusteringService(db).analyze('bitcoin')
        assert len(result['clusters'])==1
        assert db.execute(text('PRAGMA foreign_key_check')).all()==[]

@pytest.mark.parametrize('table',['technical_cluster_versions','technical_cluster_members','technical_cluster_evidence','technical_cluster_exclusions','technical_cluster_evidence_links'])
def test_history_update_delete_forbidden(migrated,table):
    cfg,engine=migrated;command.upgrade(cfg,'20260927_01')
    with Session(engine) as db:
        store(db,[address(1),address(2)])
        evidence=ClusteringService(db).analyze('bitcoin')['evidence'][0]
        ClusteringService(db).exclude(evidence['id'],'Test reviewed exclusion')
    key='version_id' if table.endswith(('_members','_links')) else 'id'
    for sql in [f'UPDATE {table} SET {key}={key}',f'DELETE FROM {table}']:
        with engine.connect() as connection:
            with pytest.raises(IntegrityError,match='immutable'):connection.execute(text(sql))
            connection.rollback()

def test_case_pin_and_cluster_identity_immutable(migrated):
    cfg,engine=migrated;command.upgrade(cfg,'head')
    with Session(engine) as db:
        store(db,[address(1),address(2)]);snap=ClusteringService(db).analyze('bitcoin')['clusters'][0]
        db.add(Case(id='case',title='Test'));db.commit()
        ClusteringService(db).pin('case',snap['id'],1)
    for sql in ["UPDATE technical_clusters SET chain='litecoin'", "UPDATE case_entities SET metadata_json='{}'"]:
        with engine.connect() as connection:
            with pytest.raises(IntegrityError,match='immutable'):connection.execute(text(sql))
            connection.rollback()

def test_empty_downgrade_safe(migrated):
    cfg,engine=migrated;command.upgrade(cfg,'20260927_01');command.downgrade(cfg,'20260923_02')
    assert not set(Base.metadata.tables).intersection(inspect(engine).get_table_names())
    with engine.connect() as connection:assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]

def test_populated_downgrade_refuses_loss(migrated):
    cfg,engine=migrated;command.upgrade(cfg,'20260927_01')
    with Session(engine) as db:
        store(db,[address(1),address(2)]);ClusteringService(db).analyze('bitcoin')
    with pytest.raises(RuntimeError,match='retained'):command.downgrade(cfg,'20260923_02')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM technical_cluster_versions')).scalar()==1
        assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]

def test_uninitialized_clustering_does_not_create_tables(migrated):
    from greedy_collector.clustering.domain import ClusteringError
    cfg,engine=migrated
    with Session(engine) as db:
        with pytest.raises(ClusteringError,match='migration'):ClusteringService(db).analyze('bitcoin')
    assert not set(Base.metadata.tables).intersection(inspect(engine).get_table_names())
