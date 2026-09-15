"""ED-6 isolated migration parity, retained history and partial revision behavior."""
from pathlib import Path
import hashlib
import subprocess
import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, DiscoveryPromotion, PROMOTION_TRIGGER_SQL, ATTRIBUTION_TRIGGER_SQL
from greedy_collector.attribution.service import AttributionService
from greedy_collector.attribution.domain import SchemaUnavailable as AttributionUnavailable
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.domain import SchemaUnavailable as DiscoveryUnavailable
from greedy_collector.discovery.promotion import PromotionService, PromotionUnavailable, REVISION
from tests.test_attribution_migration import config, schema

ROOT=Path(__file__).resolve().parents[1]
PARENT='20260913_01'
ETH='0x'+'ab'*20
def signature(engine,table):
    view=inspect(engine)
    return {
        'columns':[(c['name'],str(c['type']),c['nullable'],c['default']) for c in view.get_columns(table)],
        'pk':view.get_pk_constraint(table),
        'indexes':sorted((r['name'],r['column_names'],r['unique']) for r in view.get_indexes(table)),
        'unique':sorted((r['name'],r['column_names']) for r in view.get_unique_constraints(table)),
        'checks':sorted((r['name'],r['sqltext']) for r in view.get_check_constraints(table)),
        'fk':sorted((r['name'],r['constrained_columns'],r['referred_table'],r['referred_columns'],r['options']) for r in view.get_foreign_keys(table)),
    }

def test_clean_ed6_head_full_schema_equivalence(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'migrate.db').as_posix();cfg=config(url,monkeypatch);command.upgrade(cfg,'head')
    engine=create_fk_enabled_engine(url);orm=create_fk_enabled_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(orm)
        for table in ('discovery_promotions','attribution_evidence'):assert signature(engine,table)==signature(orm,table)
        for db in (engine,orm):
            with db.connect() as c:
                installed=dict(c.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").all())
                for name,sql in {**ATTRIBUTION_TRIGGER_SQL,**PROMOTION_TRIGGER_SQL}.items():assert installed[name]==sql
                assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
                assert c.exec_driver_sql('SELECT count(*) FROM discovery_promotions').scalar_one()==0
        with Session(engine) as db:
            assert AttributionService(db).list_entities()['total']==0
            assert DiscoveryService(db).list_runs()['total']==0
            PromotionService(db)
    finally:engine.dispose();orm.dispose()

@pytest.mark.parametrize('revision',['20260630_01','20260912_01',PARENT,REVISION])
def test_partial_revisions_preserve_applicable_services_and_no_auto_migration(tmp_path,monkeypatch,revision):
    url='sqlite:///'+(tmp_path/'partial.db').as_posix();cfg=config(url,monkeypatch);command.upgrade(cfg,revision)
    engine=create_fk_enabled_engine(url)
    try:
        with Session(engine) as db:
            if revision=='20260630_01':
                with pytest.raises(AttributionUnavailable):AttributionService(db)
            else:
                at=AttributionService(db);entity=at.create_entity({'canonical_name':'Test explicit entity'})
                claim=at.create_claim({'entity_id':entity['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'operated_by','scope_note':'Test explicit scope'})
                evidence=at.create_and_link_evidence(claim['id'],{'evidence_type':'analyst_observation','origin':'analyst_added','title':'Test capture','summary':'Test historical material','source_name':'Test analyst','analyst_note':'Test context'},
                    {'stance':'context','directness':'context','rationale':'Test context'},expected_version=1)
                assert at.get_evidence(evidence['link']['evidence_id'])['origin_discovery_observation_id'] is None
                page=at.list_evidence(limit=1)
                assert page['total']==1 and page['items'][0]['id']==evidence['link']['evidence_id']
            if revision in (PARENT,REVISION):assert DiscoveryService(db).list_runs()['total']==0
            else:
                with pytest.raises(DiscoveryUnavailable):DiscoveryService(db)
            if revision==REVISION:PromotionService(db)
            else:
                with pytest.raises(PromotionUnavailable):PromotionService(db)
        with engine.connect() as c:assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()==revision
    finally:engine.dispose()

def test_upgrade_retains_populated_evidence_links_events_and_all_triggers(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'retained.db').as_posix();cfg=config(url,monkeypatch);command.upgrade(cfg,PARENT)
    engine=create_fk_enabled_engine(url)
    with Session(engine) as db:
        at=AttributionService(db);e=at.create_entity({'canonical_name':'Test retained entity'})
        claim=at.create_claim({'entity_id':e['id'],'chain':'ethereum','subject_ref':ETH,'relationship':'controlled_by','scope_note':'Test scope'})
        capture=at.create_and_link_evidence(claim['id'],{'evidence_type':'analyst_observation','origin':'analyst_added','title':'Test immutable capture','summary':'Must survive migration','source_name':'Test analyst','analyst_note':'Test context'},
            {'stance':'contradicts','directness':'indirect','rationale':'Test contradiction'},expected_version=1)
    tables=('attribution_evidence','attribution_claims','attribution_claim_evidence','attribution_events')
    with engine.connect() as c:
        before={t:c.exec_driver_sql('SELECT * FROM '+t).all() for t in tables}
        columns={t:[r['name'] for r in inspect(c).get_columns(t)] for t in tables}
    command.upgrade(cfg,REVISION)
    with engine.connect() as c:
        for table in tables:assert c.exec_driver_sql('SELECT '+','.join(columns[table])+' FROM '+table).all()==before[table]
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert len(c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'").all())==19
    # A migration back with no ED-6 captures retains previous history as well.
    command.downgrade(cfg,PARENT)
    with engine.connect() as c:
        for table in tables:assert c.exec_driver_sql('SELECT * FROM '+table).all()==before[table]
    engine.dispose()

def test_prior_migrations_unchanged():
    for name in ('20260630_01_greedy_collector.py','20260912_01_attribution.py','20260913_01_discovery.py'):
        path='migrations/versions/'+name
        original=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True,check=True).stdout
        assert (ROOT/path).read_bytes().replace(b'\r\n',b'\n')==original.replace(b'\r\n',b'\n')
