"""Synthetic calibration scenarios ONLY for tests; never production runtime data."""
from datetime import datetime, timedelta, timezone
from greedy_collector.schemas import NormalizedTransaction

FOCUS = '0x'+'1'*40
NOW = datetime(2026,9,12,12,tzinfo=timezone.utc)

def transfer(index, direction='outgoing', value='0.25', cp=None, minute=None, token='ETH'):
    cp = cp or '0x'+format(index+100,'040x')
    return NormalizedTransaction(chain='ethereum',tx_hash='0x'+format(index,'064x'),
        from_address=FOCUS if direction=='outgoing' else cp,
        to_address=cp if direction=='outgoing' else FOCUS,
        direction=direction,value_native=value,token_symbol=token,
        timestamp=NOW-timedelta(minutes=index*120 if minute is None else minute),source_api='test-only')

def label(kind, address=None):
    return {'address':address or '0x'+'2'*40,'type':kind,'label':f'Test-only {kind}',
        'source':'Synthetic calibration fixture','confidence':0.8,'last_updated':NOW}

def controls():
    busy=[transfer(i,'incoming' if i%2 else 'outgoing',str(1000-i),
        cp='0x'+'3'*40 if i%10==0 else None) for i in range(778)]
    cp='0x'+'2'*40
    return {
      'Empty/new':([],[],[]),
      'Normal low volume':([transfer(i) for i in range(3)],[],[]),
      'Busy 778 records':(busy,[],[]),
      'Many counterparties':([transfer(i,'incoming' if i%2 else 'outgoing') for i in range(40)],[],[]),
      'Exchange-like fan-in/out':([transfer(i,'incoming' if i%2 else 'outgoing','10',minute=i) for i in range(30)],[],[]),
      'Dormant/reactivated':([transfer(0),transfer(1,minute=181*24*60)],[],[]),
      'Single risky counterparty':([transfer(0,cp=cp)],[label('Scam')],[]),
      'Repeated risky exposure':([transfer(i,cp=cp) for i in range(30)],[label('Scam')],[]),
      'Known Mixer counterparty':([transfer(0,cp=cp)],[label('Mixer')],[]),
      'Known Scam counterparty':([transfer(0,cp=cp)],[label('Scam')],[]),
      'Known Sanctioned counterparty':([transfer(0,cp=cp)],[label('Sanctioned')],[]),
      'Exchange counterparty':([transfer(0,cp=cp)],[label('Exchange')],[]),
      'Bridge counterparty':([transfer(0,cp=cp)],[label('Bridge')],[]),
      'Two-hop exposure':([transfer(0)],[],[{'hops':2,'terminal_type':'Scam','path':[FOCUS,'middle',cp],'confidence':0.8}]),
      'Three-hop exposure':([transfer(0)],[],[{'hops':3,'terminal_type':'Scam','path':[FOCUS,'middle','other',cp],'confidence':0.8}]),
      'Mixed strong exposure':([transfer(i,cp='0x'+str(i+2)*40) for i in range(3)],
          [label(kind,'0x'+str(i+2)*40) for i,kind in enumerate(['Sanctioned','Scam','Mixer'])],[]),
    }
