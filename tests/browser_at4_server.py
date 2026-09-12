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
# Explicit test-only stored blockchain fixtures; no provider request is needed.
from greedy_collector.database import SessionLocal
from greedy_collector.models import Address, Transaction, Label, RiskResult
address='0x'+'ab'*20
other='0x'+'2'*40
third='0x'+'3'*40
with SessionLocal() as db:
    db.add(Address(chain='ethereum',address=address,balance_native='7',risk_score=9,risk_level='Low'))
    db.add(RiskResult(chain='ethereum',address=address,score=9,level='Low',findings=[]))
    db.add(Label(chain='ethereum',address=address,label='Synthetic annotation only',type='Exchange',source='Test fixture',confidence=0.7))
    for index,(source,target) in enumerate([(address,other),(other,third)]):
        db.add(Transaction(chain='ethereum',tx_hash=str(index)*64,from_address=source,to_address=target,value_native='1',token_symbol='ETH',source_api='test-only'))
    db.commit()
import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
