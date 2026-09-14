"""ED-5 navigation contract. Runtime data comes only from existing local APIs."""
from pathlib import Path
import subprocess
import pytest
from tests.test_ui import ui_client, no_monitoring

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('path',['/','/health','/docs','/openapi.json','/static/js/wallet.js','/static/js/graph.js','/static/js/discovery.js','/static/js/discovery_handoff.js','/static/js/app.js'])
def test_handoff_routes(ui_client,path):
    assert ui_client[0].get(path).status_code==200

@pytest.mark.parametrize('text',['Back to graph','Back to wallet','From ${label(entry.origin)}','Select pivots, Plan, then Run explicitly.','You have an active run for another subject.','Current subject · ','await checkSubject(entry.chain)','c.check.checked = false'])
def test_handoff_discovery_surface(text):
    assert text in (ROOT/'static/js/discovery.js').read_text(encoding='utf8')

def test_actions_remain_separate_from_attribution():
    html=(ROOT/'static/index.html').read_text(encoding='utf8')
    assert 'id="wallet-discovery"' in html and 'id="wallet-attribution"' in html
    graph=(ROOT/'static/js/graph.js').read_text(encoding='utf8')
    assert 'graphWalletEligible(graph,subject)' in graph and 'graphSubjectIsUnambiguous(graph,subject)' in graph

def test_helper_has_no_execution_or_fixture_paths():
    source=(ROOT/'static/js/discovery_handoff.js').read_text(encoding='utf8')
    for forbidden in ['fetch(','/runs','/plan','/lookup/','fakeGraph','sampleWallet','cannedSearch','localStorage','sessionStorage','window.open']:
        assert forbidden not in source

def test_navigation_helper_behavior():
    result=subprocess.run(['node','--test',str(ROOT/'tests/discovery_handoff.test.cjs')],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
