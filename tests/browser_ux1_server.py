"""UX-1 isolated browser fixture. No live collection; production never imports this file."""
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['DISCOVERY_GITHUB_TOKEN']=''
os.environ['ALCHEMY_API_KEY']=''
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///'+(Path.cwd()/'flow-browser.db').as_posix()
os.environ['GREEDY_COLLECTOR_GRAPH_BACKEND']='sqlite'
from alembic import command
from alembic.config import Config
cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'));command.upgrade(cfg,'head')
import main
import httpx
from greedy_collector.database import SessionLocal
from greedy_collector.models import Case,Label
from greedy_collector.chains import get_chain
from greedy_collector.transaction_identity import persist_normalized_event
from tests.test_fund_flow import event,A,B,C,D,TOKEN
from tests.test_clustering import raw,address
with SessionLocal() as db:
    event(db,A,B,value='10');event(db,B,C,value='4',number=2,second=2)
    event(db,A,B,value='2',number=3,second=1);event(db,D,A,value='3',number=4)
    event(db,A,B,value='100',number=5,second=2,token=TOKEN);event(db,B,C,value='80',number=6,second=3,token=TOKEN)
    db.add(Label(chain='ethereum',address=C,label='Fixture exchange',type='Exchange',source='test-only'))
    db.add(Case(id='fl1-browser-case',title='FL-1 pinned run'));db.commit()
    for chain in ['bitcoin','litecoin']:
        a,b,c=[address(n,chain) for n in [1,2,3]]
        payload=raw([a,b],10,[{'scriptpubkey_address':c,'value':199000}])
        persist_normalized_event(db,get_chain(chain).adapter()._normalize(payload,a,'test-only'));db.commit()
def deny(*args,**kwargs):raise AssertionError('No live provider calls allowed')
httpx.AsyncHTTPTransport.handle_async_request=deny;httpx.HTTPTransport.handle_request=deny
main.start_monitoring=lambda:None;main.stop_monitoring=lambda:None
async def nothing(*args):pass

if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
