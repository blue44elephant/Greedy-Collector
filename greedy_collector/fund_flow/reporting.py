import json
from .domain import DISCLAIMER

def flow_lines(entities):
    lines=[]
    for entity in entities:
        if entity.get('entity_type')!='fund_flow':continue
        pin=(entity.get('metadata_json') or {}).get('fund_flow_pin')
        if not isinstance(pin,dict):
            lines.append('Pinned fund-flow material unavailable.');continue
        lines.extend(['','## Observed fund-flow analysis',DISCLAIMER,
            'Run: '+pin['id']+' / '+pin['algorithm_version'],
            'Parameters: '+json.dumps(pin['parameters'],sort_keys=True),
            'Data fingerprint: '+pin['source_data_fingerprint'],
            'Cutoff: '+json.dumps(pin['source_data_cutoff'],sort_keys=True),
            'Truncated: '+str(pin['truncated'])+' / '+', '.join(pin['limiting_reasons']),pin['coverage']])
        for path in pin['paths']:lines.append(json.dumps(path,sort_keys=True))
        if pin.get('utxo_transactions'):lines.append('UTXO transaction provenance: '+json.dumps(pin['utxo_transactions'],sort_keys=True))
        lines.append('Observed metrics: '+json.dumps(pin['analytics'],sort_keys=True))
    return lines
