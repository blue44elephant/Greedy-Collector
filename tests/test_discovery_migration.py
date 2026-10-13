"""ED-1 migrations and existing application boundaries on temporary SQLite only."""
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
from greedy_collector.models import Base, DISCOVERY_TRIGGER_SQL
from greedy_collector.discovery.service import DiscoveryService, TABLES, REVISION
from greedy_collector.discovery.domain import SchemaUnavailable
from greedy_collector.attribution.service import AttributionService
from tests.test_attribution_migration import schema as attribution_schema

ROOT=Path(__file__).resolve().parents[1]
PARENT='20260912_01'

def config(url,monkeypatch):
    monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    cfg=Config(str(ROOT/'alembic.ini'),stdout=StringIO())
    cfg.set_main_option('script_location',str(ROOT/'migrations'))
    return cfg

def discovery_schema(engine):
    view=inspect(engine); result={}
    for table in TABLES:
        result[table]={
            'columns':[(c['name'],str(c['type']),c['nullable'],c['default']) for c in view.get_columns(table)],
            'pk':view.get_pk_constraint(table)['constrained_columns'],
            'indexes':sorted((i['name'],tuple(i['column_names']),i['unique']) for i in view.get_indexes(table)),
            'uniques':sorted((i['name'],tuple(i['column_names'])) for i in view.get_unique_constraints(table)),
            'fks':sorted((i['name'],tuple(i['constrained_columns']),i['referred_table'],tuple(i['referred_columns']),i['options']) for i in view.get_foreign_keys(table)),
            'checks':sorted((i['name'],i['sqltext']) for i in view.get_check_constraints(table)),
        }
    with engine.connect() as connection:
        result['triggers']=dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'discovery_%' AND name NOT LIKE 'discovery_promotions_%'")).all())
    return result

def test_clean_upgrade_equivalence_and_successor_services(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'migrated.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,REVISION);command.current(cfg);command.heads(cfg)
    assert cfg.stdout.getvalue().splitlines()==[REVISION,'20261012_02_case_history (head)']
    migrated=create_fk_enabled_engine(url)
    metadata=create_fk_enabled_engine('sqlite:///'+(tmp_path/'metadata.db').as_posix())
    try:
        Base.metadata.create_all(metadata)
        # ED-1 retains its historical constraint; latest ORM adds ED-8A0 only.
        expected=discovery_schema(metadata)
        checks=dict(expected['discovery_subjects']['checks'])
        assert checks.pop('ck_discovery_subjects_8')=="kind != 'ens_name' OR namespace = 'ethereum'"
        assert checks['ck_discovery_subjects_1']=="kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation', 'ens_name')"
        checks['ck_discovery_subjects_6']="kind != 'blockchain_address' OR namespace IN ('bitcoin','ethereum')"
        checks['ck_discovery_subjects_1']="kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation')"
        expected['discovery_subjects']['checks']=sorted(checks.items())
        expected['discovery_results']['checks']=[(name,sql.replace(", 'mentions_wallet'",'').replace(", 'publicly_labeled_as'",'')) for name,sql in expected['discovery_results']['checks']]
        assert discovery_schema(migrated)==expected
        assert len(discovery_schema(migrated)['triggers'])==9
        with migrated.connect() as connection:
            assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==REVISION
            assert len(connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).all())==15
        assert 'discovery_promotions' not in inspect(migrated).get_table_names()
        with Session(migrated) as db:
            assert AttributionService(db).list_entities()['total']==0
            assert DiscoveryService(db).list_runs()['total']==0
            assert DiscoveryService(db).get_or_create_subject('blockchain_address','ethereum','0x'+'ab'*20)['id']
    finally:migrated.dispose();metadata.dispose()

def test_upgrade_preserves_attribution_and_legacy_rows(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'prior.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,PARENT);engine=create_fk_enabled_engine(url)
    try:
        with Session(engine) as db:entity=AttributionService(db).create_entity({'canonical_name':'Synthetic retained entity'})
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO labels (id,address,chain,label,type,source,confidence,last_updated) VALUES ('test-label','test-address','any','Synthetic annotation','Unknown','Test only',0.7,'2026-09-12 00:00:00')"))
            before={table:connection.execute(text('SELECT * FROM '+table)).all() for table in ('labels','attribution_entities','attribution_events')}
        old=set(inspect(engine).get_table_names());old_schema=attribution_schema(engine)
        command.upgrade(cfg,REVISION)
        assert set(inspect(engine).get_table_names())-old==set(TABLES)
        assert attribution_schema(engine)==old_schema
        with engine.connect() as connection:
            for table,rows in before.items():assert connection.execute(text('SELECT * FROM '+table)).all()==rows
            for table in TABLES:assert connection.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one()==0
            assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
        with Session(engine) as db:assert AttributionService(db).list_entities()['items'][0]['id']==entity['id']
    finally:engine.dispose()

def test_empty_downgrade_and_populated_history_guard(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'down.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,REVISION);command.downgrade(cfg,PARENT);command.upgrade(cfg,REVISION)
    engine=create_fk_enabled_engine(url)
    try:
        with Session(engine) as db:DiscoveryService(db).get_or_create_subject('blockchain_address','ethereum','0x'+'ab'*20)
        with pytest.raises(RuntimeError,match='populated'):command.downgrade(cfg,PARENT)
        with engine.connect() as connection:
            assert connection.execute(text('SELECT COUNT(*) FROM discovery_subjects')).scalar_one()==1
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==REVISION
            assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
    finally:engine.dispose()

@pytest.mark.parametrize('broken',['missing','fake_trigger','foreign_keys','unstamped'])
def test_schema_guard_requires_real_protection(tmp_path,broken):
    engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'guard.db').as_posix())
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            if broken in ('missing','fake_trigger'):
                name=next(iter(DISCOVERY_TRIGGER_SQL))
                db.execute(text('DROP TRIGGER '+name))
                if broken=='fake_trigger':db.execute(text('CREATE TRIGGER '+name+' BEFORE UPDATE ON discovery_observations BEGIN SELECT 1; END'))
                db.commit()
            if broken=='foreign_keys':db.execute(text('PRAGMA foreign_keys=OFF'))
            with pytest.raises(SchemaUnavailable):DiscoveryService(db,metadata_only=broken!='unstamped')
    finally:engine.dispose()

@pytest.mark.parametrize('migrated',[False,True])
def test_startup_shutdown_existing_workspaces_no_discovery_execution(tmp_path,monkeypatch,migrated):
    url='sqlite:///'+(tmp_path/'startup.db').as_posix()
    if migrated:command.upgrade(config(url,monkeypatch),'head')
    code='''
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import inspect,text
import httpx,main
from greedy_collector.database import engine
from greedy_collector.monitoring import scheduler
from greedy_collector.discovery.registry import REGISTRY
def prohibited(*args,**kwargs):raise AssertionError('No external requests')
with patch.object(httpx.HTTPTransport,'handle_request',prohibited), patch.object(httpx.AsyncHTTPTransport,'handle_async_request',prohibited):
    assert not any(t['executable'] for t in REGISTRY.capabilities()['transforms'])
    with TestClient(main.app) as client:
        assert scheduler.running
        for route in ['/','/health','/docs','/openapi.json','/static/js/app.js','/static/app.css']:
            assert client.get(route).status_code==200,route
        html=client.get('/').text
        assert html.count('data-workspace=')==12
        assert 'data-workspace="discovery"' in html
        paths=client.get('/openapi.json').json()['paths']
        assert '/api/greedy-collector/discovery/runs' in paths
        assert client.get('/api/greedy-collector/discovery/runs').status_code==(200 if MIGRATED else 503)
        exists='discovery_runs' in inspect(engine).get_table_names()
        assert exists==MIGRATED
        assert client.get('/api/greedy-collector/attribution/entities').status_code==(200 if MIGRATED else 503)
        if exists:
            with engine.connect() as c:
                for table in inspect(engine).get_table_names():
                    if table.startswith('discovery_'):assert c.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one()==0
                assert c.execute(text('PRAGMA foreign_key_check')).all()==[]
assert not scheduler.running
'''.replace('MIGRATED',str(migrated))
    env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHON_DOTENV_DISABLED':'1','GREEDY_COLLECTOR_DATABASE_URL':url,
         'GREEDY_COLLECTOR_GRAPH_BACKEND':'sqlite','GREEDY_COLLECTOR_MONITORING_BACKEND':'apscheduler'}
    for key in ('ETHERSCAN_API_KEY','ALCHEMY_API_KEY','OPENSANCTIONS_API_KEY','VIRUSTOTAL_API_KEY','URLSCAN_API_KEY','DISCOVERY_GITHUB_TOKEN'):env[key]=''
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
