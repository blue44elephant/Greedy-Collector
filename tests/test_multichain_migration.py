"""MC-1 migrations exercise temporary SQLite only."""
import hashlib
from pathlib import Path
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from greedy_collector.models import Base,Address,Transaction,WatchlistWallet,Label,AttributionClaim,DiscoverySubject
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.attribution.service import AttributionService
from greedy_collector.discovery.service import DiscoveryService
from tests.test_discovery_ens_migration import database,snapshot,triggers,seed_history
from tests.test_discovery_promotion_migration import signature

HEAD='20260923_01'
PARENT='20260922_02'

def test_mc1_upgrade_preserves_rows_triggers_and_unrelated_constraints(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,PARENT)
    try:
        seed_history(engine)
        with Session(engine) as db:
            for chain,address in [('bitcoin','1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'),('ethereum','0x'+'ab'*20)]:
                db.add(Address(chain=chain,address=address,balance_native='0.000001'))
                db.add(WatchlistWallet(chain=chain,address=address))
                db.execute(text("INSERT INTO transactions (id,tx_hash,chain,from_address,to_address,value_native,value_usd,token_symbol,timestamp,block_number,fee,direction,source_api,raw_payload) VALUES (:id,:hash,:chain,:address,'','1',NULL,'',NULL,'','0','unknown','test','{}')"),
                    {'id':'transaction-'+chain,'hash':'a'*64,'chain':chain,'address':address})
                db.add(Label(chain=chain,address=address,label='Test migration',type='Unknown',source='test'))
            db.commit()
            service=AttributionService(db);entity=service.create_entity({'canonical_name':'Migration BTC'})
            service.create_claim(dict(entity_id=entity['id'],chain='bitcoin',subject_ref='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa',relationship='operated_by',scope_note='Test'))
            DiscoveryService(db).get_or_create_subject('blockchain_address','bitcoin','1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa')
        before=snapshot(engine);protected=triggers(engine)
        old={t:signature(engine,t) for t in Base.metadata.tables}
        command.upgrade(cfg,HEAD)
        assert snapshot(engine)==before and triggers(engine)==protected
        from tests.multichain_migration_helpers import before_mc1
        for table,expected in old.items():assert before_mc1(signature(engine,table))==expected
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before and triggers(engine)==protected
        command.upgrade(cfg,HEAD)
        assert snapshot(engine)==before
    finally:engine.dispose()

def test_mc1_head_matches_models(tmp_path,monkeypatch):
    cfg,engine=database(tmp_path,monkeypatch,HEAD);orm=create_fk_enabled_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(orm)
        for table in Base.metadata.tables:
            if table.startswith(('attribution_','discovery_')):assert signature(engine,table)==signature(orm,table),table
        assert triggers(engine)==triggers(orm)
        assert ScriptDirectory.from_config(cfg).get_heads()==['20260929_01_public_source_capture']
    finally:engine.dispose();orm.dispose()

@pytest.mark.parametrize('chain',['test_chain','a','chain_123'])
def test_mc1_future_chain_storage_and_guarded_downgrade(tmp_path,monkeypatch,chain):
    cfg,engine=database(tmp_path,monkeypatch,HEAD)
    try:
        with Session(engine) as db:
            service=AttributionService(db);entity=service.create_entity({'canonical_name':'Test'})
            db.add(AttributionClaim(entity_id=entity['id'],subject_type='wallet',chain=chain,subject_ref='TestAddress',relationship='operated_by',scope_note='Test',created_by='test'))
            db.add(DiscoverySubject(kind='blockchain_address',namespace=chain,canonical_value='TestAddress',display_value='TestAddress',normalization_version=1,identity_sha256='1'*64))
            db.commit()
        before=snapshot(engine)
        with pytest.raises(RuntimeError,match='retained'):command.downgrade(cfg,PARENT)
        assert snapshot(engine)==before
        with engine.connect() as c:assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    finally:engine.dispose()

@pytest.mark.parametrize('chain',['','BadChain','bad-chain','x'*33,'has space','1number','a.b'])
def test_mc1_structural_constraint_rejects_bad_ids(tmp_path,monkeypatch,chain):
    cfg,engine=database(tmp_path,monkeypatch,HEAD)
    try:
        with Session(engine) as db:
            db.add(DiscoverySubject(kind='blockchain_address',namespace=chain,canonical_value='x',display_value='x',normalization_version=1,identity_sha256='1'*64))
            with pytest.raises(IntegrityError):db.commit()
            db.rollback()
    finally:engine.dispose()


def test_previous_migrations_byte_identical():
    root=Path(__file__).resolve().parents[1]/'migrations'/'versions'
    expected={'20260630_01_greedy_collector.py': '557d047f3ebdd50c2c8fbc21d5da1319149674bd65875429a7b6bf014de3b782', '20260912_01_attribution.py': 'ee709c59f5520f03eaa38b4af010f1286436f03d3885e6ed62eb7f7193ebfcb8', '20260913_01_discovery.py': 'bb8cd33e2a91cfa5b9cbb90428bf18b6dd0ee8623bf916a13a8e7ffdcc6eb2ec', '20260915_01_discovery_promotions.py': 'daec59aa4f49b79081f64bd79b5b6072d0f71a91864921fecbc0605e0bb84ece', '20260916_01_discovery_ens_endpoints.py': '92f1a54a60748d522b8a7bcee3db136ed8ecfcff822bb9fd472a33b292c62e97', '20260922_01_manual_source_observation.py': '816a8a8327c0418e08374c8a194de88495d1fbbb76028e7c1830dff196959e58', '20260922_02_graphsense_public_tags.py': 'f511c010629ffb6560865fa4e0aa92651fbcd8317dd689b5ec7777b9e46c4cab'}
    assert {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in expected}==expected
