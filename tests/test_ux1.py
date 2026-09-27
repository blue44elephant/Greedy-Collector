"""UX-1 diagnostics through real HTTP/runtime; isolated fixtures, zero providers."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from tests.test_discovery_execution import h
from tests.test_discovery_local_manual import live, BTC
from tests.test_discovery_api import PREFIX, ok, create, terminal

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a,**kw):raise AssertionError('UX-1 must not call providers')
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request',deny)
    monkeypatch.setattr('httpx.HTTPTransport.handle_request',deny)

@pytest.mark.parametrize('tid,mode,capture,chains',[
    ('wallet.local_labels','local',False,None),('wallet.manual_exact_web','manual',False,None),
    ('wallet.manual_source_observation','manual',True,None),('wallet.public_code_mentions','automated',False,None),
    ('wallet.graphsense_public_tags','automated',False,['bitcoin','ethereum']),('wallet.ens_primary_name','automated',False,['ethereum'])])
def test_transform_metadata(live,tid,mode,capture,chains):
    client,_,_=live
    t=next(t for t in ok(client.get(PREFIX+'/transforms')) if t['id']==tid)
    assert t['implemented'] and t['mode']==mode and t['capture_only']==capture
    assert isinstance(t['configured'],bool) and isinstance(t['executable'],bool)
    if chains:assert t['chains']==chains
    else:assert len(t['chains'])==10
    if tid in ('wallet.public_code_mentions','wallet.graphsense_public_tags'):
        assert not t['configured'] and not t['executable']
        assert t['missing_configuration']==['DISCOVERY_GITHUB_TOKEN']
        assert t['unavailable_reason']=='configuration_unavailable'


def test_configured_secret_is_never_returned(live,monkeypatch):
    client,_,_=live
    monkeypatch.setenv('DISCOVERY_GITHUB_TOKEN','ux1-test-only-secret')
    data=ok(client.get(PREFIX+'/transforms'))
    assert 'ux1-test-only-secret' not in json.dumps(data)
    t=next(t for t in data if t['id']=='wallet.public_code_mentions')
    assert t['configured'] and t['executable'] and t['missing_configuration']==[]


def test_dependency_reason_is_not_missing_key(live,monkeypatch):
    client,_,_=live
    monkeypatch.setenv('ALCHEMY_API_KEY','ux1-test-only-rpc-secret')
    monkeypatch.setattr('greedy_collector.discovery.ens.get_settings',lambda:SimpleNamespace(alchemy_api_key='ux1-test-only-rpc-secret'))
    monkeypatch.setattr('greedy_collector.discovery.ens.probe_ens_normalizer',lambda:SimpleNamespace(usable=False))
    t=next(t for t in ok(client.get(PREFIX+'/transforms')) if t['id']=='wallet.ens_primary_name')
    assert not t['executable'] and t['dependency_unavailable'] and not t['missing_configuration']
    assert 'ux1-test-only-rpc-secret' not in json.dumps(t)


def test_mixed_preflight_and_execution_accounting(live):
    client,h,_=live
    data={'subject':{'chain':'bitcoin','address':BTC},'refresh':True,'selections':[
        {'transform_id':'wallet.local_labels','source_id':'gc_labels'},
        {'transform_id':'wallet.public_code_mentions','source_id':'github'},
        {'transform_id':'wallet.graphsense_public_tags','source_id':'github'}]}
    planned=ok(client.post(PREFIX+'/plan',json=data))
    assert [p['eligibility'] for p in planned['selections']]==['eligible','configuration_unavailable','configuration_unavailable']
    assert ok(client.get(PREFIX+'/runs'))['total']==0
    row=terminal(client,ok(create(client,data),202)['id'])
    assert row['status']=='partial' and row['returned_count']==0 and row['refresh'] is True
    assert [s['status'] for s in row['sources']]==['succeeded','unavailable','unavailable']
    assert all(s['requests_attempted']==0 for s in row['sources'])


def test_incompatible_chain_preflight_rejected_without_execution(live):
    client,_,_=live
    response=client.post(PREFIX+'/plan',json={'subject':{'chain':'bitcoin','address':BTC},'selections':[{'transform_id':'wallet.ens_primary_name','source_id':'ens_ethereum'}]})
    assert response.status_code==422
    assert ok(client.get(PREFIX+'/runs'))['total']==0


def test_ux1_frontend_contracts():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test',str(root/'tests/ux1.test.mjs')],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
