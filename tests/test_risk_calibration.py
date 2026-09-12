"""Deterministic calibration controls; fixtures never enter production paths."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from greedy_collector.risk import ExplainableRiskEngine
from greedy_collector.risk.engine import contribution_summary
from tests.risk_controls import controls, transfer, label, FOCUS, NOW
from tests.test_label_risk_serialization import lookup_client

def evaluate(txs=(),labels=(),paths=()):
    return ExplainableRiskEngine().evaluate(FOCUS,list(txs),list(labels),list(paths))

EXPECTED={
 'Empty/new':0,'Normal low volume':0,'Busy 778 records':0,'Many counterparties':0,
 'Exchange-like fan-in/out':5,'Dormant/reactivated':4,'Single risky counterparty':30,
 'Repeated risky exposure':30,'Known Mixer counterparty':25,'Known Scam counterparty':30,
 'Known Sanctioned counterparty':40,'Exchange counterparty':0,'Bridge counterparty':0,
 'Two-hop exposure':10,'Three-hop exposure':5,'Mixed strong exposure':95,
}

@pytest.mark.parametrize('name',list(EXPECTED))
def test_control_matrix(name):
    args=controls()[name]
    result=evaluate(*args)
    assert result['score']==EXPECTED[name]
    assert result['level']==('Low' if EXPECTED[name]<=30 else 'Medium' if EXPECTED[name]<=70 else 'High')
    assert result==evaluate(*args)
    assert result['score']==sum(f['score_contribution'] for f in result['findings'])
    assert result['score']==sum(category['applied'] for category in result['category_contributions'].values())
    assert result['category_contributions']==contribution_summary(result['findings'])
    json.dumps(result,allow_nan=False)

def test_original_control_evidence_proves_unlabeled_medium_mechanism():
    before=json.loads(Path(__file__).with_name('risk_before.json').read_text())
    assert before['Busy 778 records']['rules']=={'high_velocity':10,'many_to_one':8,'one_to_many':8,
        'round_number_transfers':5,'large_transfer':10,'peel_chain':12,'repeated_counterparty':5}
    assert sum(before['Busy 778 records']['rules'].values())==58
    assert len(controls()['Busy 778 records'][0])==778
    assert controls()['Busy 778 records'][1:]==([],[])

def test_correlated_behavior_category_cap_and_permutation_invariance():
    txs=[transfer(i,value=str(120-i),minute=30-i) for i in range(20)]
    result=evaluate(txs)
    assert result==evaluate(list(reversed(txs)))
    assert result['category_contributions']['behavioral']=={'raw':13,'applied':10,'cap':10}
    assert result['score']==10 and result['level']=='Low'
    scores={f['rule_id']:f['score_contribution'] for f in result['findings']}
    assert scores['peel_chain']==8 and scores['rapid_pass_through']==2
    assert scores['high_velocity']==scores['one_to_many']==scores['large_transfer']==0

def test_same_counterparty_multiple_labels_are_not_three_exposures():
    cp='0x'+'2'*40
    txs=[transfer(i,cp=cp) for i in range(6)]
    labels=[label(kind) for kind in ['Sanctioned','Scam','Mixer']]
    result=evaluate(txs,labels)
    assert result['score']==40
    assert result==evaluate(txs[::-1],labels[::-1])
    findings={item['rule_id']:item for item in result['findings']}
    assert findings['direct_scam']['score_contribution']==0
    assert findings['direct_mixer']['score_contribution']==0
    assert len(findings['direct_sanctioned']['evidence']['observations'])==6
    assert findings['direct_sanctioned']['evidence']['label']['last_updated'].startswith('2026-09-12T12:00:00')
    json.dumps(result)

def test_multiple_counterparties_of_one_type_still_have_one_rule_budget():
    labels=[label('Scam','0x'+str(i)*40) for i in [2,3]]
    result=evaluate([transfer(i,cp=item['address']) for i,item in enumerate(labels)],labels)
    assert result['score']==30
    finding=next(item for item in result['findings'] if item['rule_id']=='direct_scam')
    assert len(finding['evidence']['observations'])==2

def test_indirect_paths_decay_and_do_not_stack_on_direct():
    paths=[{'hops':hop,'terminal_type':'Sanctioned','confidence':0.8,'path':[str(i) for i in range(hop+1)]} for hop in [2,3,4]]
    assert evaluate(paths=paths)['score']==10
    assert evaluate(paths=paths[1:])['score']==5
    assert evaluate(paths=paths[2:])['score']==0
    direct=evaluate([transfer(0,cp='0x'+'2'*40)],[label('Sanctioned')],paths)
    assert direct['score']==40
    finding=next(f for f in direct['findings'] if f['rule_id']=='indirect_exposure')
    assert finding['raw_score_contribution']==10 and finding['score_contribution']==0
    assert len(finding['evidence']['observations'])==2

def test_amounts_in_different_assets_do_not_create_a_peel_pattern():
    txs=[transfer(i,value=str(20-i),minute=30-i,token='ETH' if i%2 else 'TOKEN') for i in range(6)]
    assert 'peel_chain' not in {f['rule_id'] for f in evaluate(txs)['findings']}

def test_gap_score_has_no_wall_clock_dependency(monkeypatch):
    class ForbiddenClock(datetime):
        @classmethod
        def now(cls,*args,**kwargs): raise AssertionError('No wall clock in deterministic scoring')
    monkeypatch.setattr('greedy_collector.risk.engine.datetime',ForbiddenClock)
    txs=controls()['Dormant/reactivated'][0]
    result=evaluate(txs)
    assert result['score']==4
    assert result==evaluate(txs)

def test_mixed_naive_and_aware_timestamps_are_safe():
    txs=[transfer(0),transfer(1)]
    txs[0].timestamp=txs[0].timestamp.replace(tzinfo=None)
    assert evaluate(txs)['score']==0

def test_global_cap_preserves_exact_applied_contribution_sum():
    txs,labels,_=controls()['Mixed strong exposure']
    txs += [transfer(i+20,value=str(120-i),minute=30-i) for i in range(20)]
    # Put the three labelled contacts inside the same hour too.
    for i in range(3): txs[i].timestamp=NOW-timedelta(minutes=40+i)
    result=evaluate(txs,labels)
    assert result['score']==100
    assert sum(item['score_contribution'] for item in result['findings'])==100
    assert result['category_contributions']['exposure']['applied']==95
    assert result['category_contributions']['behavioral']['applied']==5

def test_context_only_tokens_short_history_and_labels_are_zero():
    txs=[transfer(i,value='1000',token='TEST',cp='0x'+'2'*40) for i in range(3)]
    result=evaluate(txs,[label('Exchange'),label('Bridge')])
    assert result['score']==0
    assert {'large_transfer','fresh_wallet_large_funds','round_number_transfers','exchange_pattern','cross_chain_bridge'} <= {f['rule_id'] for f in result['findings']}
    assert all(f['category']=='context' and f['score_contribution']==0 for f in result['findings'])

@pytest.mark.parametrize('findings',[[],[{'rule_id':'high_velocity','score_contribution':10,'evidence':{'transaction_count':778}}]])
def test_saved_legacy_score_is_not_silently_recalculated(lookup_client,findings):
    from sqlalchemy.orm import Session
    from greedy_collector.models import RiskResult
    client,engine=lookup_client
    with Session(engine) as db:
        db.add(RiskResult(chain='ethereum',address=FOCUS,score=58,level='Medium',findings=findings))
        db.commit()
    response=client.get(f'/api/greedy-collector/address/ethereum/{FOCUS}/risk')
    assert response.status_code==200
    data=response.json()
    assert data['score']==58 and data['level']=='Medium' and data['findings']==findings
    assert 'category_contributions' not in data and 'scoring_model' not in data
