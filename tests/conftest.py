# Select isolation before collection imports settings, engines or application lifespan.
import os
import tempfile
from pathlib import Path
from sqlalchemy import event
from sqlalchemy.engine import Engine

os.environ['PYTHON_DOTENV_DISABLED']='1'
_test_root=Path(tempfile.mkdtemp(prefix='gc-pytest-')).resolve()
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///'+(_test_root/'startup.db').as_posix()

@event.listens_for(Engine,'do_connect')
def _isolated_sqlite_only(dialect,connection_record,args,kwargs):
    if dialect.name!='sqlite':raise AssertionError('Tests require isolated SQLite')
    database=str(args[0]) if args else ''
    if database in ('',':memory:'):return
    # The suite uses pytest tmp_path or an explicit tempfile directory. Fail
    # before DBAPI connect can open an operator database, even after overrides.
    candidate=Path(database).resolve()
    if not candidate.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise AssertionError('Tests must not open a database outside temporary storage')

"""pytest configuration for Greedy Collector tests."""

import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


def pytest_configure(config):
    """Configure pytest for async support."""
    # Allow asyncio mode to auto
    if not hasattr(config.option, 'asyncio_mode'):
        config.option.asyncio_mode = 'auto'
