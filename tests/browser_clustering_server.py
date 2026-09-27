"""CL-1 test-only browser server: isolated DB, deterministic providers, no live traffic."""
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///'+(Path.cwd()/'clustering-browser.db').as_posix()
os.environ['GREEDY_COLLECTOR_GRAPH_BACKEND']='sqlite'
from alembic import command
from alembic.config import Config
cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'))
command.upgrade(cfg,'head')
import main
import httpx
from unittest.mock import AsyncMock
from greedy_collector.database import SessionLocal
from greedy_collector.models import Case
from greedy_collector.chains import BitcoinAdapter, LitecoinAdapter
from tests.test_clustering import address, raw, store
A='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
B='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
C=address(3)
LA,LB=address(1,'litecoin'),address(2,'litecoin')
payloads={
    'bitcoin':[raw([A,B],1,[{'value':199000,'scriptpubkey_address':B}]),raw([B,C],2,[{'value':199000,'scriptpubkey_address':C}])],
    'litecoin':[raw([LA,LB],3)]}
with SessionLocal() as db:
    for chain,rows in payloads.items():
        for row in rows:store(db,[row['vin'][0]['prevout']['scriptpubkey_address']],chain=chain,payload=row)
    db.add(Case(id='cl1-browser-case',title='CL-1 pinned evidence'));db.commit()
for cls in (BitcoinAdapter,LitecoinAdapter):
    chain=cls().chain
    async def profile(address, chain=chain):return {'balance_native':'0','source_api':'test-only'}
    async def transactions(address, chain=chain, cls=cls):return [cls()._normalize(row,address,'test-only') for row in payloads[chain]]
    cls.lookup_address=staticmethod(profile);cls.transactions=staticmethod(transactions)
def deny(*args,**kwargs):raise AssertionError('Live provider traffic is forbidden in browser verification')
httpx.AsyncHTTPTransport.handle_async_request=deny
httpx.HTTPTransport.handle_request=deny
main.start_monitoring=lambda:None
main.stop_monitoring=lambda:None
async def nothing(*args):pass
main.start_discovery=nothing;main.stop_discovery=nothing
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
