"""AT-4 HTTP boundaries over real services; browser fixtures remain test-only."""
from pathlib import Path
import shutil,subprocess
import pytest
from tests.test_attribution_api import api,migrated_template,claim,attach,assess,ok,API,P,ETH,BTC
from tests.test_ui import ui_client,no_monitoring
from greedy_collector.models import Transaction,Address,RiskResult
from greedy_collector.transaction_identity import legacy_event_key
from sqlalchemy.orm import Session

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('chain,address',[('ethereum',ETH),('bitcoin',BTC)])
def test_summary_filter_uses_backend_normalization_and_counts(api,chain,address):
    client,_=api;row=claim(client,chain=chain,subject_ref=address)
    row=attach(client,row)['claim'];row=attach(client,row,'contradicts')['claim'];row=attach(client,row,'context')['claim']
    for spelling in [address,address.lower()] if chain=='ethereum' else [address]:
        listed=ok(client.get(P+'/claims',params={'chain':chain,'subject_ref':spelling}))
        assert listed['total']==1
        detail=ok(client.get(P+'/claims/'+listed['items'][0]['id']))
        assert detail['active_evidence_counts']=={'supports':1,'contradicts':1,'context':1}
        assert detail['needs_review']

def test_graph_snapshot_and_saved_risk_do_not_change_from_claims(api):
    client,engine=api;address=ETH.lower();other='0x'+'2'*40
    with Session(engine) as db:
        db.add(Address(chain='ethereum',address=address,balance_native='7'))
        for amount in ['1','2']:
            activity={'chain':'ethereum','tx_hash':'same-hash-test','from_address':address,
                'to_address':other,'value_native':amount,'token_symbol':'ETH','asset_contract':None}
            db.add(Transaction(**activity, event_key=legacy_event_key(activity), source_api='test-only'))
        db.commit()
    graph_path=API+'/address/ethereum/'+address+'/graph?hops=2'
    before=ok(client.get(graph_path))
    row=attach(client,claim(client))['claim'];ok(assess(client,row,'strongly_supported'))
    assert ok(client.get(graph_path))==before
    # Existing same-hash backend limitation is not used as an attribution identity key.
    with Session(engine) as db:
        assert db.query(Transaction).count()==2
        assert db.query(RiskResult).count()==0

@pytest.mark.parametrize('module',['attribution_summary','attribution_overlay','wallet','graph','attribution'])
def test_integration_assets(ui_client,module):
    response=ui_client[0].get('/static/js/'+module+'.js');assert response.status_code==200

def test_summary_handoff_surface(ui_client):
    client,_=ui_client
    assert 'id="wallet-attribution"' in client.get('/').text
    script=client.get('/static/js/attribution_summary.js').text
    assert 'No attribution claims have been recorded for this wallet.' in script
    assert 'No attribution claims recorded.' in script
    assert 'Create attribution claim' in script and 'Open attribution' in script
    assert "action:'create_claim'" in script and "action:'open_claim'" in script
    for word in ['fakeGraph','sampleWallet','cannedSearch','owned_by','Deanonymized','Unknown owner']:
        assert word not in script

def test_overlay_pure_layout_and_guards():
    if not shutil.which('node'):pytest.skip('Node is required for presentation checks')
    result=subprocess.run(['node','--test',str(ROOT/'tests/attribution_overlay.test.cjs')],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
