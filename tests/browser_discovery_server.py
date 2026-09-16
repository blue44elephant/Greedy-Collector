"""Isolated ED-3 browser server. Test bindings never enter production startup."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
work=Path.cwd().resolve()
if not work.name.startswith('gc-discovery-browser-') or work==ROOT:
    raise RuntimeError('Use the isolated Discovery browser harness')
sys.path.insert(0,str(ROOT))
os.environ.update(PYTHON_DOTENV_DISABLED='1',GREEDY_COLLECTOR_DATABASE_URL='sqlite:///'+(work/'discovery-test.db').as_posix(),GREEDY_COLLECTOR_GRAPH_BACKEND='sqlite',GREEDY_COLLECTOR_MONITORING_BACKEND='apscheduler',DISCOVERY_GITHUB_TOKEN='ed3-test-only-secret')
mode=sys.argv[2]
if mode in ('production','unmigrated','handoff','handoff_unmigrated','promotion_partial','promotion_unmigrated'):os.environ.pop('DISCOVERY_GITHUB_TOKEN',None)
if mode not in ('production','executor','unmigrated','github','handoff','handoff_github','handoff_unmigrated','promotion','promotion_partial','promotion_unmigrated','graph','graph_partial','graph_unmigrated'):raise RuntimeError('Unknown test mode')
if mode not in ('unmigrated','handoff_unmigrated','promotion_unmigrated','graph_unmigrated'):
    from alembic import command
    from alembic.config import Config
    cfg=Config(str(ROOT/'alembic.ini'));cfg.set_main_option('script_location',str(ROOT/'migrations'))
    command.upgrade(cfg,'20260915_01' if mode in ('promotion','graph') else '20260913_01')

import httpx
import requests
def blocked(*args,**kwargs):
    (work/'external-request-attempted').write_text('External HTTP was attempted')
    raise AssertionError('No external request is permitted in ED-3 tests')
httpx.HTTPTransport.handle_request=blocked
httpx.AsyncHTTPTransport.handle_async_request=blocked
httpx.Client.request=blocked
httpx.AsyncClient.request=blocked
requests.Session.request=blocked

if mode in ('github','handoff_github','promotion','graph','graph_partial'):
    from tests.browser_discovery_github_transport import install
    install(work)

import main
if mode.startswith('handoff'):
    from tests.browser_discovery_handoff_fixture import install
    main.start_monitoring=lambda:None
    main.stop_monitoring=lambda:None
    install(main.app,work)
if mode=='executor':
    import asyncio
    from datetime import datetime,timezone
    from greedy_collector.discovery.registry import REGISTRY,Registry
    from greedy_collector.discovery.executors import ExecutorRegistry,Binding,QuotaPolicy,ExecutionSignal
    from greedy_collector.discovery.runtime import DiscoveryRuntime
    from greedy_collector.database import SessionLocal

    class BrowserExecutor:
        def __init__(self,fail=False):self.calls=0;self.fail=fail
        async def execute(self,context):
            self.calls+=1
            async def operation():
                await asyncio.sleep(2)
                if self.fail:raise ExecutionSignal('transport_failed')
            await context.request(operation)
            (work/('failure-count' if self.fail else 'execution-count')).write_text(str(self.calls))
            return {'records':[{'kind':'candidate_relationship','predicate':'repository_contains',
                'from':{'kind':'repository','namespace':'github','value':'123'},
                'to':{'kind':'blockchain_address','namespace':context.subject['namespace'],'value':context.subject['canonical_value']},
                'fact_key':{'path':'README.md'},
                'observation':{'kind':'code_search_result','source_record_key':'test-record',
                    'source_url':'https://example.invalid/test-only','title':'Synthetic browser reference',
                    'summary':f'Synthetic observation revision {self.calls}', 'retrieved_at':datetime.now(timezone.utc),
                    'source_snapshot':{'public':True,'revision':self.calls,'test_only':True}}}]}

    sources=[];transforms=[]
    for sid in ('test_success','test_failure'):
        source=REGISTRY.sources['github'].model_dump();source.update(id=sid,display_name=sid,credential_env=None,storage_allowed=True,rate_limit_per_minute=100)
        sources.append(source)
        transform=REGISTRY.transforms['wallet.public_code_mentions'].model_dump();transform.update(id='wallet.'+sid,display_name='Synthetic '+sid,source_ids=(sid,))
        transforms.append(transform)
    registry=Registry(sources,transforms);executors=ExecutorRegistry(registry)
    for sid in ('test_success','test_failure'):
        executors.register(Binding('wallet.'+sid,sid,1,1,BrowserExecutor(sid=='test_failure'),QuotaPolicy(daily_units=1000,monthly_units=30000)))
    async def start_test_discovery(app):
        main.app.state.discovery=DiscoveryRuntime(SessionLocal,executors)
        await main.app.state.discovery.start()
    main.start_discovery=start_test_discovery

import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
