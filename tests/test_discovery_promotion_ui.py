"""Small ED-6 module/route contracts; browser scenarios cover interactions."""
from pathlib import Path
import subprocess
import pytest
from tests.test_ui import ui_client, no_monitoring
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('path',['/static/js/discovery_promotion.js','/static/js/attribution_handoff.js','/static/js/discovery.js','/static/js/attribution.js'])
def test_promotion_assets_load(ui_client,path):assert ui_client[0].get(path).status_code==200

def test_promotion_api_is_local_and_only_confirmation_writes():
    source=(ROOT/'static/js/attribution_handoff.js').read_text(encoding='utf8')
    assert "button('Preview promotion'" in source and "'Confirm promotion'" in source
    assert 'promotionConsent' in source and 'expected_claim_version:target.version' in source
    assert 'expected_source_fingerprint:promotionConsent.source_fingerprint' in source
    assert 'link:linkData(data)' in source and 'readPage(\'/claims\',values,offset,10)' in source

def test_observation_action_and_history_are_separate_from_review():
    source=(ROOT/'static/js/discovery_promotion.js').read_text(encoding='utf8')
    assert 'if(preview.eligible)' in source and 'Selected observation:' in source
    assert 'separate from relevance review' in source and 'limit=10&offset=' in source
    assert "source_kind:'discovery',source_id:observation.id" in source
    assert 'fetch(' not in source and '/promote`' not in source

@pytest.mark.parametrize('name',['discovery_promotion','attribution_handoff'])
def test_promotion_modules_parse(name):
    result=subprocess.run(['node','--check',str(ROOT/f'static/js/{name}.js')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
