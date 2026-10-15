import pytest
from sqlalchemy import inspect,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from alembic import command
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.narcotics.models import Base, RECORD_MODELS
from tests.test_attribution_migration import config
from tests.test_narcotics import api, migrated_template, create, profile, related, N, ok

REVISION='20261013_01_narcotics_network_intelligence'
PARENT='20261012_02_case_history'
def test_migration_no_seeds_upgrade_downgrade_and_metadata(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'narcotics.db').as_posix();cfg=config(url,monkeypatch)
    command.upgrade(cfg,PARENT);engine=create_fk_enabled_engine(url)
    before=set(inspect(engine).get_table_names());command.upgrade(cfg,REVISION)
    added=set(inspect(engine).get_table_names())-before
    assert added=={m.__tablename__ for m in RECORD_MODELS}
    with engine.connect() as c:
        assert all(c.exec_driver_sql('SELECT count(*) FROM '+t).scalar()==0 for t in added)
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    for model in RECORD_MODELS:
        assert set(inspect(engine).get_columns(model.__tablename__)[i]['name'] for i in range(len(model.__table__.columns)))==set(model.__table__.columns.keys())
    command.downgrade(cfg,PARENT)
    assert set(inspect(engine).get_table_names())==before
    command.upgrade(cfg,'head');engine.dispose()

@pytest.mark.parametrize('table',[m.__tablename__ for m in RECORD_MODELS if m.__name__!='Identifier'])
def test_immutable_analysis_storage_raw_update_delete_replace(api,table):
    client,engine=api;a,b=create(client),create(client);profile(client,a);profile(client,b)
    run=related(client,a,b);link=run['links'][0]
    ok(client.post(N+'/links/'+link['id']+'/reviews',json={'expected_sequence':0,'status':'RELEVANT','rationale':'Test fixture review'}))
    graph=ok(client.post(N+'/nexus',json={'case_ids':[a['id'],b['id']]}));ok(client.post(N+'/priority',json={'nexus_id':graph['id']}))
    with engine.connect() as c:identifier=c.exec_driver_sql('SELECT id FROM '+table+' LIMIT 1').scalar()
    assert identifier
    for sql in ['UPDATE '+table+' SET record=record WHERE id=:id','DELETE FROM '+table+' WHERE id=:id','INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table+' WHERE id=:id']:
        with pytest.raises(IntegrityError,match='immutable'):
            with engine.begin() as c:c.execute(text(sql),{'id':identifier})

def test_populated_downgrade_refused(api,monkeypatch):
    client,engine=api;profile(client,create(client));cfg=config(str(engine.url),monkeypatch)
    with pytest.raises(RuntimeError,match='Retained narcotics'):command.downgrade(cfg,PARENT)
    with engine.connect() as c:assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()==REVISION
