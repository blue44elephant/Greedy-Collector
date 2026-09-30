"""Safe projections from durable provider evidence; never use UTXO representative pairs."""
from collections import defaultdict
import time
from .domain import amount, decimal_text, iso, digest, UTXO_CAVEAT
from ..chains.registry import ChainFamily
from ..collection import execution_status, atomic_amount


def successful(row,d,pub,raw):
    if execution_status(row) == "failed": return False
    if d.evm_compatible:
        if str(raw.get('isError',''))=='1' or str(raw.get('txreceipt_status',''))=='0':return False
        if row.source_api=='etherscan_token':return bool(row.block_number) and bool(row.asset_contract)
        return row.source_api=='etherscan' and (str(raw.get('isError',''))=='0' or str(raw.get('txreceipt_status',''))=='1')
    if row.source_api=='solana-json-rpc':return pub.get('execution_status')=='succeeded'
    if row.source_api=='trongrid_trc20':
        return pub.get('confirmed') is True and pub.get('asset_type')=='trc20'
    if row.source_api=='trongrid':
        provider=raw.get('provider',{});ret=provider.get('ret',[]) if isinstance(provider,dict) else []
        return pub.get('asset_type')=='native' and bool(ret) and all(isinstance(item,dict) and item.get('contractRet')=='SUCCESS' for item in ret)
    return False


def account_edge(row,d):
    raw=row.raw_payload if isinstance(row.raw_payload,dict) else {}
    pub=raw.get('_public',{});pub=pub if isinstance(pub,dict) else {}
    if not successful(row,d,pub,raw):return None,'unsuccessful_or_unknown_execution'
    try:
        adapter=d.adapter()
        source=adapter.normalize_address(row.from_address);target=adapter.normalize_address(row.to_address)
        value=amount(row.value_native)
        if not adapter.identify_transaction(row.tx_hash):raise ValueError()
        token=row.asset_contract
        if token:
            asset=d.chain_id+':token:'+adapter.normalize_address(token)
        else:
            if pub.get('asset_type') not in (None,'native') or row.source_api.endswith(('_token','_trc20')):raise ValueError()
            asset=d.chain_id+':native'
    except (ValueError,TypeError):return None,'incomplete_transfer_identity_or_amount'
    raw_value=pub.get('raw_value',raw.get('value'))
    raw_value=str(raw_value) if isinstance(raw_value,(str,int)) and not isinstance(raw_value,bool) and str(raw_value).isdigit() and len(str(raw_value))<=120 else None
    def public_address(name):
        try:return adapter.normalize_address(pub[name]) if isinstance(pub.get(name),str) else None
        except ValueError:return None
    material={'chain':d.chain_id,'tx_hash':row.tx_hash,'event_key':row.event_key,'source':source,'target':target,
        'asset':asset,'symbol':row.token_symbol,'amount':decimal_text(value),'raw_amount':raw_value,
        'timestamp':iso(row.timestamp),'block':row.block_number or None,'confirmed':pub.get('confirmed') if isinstance(pub.get('confirmed'),bool) else (True if row.block_number else None),
        'semantics':'observed_transfer','provider':row.source_api,
        'source_token_account':public_address('source_token_account') if row.source_api=='solana-json-rpc' else None,
        'destination_token_account':public_address('destination_token_account') if row.source_api=='solana-json-rpc' else None}
    material['id']=digest([d.chain_id,row.tx_hash,row.event_key])
    return material,None


def utxo_event(row,d):
    raw=row.raw_payload if isinstance(row.raw_payload,dict) else {}
    inputs,outputs=raw.get('vin'),raw.get('vout');status=raw.get('status',{})
    if not isinstance(status,dict) or status.get('confirmed') is not True:return None,'unconfirmed_or_unknown_status'
    if not isinstance(inputs,list) or not inputs or not isinstance(outputs,list) or not outputs:return None,'incomplete_utxo_data'
    adapter=d.adapter();sources=set();targets=[]
    try:
        if raw.get('txid','').lower()!=row.tx_hash.lower() or not adapter.identify_transaction(row.tx_hash):raise ValueError()
        for item in inputs:
            prev=item.get('prevout')
            if item.get('is_coinbase') or not isinstance(prev,dict) or type(prev.get('value')) is not int or prev['value']<0:raise ValueError()
            sources.add(adapter.normalize_address(prev['scriptpubkey_address']))
        for index,output in enumerate(outputs):
            value=output.get('value')
            if type(value) is not int or value<0:raise ValueError()
            if value==0:continue
            if not output.get('scriptpubkey_address'):
                # Unspendable outputs do not identify a wallet and cannot be traversed.
                if output.get('scriptpubkey_type')=='op_return':continue
                raise ValueError()
            targets.append({'address':adapter.normalize_address(output['scriptpubkey_address']),
                            'index':index,'raw_output_amount':str(value),'output_amount':atomic_amount(value, d.native_decimals)})
    except (KeyError,TypeError,ValueError,AttributeError):return None,'incomplete_utxo_data'
    # Retain each output index; never multiply input x output amounts.
    if not targets:return None,'no_address_outputs'
    return {'id':digest([d.chain_id,row.tx_hash.lower(),'utxo-connectivity']), 'chain':d.chain_id,'tx_hash':row.tx_hash.lower(),
        'event_key':'utxo-connectivity','stored_event_keys':[row.event_key],'sources':sorted(sources),'outputs':targets,'asset':d.chain_id+':native',
        'symbol':d.native_symbol,'timestamp':iso(row.timestamp),'block':row.block_number or None,'confirmed':True,
        'semantics':'utxo_connectivity','amount':None,'raw_amount':None,'caveat':UTXO_CAVEAT},None


def project(rows,d,deadline=None):
    events={};excluded=defaultdict(int);conflicts=set()
    for row in rows:
        if deadline is not None and time.monotonic()>deadline:
            excluded['execution_timeout']=1;break
        edge,reason=utxo_event(row,d) if d.family==ChainFamily.UTXO else account_edge(row,d)
        if reason:excluded[reason]+=1;continue
        key=edge['id']
        if key in events:
            previous=events[key]
            if {k:v for k,v in previous.items() if k!='stored_event_keys'}!={k:v for k,v in edge.items() if k!='stored_event_keys'}:conflicts.add(key)
            elif edge['semantics']=='utxo_connectivity':previous['stored_event_keys']=sorted(set(previous['stored_event_keys']+edge['stored_event_keys']))
        else:events[key]=edge
    for key in conflicts:events.pop(key,None)
    if conflicts:excluded['conflicting_event_views']=len(conflicts)
    return sorted(events.values(),key=lambda e:(e['tx_hash'],e['event_key'])),dict(sorted(excluded.items()))
