"""ED-3 static/API surface checks; synthetic browser execution stays in tests."""
from pathlib import Path
import subprocess
import pytest
from tests.test_ui import ui_client, no_monitoring

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('path',['/','/health','/docs','/openapi.json','/static/js/discovery.js','/static/js/discovery_api.js','/static/app.css'])
def test_discovery_routes_and_assets(ui_client,path):
    assert ui_client[0].get(path).status_code==200

def test_discovery_ninth_workspace(ui_client):
    html=ui_client[0].get('/').text
    assert html.count('data-workspace=')==9
    assert 'data-workspace="discovery"' in html and 'id="discovery-workspace"' in html
    app=ui_client[0].get('/static/js/app.js').text
    assert 'initDiscovery' in app and 'discovery.setVisible(name === "discovery")' in app

@pytest.mark.parametrize('value',['Public-source pivots & candidate evidence','Available pivots','Source capabilities','Not implemented','Not executable','No automated Discovery pivots are executable','Plan selected pivots','Diagnostic plan','No selected pivots are currently executable','expected_plan_fingerprint','new_material_since_review','expected_source_fingerprint','Cached observation','Refresh sources','Archive run','Restore run'])
def test_discovery_surface_contract(value):
    assert value in (ROOT/'static/js/discovery.js').read_text(encoding='utf-8')

@pytest.mark.parametrize('forbidden',['Deanonymizer','Owner Finder','Identity Finder','Use as attribution evidence','fakeGraph','sampleWallet','demoNodes','mockTransactions','cannedSearch','alembic','create_all','/lookup/','/kyc/','/attribution/','innerHTML','window.open','setInterval'])
def test_discovery_runtime_boundaries(forbidden):
    source='\n'.join((ROOT/f'static/js/{name}.js').read_text(encoding='utf-8') for name in ['discovery','discovery_api'])
    assert forbidden not in source

def test_discovery_fetches_are_local_only():
    source=(ROOT/'static/js/discovery_api.js').read_text(encoding='utf-8')
    assert "fetch('/api/greedy-collector/discovery' + path" in source
    assert 'fetch(' not in (ROOT/'static/js/discovery.js').read_text(encoding='utf-8')

def test_discovery_frontend_behavior():
    result=subprocess.run(['node','--test',str(ROOT/'tests/discovery.test.cjs')],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
