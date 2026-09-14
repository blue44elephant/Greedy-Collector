"""A valid successor must retain Attribution eligibility, without trusting stamps alone."""
from pathlib import Path
import shutil
import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base
from greedy_collector.attribution.service import AttributionService
from greedy_collector.attribution.domain import SchemaUnavailable
import greedy_collector.attribution.service as module


@pytest.mark.parametrize('revision,accepted',[
    ('20260912_01',True),('test_successor',True),('20260630_01',False),
    ('test_unrelated',False),('not_a_revision',False),('',False),
])
def test_attribution_revision_ancestry(tmp_path,monkeypatch,revision,accepted):
    scripts=tmp_path/'migrations';shutil.copytree(Path(__file__).resolve().parents[1]/'migrations',scripts)
    (scripts/'versions'/'test_successor.py').write_text("revision='test_successor'\ndown_revision='20260912_01'\n",encoding='utf-8')
    (scripts/'versions'/'test_unrelated.py').write_text("revision='test_unrelated'\ndown_revision=None\n",encoding='utf-8')
    monkeypatch.setattr(module,'migration_scripts',lambda:ScriptDirectory(str(scripts)),raising=False)
    engine=create_fk_enabled_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        if revision:c.execute(text('INSERT INTO alembic_version VALUES (:revision)'),{'revision':revision})
    try:
        with Session(engine) as db:
            if accepted:assert AttributionService(db).list_entities()['total']==0
            else:
                with pytest.raises(SchemaUnavailable):AttributionService(db)
    finally:engine.dispose()
