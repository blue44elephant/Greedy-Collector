"""OSINT-2 isolated browser fixture, imported only by its test launcher."""
import os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
assert Path.cwd().resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///'+(Path.cwd()/'osint2.db').as_posix()
os.environ['GREEDY_COLLECTOR_GRAPH_BACKEND']='sqlite'
os.environ['DISCOVERY_GITHUB_TOKEN']=''
os.environ['ALCHEMY_API_KEY']=''
os.environ['BRAVE_SEARCH_API_KEY']='osint2-browser-only'
os.environ['BRAVE_SEARCH_STORAGE_ALLOWED']='true'
from alembic import command
from alembic.config import Config
cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'));command.upgrade(cfg,'head')
import main,httpx
from unittest.mock import AsyncMock
from sqlalchemy import select,func
from greedy_collector.database import SessionLocal
from greedy_collector.models import Base,Case
from greedy_collector.chains import BitcoinAdapter
from greedy_collector.attribution.service import AttributionService
from greedy_collector.discovery.broad import providers as p
BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
BitcoinAdapter.lookup_address=AsyncMock(return_value={'balance_native':'1','source_api':'test-only'})
BitcoinAdapter.transactions=AsyncMock(return_value=[])
with SessionLocal() as db:
    svc=AttributionService(db);entity=svc.create_entity({'canonical_name':'Explicit test analyst entity'})
    claim=svc.create_claim({'entity_id':entity['id'],'chain':'bitcoin','subject_ref':BTC,'relationship':'operated_by','scope_note':'Test analyst claim, not inferred'})
    db.add(Case(id='osint2-case',title='OSINT-2 historical run'));db.commit()
def deny(*a,**k):raise AssertionError('Live external request forbidden')
httpx.AsyncHTTPTransport.handle_async_request=deny;httpx.HTTPTransport.handle_request=deny
import requests
requests.Session.request=deny
calls=[]
def handler(request):
    calls.append(str(request.url))
    assert request.url.host=='api.search.brave.com'
    return httpx.Response(200,json={'web':{'results':[
      {'url':'https://www.justice.gov/osint2-fixture','title':'Fixture public notice','description':BTC+'; alias: vendor123; entity: Example Service;'},
      {'url':'https://example.org/unrelated','title':'Fuzzy fixture','description':'No wallet token present'},
      {'url':'http://testhidden.onion/source','title':'Inert citation fixture','description':BTC}
    ]},'query':{'more_results_available':False}})
actual=httpx.AsyncClient
p.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)
main.start_monitoring=lambda:None;main.stop_monitoring=lambda:None
@main.app.get('/test-osint2-state')
def state():
    with SessionLocal() as db:
        counts={n:db.scalar(select(func.count()).select_from(t)) for n,t in Base.metadata.tables.items() if not n.startswith('discovery_')}
    return {'calls':calls,'counts':counts}
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
