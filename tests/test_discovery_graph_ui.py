from pathlib import Path
import subprocess
import pytest
from tests.test_ui import ui_client,no_monitoring
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('asset',['discovery_graph','discovery_graph_layout'])
def test_graph_assets_available_and_parse(ui_client,asset):
    assert ui_client[0].get('/static/js/'+asset+'.js').status_code==200
    result=subprocess.run(['node','--check',str(ROOT/f'static/js/{asset}.js')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

def test_graph_layout_behavior():
    r=subprocess.run(['node','--test',str(ROOT/'tests/discovery_graph.test.cjs')],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

def test_graph_workspace_and_existing_workflows_reused():
    source=(ROOT/'static/js/discovery.js').read_text(encoding='utf8')
    assert "button('Graph'" in source and 'initDiscoveryGraph' in source
    assert 'await graph.setRun(current.id)' in source and 'Back to Discovery graph' in source
    graph=(ROOT/'static/js/discovery_graph.js').read_text(encoding='utf8')
    assert 'Showing ${graph.items.length} of ${graph.total}' in graph
    assert 'Current review' in graph and 'Promoted (current)' in graph
    assert 'sourceReference(node.url)' in graph
    links=(ROOT/'static/js/discovery_manual_source.js').read_text(encoding='utf8')
    assert "link.rel='noopener noreferrer'" in links and "link.target='_blank'" in links
    assert "Copy source URL" in links and "endsWith('.onion')" in links
    assert 'Accessible result list' in graph and 'pointermove' in graph
    assert '/promote`' not in graph and 'fetch(' not in graph and 'POST' not in graph
