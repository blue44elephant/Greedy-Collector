"""Explicit migration, model parity, and lifecycle checks on temporary SQLite only."""
from io import StringIO
from pathlib import Path
import os
import subprocess
import sys

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, AttributionEntity, ATTRIBUTION_TRIGGER_SQL
from greedy_collector.attribution.service import AttributionService, REVISION, TABLES

ROOT=Path(__file__).resolve().parents[1]


def config(url,monkeypatch):
    monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    cfg=Config(str(ROOT/'alembic.ini'),stdout=StringIO())
    cfg.set_main_option('script_location',str(ROOT/'migrations'))
    return cfg


def schema(engine):
    view=inspect(engine)
    result={}
    for table in TABLES:
        result[table]={
            'columns':[(c['name'],str(c['type']),c['nullable'],c['default']) for c in view.get_columns(table)],
            'pk':view.get_pk_constraint(table)['constrained_columns'],
            'indexes':sorted((i['name'],tuple(i['column_names']),i['unique']) for i in view.get_indexes(table)),
            'uniques':sorted((i['name'],tuple(i['column_names'])) for i in view.get_unique_constraints(table)),
            'fks':sorted((i['name'],tuple(i['constrained_columns']),i['referred_table'],tuple(i['referred_columns']),i['options'].get('ondelete')) for i in view.get_foreign_keys(table)),
            'checks':sorted((i['name'],i['sqltext']) for i in view.get_check_constraints(table)),
        }
    with engine.connect() as connection:
        result['triggers']=dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'attribution_%'")).all())
    return result


def test_clean_upgrade_schema_equivalence_and_foreign_keys(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'migrated.db').as_posix()
    cfg=config(url,monkeypatch)
    command.upgrade(cfg,'head'); command.current(cfg); command.heads(cfg)
    assert '20260915_01' in cfg.stdout.getvalue()
    migrated=create_fk_enabled_engine(url)
    metadata=create_fk_enabled_engine('sqlite:///'+(tmp_path/'metadata.db').as_posix())
    Base.metadata.create_all(metadata)
    try:
        assert schema(migrated)==schema(metadata)
        with migrated.connect() as connection:
            assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='20260915_01'
            assert len(connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).all())==19
        with Session(migrated) as db:
            svc=AttributionService(db)
            assert svc.list_entities()['total']==0
            svc.create_entity({'canonical_name':'Synthetic migrated service'})
            assert db.query(AttributionEntity).count()==1
    finally:
        migrated.dispose();metadata.dispose()


def test_upgrade_existing_baseline_preserves_rows_and_creates_no_attribution(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'baseline.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,'20260630_01')
    engine=create_fk_enabled_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO labels (id,address,chain,label,type,source,confidence,last_updated) VALUES ('test-label','test-address','any','Synthetic annotation','Unknown','Test only',0.7,'2026-09-12 00:00:00')"))
        before=connection.execute(text('SELECT * FROM labels')).all()
    old_tables=set(inspect(engine).get_table_names())
    command.upgrade(cfg,REVISION)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT * FROM labels')).all()==before
        assert set(inspect(engine).get_table_names())-old_tables==set(TABLES)
        for table in TABLES: assert connection.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one()==0
        assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
    engine.dispose()


def test_empty_downgrade_and_populated_history_protection(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'downgrade.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,REVISION);command.downgrade(cfg,'20260630_01');command.upgrade(cfg,REVISION)
    engine=create_fk_enabled_engine(url)
    with Session(engine) as db: AttributionService(db).create_entity({'canonical_name':'Retained synthetic history'})
    with pytest.raises(RuntimeError,match='populated attribution history'): command.downgrade(cfg,'20260630_01')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM attribution_entities')).scalar_one()==1
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==REVISION
    engine.dispose()


def test_normal_startup_has_guarded_attribution_routes_but_no_automatic_schema(tmp_path):
    code='''
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import inspect
import httpx
import main
from greedy_collector.database import engine
from greedy_collector.monitoring import scheduler
with patch.object(httpx.AsyncClient,'request',side_effect=AssertionError('No external provider')):
    with TestClient(main.app) as client:
        assert scheduler.running
        for route in ['/','/health','/docs','/openapi.json']:
            assert client.get(route).status_code==200
        html=client.get('/').text
        assert html.count('data-workspace=')==9
        assert 'data-workspace="attribution"' in html
        paths=client.get('/openapi.json').json()['paths']
        assert '/api/greedy-collector/attribution/entities' in paths
        assert client.get('/api/greedy-collector/attribution/entities').status_code==503
        assert not any(t.startswith('attribution_') for t in inspect(engine).get_table_names())
assert not scheduler.running
'''
    env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHON_DOTENV_DISABLED':'1','GREEDY_COLLECTOR_DATABASE_URL':'sqlite:///'+(tmp_path/'startup.db').as_posix(),
         'GREEDY_COLLECTOR_GRAPH_BACKEND':'sqlite','GREEDY_COLLECTOR_MONITORING_BACKEND':'apscheduler'}
    for key in ['ETHERSCAN_API_KEY','ALCHEMY_API_KEY','OPENSANCTIONS_API_KEY','VIRUSTOTAL_API_KEY','URLSCAN_API_KEY']:env[key]=''
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
