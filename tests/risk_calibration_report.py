"""Print the synthetic before/after controls without querying any provider."""
import json
import os
from pathlib import Path
# This command evaluates test fixtures in memory and must never initialize a user's DB.
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['GREEDY_COLLECTOR_DATABASE_URL']='sqlite:///:memory:'
os.environ['GREEDY_COLLECTOR_GRAPH_BACKEND']='sqlite'
from greedy_collector.risk import ExplainableRiskEngine
from tests.risk_controls import controls, FOCUS

def report():
    original=json.loads(Path(__file__).with_name('risk_before.json').read_text())
    print('| Synthetic control | Original rules: points | Before | Revised rules: applied points | After |')
    print('|---|---|---|---|---|')
    before_levels={key:0 for key in ['Low','Medium','High']}
    after_levels=dict(before_levels)
    for name,args in controls().items():
        old=original[name]
        new=ExplainableRiskEngine().evaluate(FOCUS,*args)
        before=', '.join(f'{rule}: {points}' for rule,points in old['rules'].items()) or 'None'
        after=', '.join(f"{f['rule_id']}: {f['score_contribution']}" for f in new['findings']) or 'None'
        print(f"| {name} | {before} | {old['score']} / {old['level']} | {after} | {new['score']} / {new['level']} |")
        before_levels[old['level']]+=1
        after_levels[new['level']]+=1
    print(f'\nSynthetic distribution (16 controls): before {before_levels}; after {after_levels}.')
    print('These scenarios are not a statistically representative blockchain sample.')

if __name__=='__main__': report()
