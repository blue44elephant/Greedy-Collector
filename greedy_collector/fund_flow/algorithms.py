"""Bounded deterministic simple paths, BFS and maximum-bottleneck priority search."""
from collections import defaultdict, deque
from decimal import Decimal
import heapq
import time
from .domain import decimal_text, CAPACITY_CAVEAT, UTXO_CAVEAT


def transitions(event,source):
    if event['semantics']=='observed_transfer':
        yield event
    else:
        for output in event['outputs']:
            yield {k:v for k,v in event.items() if k not in ('sources','outputs','stored_event_keys')} | {
                'id':event['id']+':'+source+':'+str(output['index']), 'source':source,'target':output['address'],
                'output_index':output['index'],'output_amount':output['output_amount'],
                'raw_output_amount':output['raw_output_amount'], 'input_count':len(event['sources']), 'transaction_provenance_ref':event['id']}


def search(events,q,targets,deadline,neighborhood=False):
    adjacency=defaultdict(list)
    for event in events:
        for source in event.get('sources',[event.get('source')]):adjacency[source].append(event)
    for value in adjacency.values():value.sort(key=lambda e:(e['timestamp'] or '',e['tx_hash'],e['event_key'],e['id']))
    # States retain visited addresses: global BFS visitation would lose valid temporal paths.
    initial=([q.source],[],None,None,Decimal('Infinity'),frozenset())
    queue=deque([initial]);heap=[];serial=0
    if q.algorithm=='widest':heapq.heappush(heap,(-initial[4],(),serial,initial))
    result=[];reasons=set();nodes={q.source};explored=0;shortest=None
    while heap if q.algorithm=='widest' else queue:
        if time.monotonic()>deadline:reasons.add('execution_timeout');break
        if q.algorithm=='widest':_,_,_,state=heapq.heappop(heap)
        else:state=queue.popleft()
        addresses,steps,asset,last_time,capacity,used_tx=state
        if steps and (neighborhood or addresses[-1] in targets):
            if q.algorithm=='shortest' and not neighborhood:
                if shortest is None:shortest=len(steps)
                if len(steps)>shortest:break
            result.append({'addresses':addresses,'steps':steps,'hops':len(steps),'asset':asset,
                'first_timestamp':steps[0]['timestamp'],'last_timestamp':steps[-1]['timestamp'],
                'observed_path_capacity':decimal_text(capacity) if capacity.is_finite() else None,
                'explanation':UTXO_CAVEAT if steps[0]['semantics']=='utxo_connectivity' else f"Path uses {len(steps)} observed transfer events between {len(addresses)} addresses from the locally stored dataset. "+CAPACITY_CAVEAT})
            if len(result)>=q.max_paths:
                if queue or heap or (neighborhood and len(steps)<q.max_hops):reasons.add('max_paths')
                break
            if not neighborhood:continue
        if len(steps)>=q.max_hops:continue
        if shortest is not None and len(steps)>=shortest:continue
        stop=False
        for event in adjacency.get(addresses[-1],[]):
            if asset is not None and event['asset']!=asset:continue
            if q.algorithm=='widest' and event['semantics']!='observed_transfer':continue
            if q.temporal_order and (not event['timestamp'] or (last_time and event['timestamp']<last_time)):continue
            if event['semantics']=='utxo_connectivity' and event['tx_hash'] in used_tx:continue
            for edge in transitions(event,addresses[-1]):
                if time.monotonic()>deadline:reasons.add('execution_timeout');stop=True;break
                explored+=1
                if explored>q.max_edges:reasons.add('max_explored_edges');stop=True;break
                if edge['target'] in addresses:continue
                nodes.add(edge['target'])
                if len(nodes)>q.max_nodes:reasons.add('max_explored_nodes');stop=True;break
                next_capacity=min(capacity,Decimal(edge['amount'])) if edge['amount'] is not None else Decimal('Infinity')
                next_state=(addresses+[edge['target']],steps+[edge],edge['asset'],edge['timestamp'],next_capacity,used_tx|{edge['tx_hash']})
                if q.algorithm=='widest':
                    serial+=1
                    heapq.heappush(heap,(-next_capacity,tuple(e['id'] for e in next_state[1]),serial,next_state))
                else:queue.append(next_state)
            if stop:break
        if stop:break
    return {'paths':result,'truncated':bool(reasons),'limiting_reasons':sorted(reasons),
            'explored_nodes':min(len(nodes),q.max_nodes),'explored_edges':min(explored,q.max_edges)}


def metrics(events,source,limit=1000,deadline=None):
    """Each genuine event counted once per direction/asset; no UTXO pair allocation."""
    buckets={};repeated={};limits=set()
    def group(asset,direction):
        return buckets.setdefault((asset,direction),{'asset':asset,'direction':direction,'event_ids':set(),'counterparties':set(),'amount':Decimal(0),'precise':True})
    for event in events:
        if deadline is not None and time.monotonic()>deadline:limits.add('execution_timeout');break
        for direction in ('incoming','outgoing'):
            if event['semantics']=='observed_transfer':
                if event['target' if direction=='incoming' else 'source']!=source:continue
                peers={event['source' if direction=='incoming' else 'target']}-{source}
            else:
                sources=set(event['sources']);destinations={o['address'] for o in event['outputs']}
                if source not in (destinations if direction=='incoming' else sources):continue
                peers=(sources if direction=='incoming' else destinations)-{source}
            bucket=group(event['asset'],direction)
            bucket['event_ids'].add(event['id']);bucket['counterparties'].update(peers)
            if event['amount'] is None:bucket['precise']=False
            else:bucket['amount']+=Decimal(event['amount'])
            for peer in sorted(peers):
                item=repeated.setdefault((event['asset'],direction,peer),{'asset':event['asset'],'direction':direction,'counterparty':peer,'event_ids':set(),'times':[],'amount':Decimal(0),'precise':True})
                item['event_ids'].add(event['id'])
                if event['timestamp']:item['times'].append(event['timestamp'])
                if event['amount'] is None:item['precise']=False
                else:item['amount']+=Decimal(event['amount'])
    rows=[]
    for _,b in sorted(buckets.items()):
        rows.append({'asset':b['asset'],'direction':b['direction'],'distinct_counterparties':len(b['counterparties']),
                     'event_count':len(b['event_ids']),'observed_amount':decimal_text(b['amount']) if b['precise'] else None,
                     'explanation':f"{len(b['counterparties'])} distinct counterparties in {len(b['event_ids'])} stored events in the selected scope."+(' '+UTXO_CAVEAT if not b['precise'] else '')})
    peers=[]
    for _,r in sorted(repeated.items()):
        if len(r['event_ids'])<2:continue
        peers.append({k:r[k] for k in ('asset','direction','counterparty')} | {'count':len(r['event_ids']),
                      'first_observed':min(r['times']) if r['times'] else None,'last_observed':max(r['times']) if r['times'] else None,
                      'observed_amount':decimal_text(r['amount']) if r['precise'] else None})
    if len(rows)>limit or len(peers)>limit:limits.add('max_metric_rows')
    return {'wallet':source,'fan_in_out':rows[:limit],'repeated_counterparties':peers[:limit], 'limiting_reasons':sorted(limits)}
