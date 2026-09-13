"""Lightweight frontend contracts. Full interactions use isolated browser checks."""
from pathlib import Path
import re
import pytest
from tests.test_ui import ui_client, no_monitoring

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name',['attribution','attribution_api','attribution_forms'])
def test_attribution_assets_load(ui_client,name):
    response=ui_client[0].get('/static/js/'+name+'.js')
    assert response.status_code==200 and 'javascript' in response.headers['content-type']


def test_attribution_navigation_and_views(ui_client):
    client,_=ui_client
    html=client.get('/').text
    assert html.count('data-workspace=')==8
    assert 'data-workspace="attribution"' in html and 'id="attribution-workspace"' in html
    app=client.get('/static/js/app.js').text
    assert 'initAttribution' in app and 'loadAttribution(id)' in app
    script=client.get('/static/js/attribution.js').text
    for value in ['attr-claims-view','attr-entities-view','Evidence-backed entity claims']:
        assert value in script


@pytest.mark.parametrize('forbidden',['Confirmed','owned_by','associated_with','Owner Finder','Identity Finder',
                                     'Edit evidence text','Delete evidence','Delete event','fakeGraph','sampleWallet','demoNodes','cannedSearch'])
def test_attribution_has_no_forbidden_controls_or_fixtures(forbidden):
    text='\n'.join(path.read_text(encoding='utf-8') for path in (ROOT/'static/js').glob('attribution*.js'))
    # Research status is permitted only in this explicit non-attribution warning.
    text=text.replace("Confirmed source match does not confirm wallet attribution.", "")
    assert forbidden not in text


def test_attribution_calls_local_namespace_and_never_other_workspaces():
    module=(ROOT/'static/js/attribution_api.js').read_text(encoding='utf-8')
    assert "const prefix = '/api/greedy-collector/attribution'" in module
    text='\n'.join(path.read_text(encoding='utf-8') for path in (ROOT/'static/js').glob('attribution*.js'))
    for forbidden in ['/lookup/','/kyc/','/labels/','/graph/','/cases/','innerHTML','insertAdjacentHTML','method:\'DELETE\'']:
        assert forbidden not in text
    # SVG's namespace URI is an identifier, not a fetched network resource.
    assert not re.search(r'https?://',text.replace('http://www.w3.org/2000/svg',''))


def test_review_acknowledgements_and_versions_are_explicit():
    script=(ROOT/'static/js/attribution.js').read_text(encoding='utf-8')
    assert 'acknowledged=new Set()' in script
    assert 'acknowledged_contradictions:[...acknowledged]' in script
    assert "check('I acknowledge this contradiction',acknowledged,'ackId')" in script
    assert 'expected_version:row.version' in script
    assert 'Replacement creates a new immutable evidence record; the original remains in history.' in script


def test_unmigrated_workspace_uses_safe_api_guard(ui_client):
    # Existing metadata-only fixture is deliberately unstamped, not a migrated DB.
    response=ui_client[0].get('/api/greedy-collector/attribution/entities')
    assert response.status_code==503 and response.json()['detail']['code']=='schema_unavailable'
    assert ui_client[0].get('/').status_code==200
