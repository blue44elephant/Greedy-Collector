"""AT-7 browser fixtures: real migrated temporary SQLite, no external providers."""
import os
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

root=Path(__file__).resolve().parents[1]
work=Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
sys.path.insert(0,str(root))
os.environ.update(PYTHON_DOTENV_DISABLED='1',GREEDY_COLLECTOR_DATABASE_URL='sqlite:///'+(work/'at7.db').as_posix(),
    GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite',TAVILY_KEYLESS_ENABLED='false',BRAVE_SEARCH_STORAGE_ALLOWED='true',BRAVE_SEARCH_API_KEY='at7-test-only')
from alembic import command
from alembic.config import Config
cfg=Config(str(root/'alembic.ini'));cfg.set_main_option('script_location',str(root/'migrations'));command.upgrade(cfg,'head')
import httpx
import requests
import main
from unittest.mock import AsyncMock
from sqlalchemy import select,func
from greedy_collector.database import SessionLocal
from greedy_collector.models import Base
from greedy_collector.chains import BitcoinAdapter
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.broad.providers import normalize_result,DiscoveryQuery,DiscoveryObservation
from greedy_collector.discovery.capture.service import CaptureService
from greedy_collector.discovery.capture.network import Retrieved
from greedy_collector.discovery.capture.api import ReviewInput

main.start_monitoring=lambda:None
main.stop_monitoring=lambda:None
def blocked(*args,**kwargs):
    (work/'external-request-attempted').write_text('External request attempted')
    raise AssertionError('No live provider/source requests in AT-7 browser smoke')
httpx.HTTPTransport.handle_request=blocked
httpx.AsyncHTTPTransport.handle_async_request=blocked
requests.Session.request=blocked
BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
BitcoinAdapter.lookup_address=AsyncMock(return_value={'balance_native':'0','source_api':'test-only'})
BitcoinAdapter.transactions=AsyncMock(return_value=[])

# Seed only test source material through its real storage/review paths. No Entity,
# Claim or Attribution Evidence exists before the browser explicitly creates it.
with SessionLocal() as db:
    ds=DiscoveryService(db)
    subject=ds.get_or_create_subject('blockchain_address','bitcoin',BTC)
    row=ds.create_run(subject['id'],[{'transform_id':'wallet.broad_web','source_id':'brave_search'}],idempotency_key=str(uuid4()))
    row=ds.transition_run(row['id'],'running',expected_version=row['version'])
    ds.transition_source(row['sources'][0]['id'],'running',expected_run_version=row['version'])
    row=ds.get_run(row['id'])
    record=normalize_result('brave_search',DiscoveryQuery('bitcoin',BTC),
        DiscoveryObservation('https://source.example/at7','AT7 captured fixture',BTC+' literal primary source context',1),'2026-10-12T10:00:00Z')
    batch=ds.record_batch(row['sources'][0]['id'],[record],expected_run_version=row['version'])
    cs=CaptureService(db);origin=cs.origin(batch['observation_ids'][0])
    body=(BTC+' literal primary source context').encode()
    captured=cs.store(origin,Retrieved(final_url=origin['requested_url'],http_status=200,content_type='text/plain',
        byte_count=len(body),body_sha256=sha256(body).hexdigest(),title='AT7 captured fixture',text=body.decode(),status='captured',body=body))
    cs.review(captured['id'],ReviewInput(status='relevant',note='Test analyst reviewed the preserved source',expected_version=0))

@main.app.get('/test-at7-state')
def state():
    with SessionLocal() as db:
        counts={name:db.scalar(select(func.count()).select_from(table)) for name,table in Base.metadata.tables.items()}
    return {'capture_id':captured['id'],'body_sha256':captured['body_sha256'],'counts':counts}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
