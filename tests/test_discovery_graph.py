"""ED-7 real local graph projection. Fixtures never enter production runtime."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,event,text
from sqlalchemy.orm import Session
from greedy_collector.models import DiscoveryRunSource,DiscoveryRun,Label,Base
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.discovery.graph import graph_summary
from tests.test_discovery_promotion import env,material,promote,P,counts
from tests.test_discovery import record,ETH

def run_id(env,ob):
    with env[1]() as db:return db.get(DiscoveryRunSource,ob['execution_id']).run_id
def graph(env,id,query=''):
    response=env[0].get(P+'/runs/'+id+'/graph'+query)
    assert response.status_code==200,response.text
    return response.json()

@pytest.mark.parametrize('kind,predicate,node_type',[('label','locally_labeled_as','label_annotation'),('github','repository_contains','code_location')])
def test_typed_root_result_and_literal_direction(env,kind,predicate,node_type):
    ob=material(env,kind);g=graph(env,run_id(env,ob));node=g['items'][0];edge=g['edges'][0]
    assert g['root']['type']=='wallet' and g['root']['address']==ETH.lower()
    assert node['type']==node_type and edge['predicate']==predicate
    assert edge['source']==(g['root']['id'] if kind=='label' else node['id'])
    assert edge['target']==(node['id'] if kind=='label' else g['root']['id'])
    assert node['observation_id']==ob['id'] and node['run_observation_count']==1
    assert node['current_review_status']=='relevant' and node['promotion_count']==0

def stored_run(env,records=(),manual=False):
    with env[1]() as db:
        svc=DiscoveryService(db);subject=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
        selected=[{'transform_id':'wallet.manual_exact_web','source_id':'google'}] if manual else [{'transform_id':'wallet.public_code_mentions','source_id':'github'}]
        run=svc.create_run(subject['id'],selected,idempotency_key=uuid4().hex)
        run=svc.transition_run(run['id'],'running',expected_version=run['version'])
        if not manual:
            svc.transition_source(run['sources'][0]['id'],'running',expected_run_version=run['version']);run=svc.get_run(run['id'])
        if manual:svc.transition_source(run['sources'][0]['id'],'manual_ready',expected_run_version=run['version'])
        else:svc.record_batch(run['sources'][0]['id'],list(records),expected_run_version=run['version'])
        return run['id']

@pytest.mark.parametrize('manual',[False,True])
def test_empty_and_manual_have_only_wallet(env,manual):
    g=graph(env,stored_run(env,manual=manual))
    assert g['root']['type']=='wallet' and g['items']==g['edges']==[] and g['total']==0

def test_duplicate_and_multiple_observations_one_logical_node(env):
    a=record('Test first material');b=record('Test changed material');rid=stored_run(env,[a,a,b])
    g=graph(env,rid)
    assert len(g['items'])==len(g['edges'])==1
    assert g['items'][0]['run_observation_count']==2
    assert g['items'][0]['current_observation_count']==2

def test_separate_files_and_repositories_stay_separate(env):
    rows=[]
    for repo,path in [('11','one.txt'),('11','two.txt'),('12','one.txt')]:
        item=record('Test code');item['from']['value']=repo;item['fact_key']={'path':path}
        item['observation']['source_snapshot'].update(repository_full_name='test/repo'+repo,file_path=path)
        rows.append(item)
    g=graph(env,stored_run(env,rows))
    assert len(g['items'])==3 and len({n['id'] for n in g['items']})==3
    assert all(e['predicate']=='repository_contains' for e in g['edges'])

def test_conflicting_label_rows_remain_separate(env):
    # Persist the same validated local candidate contract used by the executor.
    with env[1]() as db:
        labels=[Label(chain='ethereum',address=ETH.lower(),label=value,type='Unknown',source='Test annotation source',confidence=.5) for value in ('Test A','Test B')]
        db.add_all(labels);db.commit();ids=[r.id for r in labels]
        svc=DiscoveryService(db);s=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
        run=svc.create_run(s['id'],[{'transform_id':'wallet.local_labels','source_id':'gc_labels'}],idempotency_key=uuid4().hex)
        run=svc.transition_run(run['id'],'running',expected_version=1);svc.transition_source(run['sources'][0]['id'],'running',expected_run_version=run['version']);run=svc.get_run(run['id'])
        rows=[{'kind':'candidate_evidence','predicate':'locally_labeled_as','from':{'kind':'blockchain_address','namespace':'ethereum','value':ETH},'to':{'kind':'annotation','namespace':'gc-label','value':id},'fact_key':{'label_id':id},'observation':{'kind':'local_label_snapshot','source_record_key':id,'origin_label_id':id,'source_locator':'label:'+id,'title':'Test annotation','summary':'Test only','retrieved_at':datetime.now(timezone.utc),'source_snapshot':{'record':{'label':value}}}} for id,value in zip(ids,('Test A','Test B'))]
        svc.record_batch(run['sources'][0]['id'],rows,expected_run_version=run['version'])
    g=graph(env,run['id']);assert {n['title'] for n in g['items']}=={'Test A','Test B'}

def test_historical_material_fixed_current_status_separate(env):
    old=material(env,content='Test old');id=run_id(env,old);before=graph(env,id)
    new=material(env,content='Test new',review=None)
    after=graph(env,id);node=after['items'][0]
    assert node['observation_id']==old['id'] and node['summary']==before['items'][0]['summary']
    assert node['current_review_required'] and node['current_observation_count']==2
    assert node['run_observation_count']==1 and node['current_review_status']=='relevant'
    assert graph(env,run_id(env,new))['items'][0]['observation_id']==new['id']
    assert after['edges']==before['edges']

@pytest.mark.parametrize('status',['unreviewed','relevant','irrelevant'])
def test_review_text_is_explicit_and_irrelevant_not_hidden(env,status):
    ob=material(env,review=status);g=graph(env,run_id(env,ob))
    assert g['total']==1 and g['items'][0]['current_review_status']==status

def test_promotion_and_withdrawal_do_not_change_graph_semantics(env):
    from greedy_collector.attribution.service import AttributionService
    ob=material(env);id=run_id(env,ob);before=graph(env,id)
    saved=promote(env,ob).json();p=saved['promotion']
    with env[1]() as db:AttributionService(db).withdraw_evidence(p['claim_id'],p['link_id'],expected_version=2,reason='Test withdrawal')
    after=graph(env,id);assert after['edges']==before['edges']
    assert after['items'][0]['promotion_count']==1 and after['items'][0]['current_review_status']=='relevant'

def test_bounded_stable_pages_no_duplicates(env):
    rows=[]
    for i in range(5):
        r=record('Test bounded');r['fact_key']={'path':f'test-{i}.txt'};rows.append(r)
    id=stored_run(env,rows);a=graph(env,id,'?limit=2');b=graph(env,id,'?limit=2&offset=2')
    assert a==graph(env,id,'?limit=2') and a['total']==5 and a['next_offset']==2
    assert not {n['id'] for n in a['items']} & {n['id'] for n in b['items']}
    assert graph(env,id,'?offset=100')['items']==[]

@pytest.mark.parametrize('query',['?limit=0','?limit=101','?offset=-1'])
def test_bounds_rejected(env,query):assert env[0].get(P+'/runs/missing/graph'+query).status_code==422

def test_missing_run_is_safe(env):
    r=env[0].get(P+'/runs/missing/graph');assert r.status_code==404 and 'traceback' not in r.text.lower()

def test_no_writes_no_provider_and_no_n_plus_one(env):
    many=[]
    for i in range(25):
        item=record('Test only');item['fact_key']={'path':str(i)};many.append(item)
    id=stored_run(env,many)
    with env[1]() as db:
        before={t.name:db.execute(select(t)).all() for t in Base.metadata.tables.values()}
        svc=DiscoveryService(db);engine=db.get_bind();calls=[]
        def track(c,cu,statement,p,ctx,many):calls.append(statement)
        event.listen(engine,'before_cursor_execute',track)
        try:
            graph_summary(svc,id,limit=1,metadata_only=True);one=len(calls);calls.clear()
            graph_summary(svc,id,limit=25,metadata_only=True);assert len(calls)==one
        finally:event.remove(engine,'before_cursor_execute',track)
        assert {t.name:db.execute(select(t)).all() for t in Base.metadata.tables.values()}==before

@pytest.mark.parametrize('revision',['20260912_01','20260913_01','20260915_01'])
def test_partial_schema_does_not_require_promotions(tmp_path,monkeypatch,revision):
    from alembic import command
    from tests.test_attribution_migration import config
    from greedy_collector.database import create_fk_enabled_engine
    from greedy_collector.discovery.domain import SchemaUnavailable
    url='sqlite:///'+(tmp_path/'graph.db').as_posix();command.upgrade(config(url,monkeypatch),revision)
    engine=create_fk_enabled_engine(url)
    with Session(engine) as db:
        if revision=='20260912_01':
            with pytest.raises(SchemaUnavailable):DiscoveryService(db)
        else:
            svc=DiscoveryService(db);s=svc.get_or_create_subject('blockchain_address','ethereum',ETH)
            row=svc.create_run(s['id'],[{'transform_id':'wallet.local_labels','source_id':'gc_labels'}],idempotency_key=uuid4().hex)
            value=graph_summary(svc,row['id']);assert value.root.type=='wallet'
            assert value.promotion_available==(revision=='20260915_01')
        assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==revision
    engine.dispose()

def test_graph_re_sanitizes_and_has_explicit_schema(env,monkeypatch):
    ob=material(env,content='Test later-configured-graph-secret')
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','later-configured-graph-secret')
    r=env[0].get(P+'/runs/'+run_id(env,ob)+'/graph');assert r.status_code==200
    assert 'later-configured-graph-secret' not in r.text
    schemas=env[0].get('/openapi.json').json()['components']['schemas']
    assert schemas['GraphRead']['properties']['items'] and schemas['GraphEdge']['properties']['predicate']['enum']==['locally_labeled_as','repository_contains','resolves_to','mentions_wallet','publicly_labeled_as','mentioned_at','search_candidate','names_alias','names_entity','references_domain']
