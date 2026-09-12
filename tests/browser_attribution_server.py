"""Isolated AT-3 browser server. No production seed data or real provider access."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
work=Path.cwd().resolve()
if not work.name.startswith('gc-attribution-browser-') or work==ROOT:
    raise RuntimeError('Run only through the isolated attribution browser harness')
sys.path.insert(0,str(ROOT))
os.environ.update(PYTHON_DOTENV_DISABLED='1', GREEDY_COLLECTOR_DATABASE_URL='sqlite:///'+(work/'attribution-test.db').as_posix(),
                  GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite', GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler')
for key in ['ETHERSCAN_API_KEY','ALCHEMY_API_KEY','OPENSANCTIONS_API_KEY','VIRUSTOTAL_API_KEY','URLSCAN_API_KEY']:
    os.environ[key]='at3-browser-test-secret'

if sys.argv[2]=='migrated':
    from alembic import command
    from alembic.config import Config
    cfg=Config(str(ROOT/'alembic.ini'))
    cfg.set_main_option('script_location',str(ROOT/'migrations'))
    command.upgrade(cfg,'20260912_01')

import httpx
import requests
def blocked(*args,**kwargs):
    (work/'external-request-attempted').write_text('External HTTP was attempted')
    raise AssertionError('No external provider or evidence URL retrieval is allowed')
httpx.Client.request=blocked
httpx.AsyncClient.request=blocked
requests.Session.request=blocked

import main
import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
