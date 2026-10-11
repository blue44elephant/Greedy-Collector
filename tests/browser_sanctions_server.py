"""Test-only SANC-1 browser server: isolated SQLite, fixture OFAC, no external I/O."""
import os,sys,tempfile
from pathlib import Path
work=Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///'+(work/'sanc1.db').as_posix()
os.environ['GREEDY_COLLECTOR_GRAPH_BACKEND']='sqlite'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests,httpx,uvicorn,importlib
import main
from greedy_collector.database import engine
from greedy_collector.models import Base
from greedy_collector.sanctions.ofac import OfacSdnSource,SanctionsError,parse_sdn_xml
from tests.test_sanctions_registry import source
from greedy_collector.sanctions.service import SanctionsRegistry

Base.metadata.create_all(engine)
main.start_monitoring=lambda:None
main.stop_monitoring=lambda:None

def blocked(*args,**kwargs):raise AssertionError('External request during browser fixture')
requests.Session.request=blocked
httpx.AsyncHTTPTransport.handle_async_request=blocked
httpx.HTTPTransport.handle_request=blocked
A='0x'+'a'*40
B='0x'+'b'*40
first=source([(1,'Fixture Entity A',['CYBER2','SDGT'],[('ETH',A),('ETH',B)]),
              (2,'Fixture Entity B',['CYBER2'],[('ETH',A)])])
second=source([(1,'Fixture Entity A',['CYBER2','SDGT'],[('ETH',B)])])
state={'calls':0}
def fetch(self):
    state['calls']+=1
    if state['calls']==1:return first,None
    if state['calls']==2:return second,None
    raise SanctionsError('network_error')
OfacSdnSource.fetch=fetch
OfacSdnSource.parse=lambda self,data:parse_sdn_xml(data,minimum_entities=1)
router=importlib.import_module('greedy_collector.router')
actual=router.service.lookup_address
async def wallet(db,payload):
    return await actual(db,payload,profile_override={'balance_native':'0','source_api':'test_fixture'},transactions_override=[])
router.service.lookup_address=wallet

if __name__=='__main__':uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
