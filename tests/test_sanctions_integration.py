"""SANC-1 routes, Discovery, migration and wallet contracts use test-only OFAC data."""
from io import StringIO
from pathlib import Path
import asyncio
from fastapi.testclient import TestClient
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect,select,func
from sqlalchemy.orm import sessionmaker
import main
from greedy_collector.database import get_db,create_fk_enabled_engine
from greedy_collector.models import Base,Label,RiskResult,SanctionsSnapshot
from greedy_collector.sanctions.service import SanctionsRegistry
from greedy_collector.sanctions import router as sanctions_router
from greedy_collector.schemas import LookupRequest
from greedy_collector.services import GreedyCollectorService
from tests.test_sanctions_registry import FixtureSource,source,ETH
from tests.test_discovery_execution import h
from tests.test_discovery_local_manual import live,run

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def api_db(tmp_path,monkeypatch):
    engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'api.db').as_posix())
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    def db():
        with sessions() as session:yield session
    old=main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db]=db
    fixture=FixtureSource(source())
    monkeypatch.setattr(sanctions_router,'SanctionsRegistry',lambda session:SanctionsRegistry(session,fixture))
    try:
        with TestClient(main.app) as client:yield client,sessions,fixture
    finally:
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(old)
        engine.dispose()

def test_api_sync_search_screen_entity_and_failure(api_db):
    client,sessions,fixture=api_db
    assert client.get('/api/greedy-collector/sanctions/status').json()['snapshot'] is None
    unavailable=client.get('/api/greedy-collector/sanctions/screen/ethereum/'+ETH).json()
    assert unavailable['listing_state']=='REGISTRY_NOT_SYNCED'
    fresh=client.post('/api/greedy-collector/sanctions/sync')
    assert fresh.status_code==200 and fresh.json()['snapshot']['identifier_count']==5
    summary=client.get('/api/greedy-collector/sanctions/summary').json()
    assert summary['by_asset']['ETH']==2 and summary['unresolved_count']==2
    hits=client.get('/api/greedy-collector/sanctions/search',params={'q':ETH}).json()
    assert hits['total']==3
    entity=client.get('/api/greedy-collector/sanctions/entities/1').json()
    assert entity['entity']['name']=='Listed One' and len(entity['identifiers'])==3
    assert client.get('/api/greedy-collector/sanctions/search',params={'program':'CYBER'}).json()['total']==0
    assert client.get('/api/greedy-collector/sanctions/search',params={'program':'CYBER2'}).json()['total']==5
    assert client.get('/api/greedy-collector/sanctions/search',params={'q':'Alias 1'}).json()['total']==3
    fixture.fail='timeout'
    assert client.post('/api/greedy-collector/sanctions/sync').status_code==502
    assert client.get('/api/greedy-collector/sanctions/status').json()['snapshot']['id']==fresh.json()['snapshot']['id']


def test_historical_search_opens_immutable_entity_snapshot(api_db):
    client,_,fixture=api_db
    first=client.post('/api/greedy-collector/sanctions/sync').json()['snapshot']
    fixture.data=source([(3,'Replacement',['CYBER2'],[('ETH','0x'+'cd'*20)])])
    assert client.post('/api/greedy-collector/sanctions/sync').status_code==200
    historical=client.get('/api/greedy-collector/sanctions/search',params={'q':ETH,'state':'historical'}).json()
    assert historical['total']==3
    item=historical['items'][0]
    assert item['snapshot']['id']==first['id']
    detail=client.get('/api/greedy-collector/sanctions/entities/'+item['entity']['source_entity_id'],
                      params={'snapshot_id':item['snapshot']['id']})
    assert detail.status_code==200
    assert detail.json()['snapshot']['id']==first['id']
    assert client.get('/api/greedy-collector/sanctions/entities/'+item['entity']['source_entity_id']).status_code==404

def test_wallet_service_screen_separate_from_risk(api_db):
    _,sessions,fixture=api_db
    with sessions() as db:
        SanctionsRegistry(db,fixture).sync()
        service=GreedyCollectorService()
        response=asyncio.run(service.lookup_address(db,LookupRequest(chain='ethereum',address=ETH),
            profile_override={'balance_native':'0','source_api':'test-only'},transactions_override=[]))
        assert response['sanctions_screening']['match_type']=='DIRECT_CHAIN_MATCH'
        assert response['sanctions_screening']['listing_state']=='CURRENTLY_LISTED'
        assert response['risk']['score']<100
        assert db.scalar(select(func.count()).select_from(Label))==0

def test_discovery_local_ofac_provenance_and_zero_transport(live):
    client,h,_=live
    fixture=FixtureSource(source())
    with h.sessions() as db:SanctionsRegistry(db,fixture).sync()
    row,items=run(client,transforms=('wallet.ofac_sdn_match',))
    assert row['status']=='completed' and len(items)==3,(row['sources'][0]['status'],row['sources'][0]['error_code'])
    assert row['sources'][0]['requests_attempted']==0
    from tests.test_discovery_api import ok,PREFIX
    observation=ok(client.get(PREFIX+'/observations/'+items[0]['observation']['id']))
    snapshot=observation['source_snapshot']
    assert snapshot['source_id']=='ofac_sdn' and snapshot['snapshot_sha256']
    assert snapshot['match_type']=='DIRECT_CHAIN_MATCH'
    assert snapshot['entity']['source_entity_id'] in ('1','2')
    with h.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Label))==0
        assert db.scalar(select(func.count()).select_from(RiskResult))==0

def test_migration_head_on_temporary_database(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'migration.db').as_posix()
    monkeypatch.setenv('GREEDY_COLLECTOR_DATABASE_URL',url)
    cfg=Config(str(ROOT/'alembic.ini'),stdout=StringIO())
    cfg.set_main_option('script_location',str(ROOT/'migrations'))
    command.upgrade(cfg,'head')
    engine=create_fk_enabled_engine(url)
    names=set(inspect(engine).get_table_names())
    assert {'sanctions_snapshots','sanctions_identifiers','sanctions_entities','sanctions_registry_state',
            'sanctions_case_pins','sanctions_sync_events'} <= names
    engine.dispose()
