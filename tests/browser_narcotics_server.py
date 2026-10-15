"""NARC-1 browser-only server: temporary migrated DB, no provider transport."""
import os
import sys
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];work=Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve())
sys.path.insert(0,str(root))
os.environ.update(PYTHON_DOTENV_DISABLED='1',GREEDY_COLLECTOR_DATABASE_URL='sqlite:///'+(work/'narcotics.db').as_posix(),GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite')
from alembic import command
from alembic.config import Config
cfg=Config(str(root/'alembic.ini'));cfg.set_main_option('script_location',str(root/'migrations'));command.upgrade(cfg,'head')
import httpx,requests,main
from sqlalchemy import text
from greedy_collector.database import engine
main.start_monitoring=lambda:None
main.stop_monitoring=lambda:None
def blocked(*args,**kwargs):
    (work/'external-request-attempted').write_text('External request attempted')
    raise AssertionError('NARC-1 must not request external providers')
httpx.HTTPTransport.handle_request=blocked
httpx.AsyncHTTPTransport.handle_async_request=blocked
requests.Session.request=blocked
@main.app.get('/test-narcotics-counts')
def counts():
    with engine.connect() as c:return {t:c.execute(text('SELECT count(*) FROM '+t)).scalar() for t in ['risk_results','attribution_claims','attribution_entities','attribution_evidence']}
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
