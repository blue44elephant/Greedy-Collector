"""Snapshot local data, run bounded analysis, persist immutable analyst results."""
from datetime import datetime, timezone
from decimal import localcontext
from uuid import uuid4
import time
from sqlalchemy import select, or_, func, inspect, text
from ..models import Transaction, Label, Case, CaseEntity
from ..chains.registry import ChainFamily
from .models import FlowRun
from .domain import definition, FlowError, digest, iso, VERSION, DISCLAIMER, MAX_ROWS, MAX_BYTES, MAX_TARGETS, TIMEOUT
from .edges import project
from .algorithms import search, metrics

class FlowService:
    def __init__(self,db):self.db=db

    def ready(self):
        if 'fund_flow_runs' not in inspect(self.db.get_bind()).get_table_names():
            raise FlowError('Fund-flow storage unavailable. Explicit migration required.',503)

    def targets(self,q,d):
        if q.target:return [q.target],[]
        if not (q.label or q.label_category):return [],[]
        query=select(Label.address).where(Label.chain.in_([q.chain,'any']))
        query=query.where(Label.label==q.label) if q.label else query.where(Label.type==q.label_category)
        addresses=self.db.scalars(query.distinct().order_by(Label.address).limit(MAX_TARGETS+1)).all()
        reasons=['max_label_targets'] if len(addresses)>MAX_TARGETS else []
        targets=set();adapter=d.adapter()
        for address in addresses[:MAX_TARGETS]:
            try:targets.add(adapter.normalize_address(address))
            except ValueError:continue
        return sorted(targets),reasons

    def load(self,q,d,deadline):
        reasons=set();rows={};size=0;adapter=d.adapter();seen=set()
        filters=[Transaction.chain==q.chain]
        if q.start_time:filters.append(Transaction.timestamp>=q.start_time)
        if q.end_time:filters.append(Transaction.timestamp<=q.end_time)
        if q.asset:
            if q.asset.endswith(':native'):filters.append(Transaction.asset_contract.is_(None))
            else:
                contract=q.asset.split(':token:',1)[1]
                column=func.lower(Transaction.asset_contract) if d.evm_compatible else Transaction.asset_contract
                filters.append(column==contract)
        def collect(extra=()):
            nonlocal size
            query=select(Transaction.id,func.length(Transaction.raw_payload)).where(*filters,*extra).order_by(Transaction.tx_hash,Transaction.event_key).limit(MAX_ROWS+1)
            # Only lightweight indexed candidates are read before enforcing JSON size bounds.
            candidates=self.db.execute(query).all()
            for row_id,length in candidates:
                if row_id in rows:continue
                if time.monotonic()>deadline:reasons.add('execution_timeout');return
                if len(rows)>=MAX_ROWS:reasons.add('max_stored_rows');return
                if size+(length or 0)>MAX_BYTES:reasons.add('max_source_bytes');return
                row=self.db.get(Transaction,row_id)
                rows[row_id]=row;size+=length or 0
        if d.family==ChainFamily.UTXO:
            # Input/output participants have no relational index; bounded raw scan is required.
            collect()
        else:
            outgoing=func.lower(Transaction.from_address) if d.evm_compatible else Transaction.from_address
            incoming=func.lower(Transaction.to_address) if d.evm_compatible else Transaction.to_address
            frontier={q.source}
            for depth in range(q.max_hops):
                if not frontier or reasons:break
                current=sorted(frontier-seen);seen.update(current)
                if len(seen)>q.max_nodes:reasons.add('max_explored_nodes');break
                previous=set(rows)
                for start in range(0,len(current),200):
                    condition=outgoing.in_(current[start:start+200])
                    if depth==0:condition=or_(condition,incoming==q.source)
                    collect([condition])
                    if reasons:break
                frontier=set()
                for row_id in set(rows)-previous:
                    row=rows[row_id]
                    if adapter.address_key(row.from_address) not in seen:continue
                    try:frontier.add(adapter.normalize_address(row.to_address))
                    except ValueError:continue
        ordered=sorted(rows.values(),key=lambda r:(r.tx_hash,r.event_key))
        material=[{key:getattr(row,key) for key in ('chain','tx_hash','event_key','from_address','to_address','value_native','asset_contract','token_symbol','block_number','source_api','raw_payload')} | {'timestamp':iso(row.timestamp)} for row in ordered]
        return ordered,sorted(reasons),digest(material)

    def analyze(self,q,kind='path'):
        d=definition(q.chain)
        if kind=='path' and not (q.target or q.label or q.label_category):raise FlowError('Choose a wallet or local Label target.')
        if q.algorithm=='widest' and (d.family==ChainFamily.UTXO or not q.asset):
            raise FlowError('Widest paths require one explicit asset and precise account-chain transfers.')
        self.ready()
        if self.db.in_transaction():raise FlowError('Analysis requires a separate transaction.',409)
        try:
            self.db.execute(text('BEGIN IMMEDIATE'))
            created=iso(datetime.now(timezone.utc));deadline=time.monotonic()+TIMEOUT
            targets,target_limits=self.targets(q,d)
            rows,limits,source_fingerprint=self.load(q,d,deadline)
            with localcontext() as context:
                context.prec=512
                events,excluded=project(rows,d,deadline)
                filtered=[]
                for e in events:
                    if q.asset and e['asset']!=q.asset:continue
                    if q.temporal_order and not e['timestamp']:
                        excluded['unknown_timestamp']=excluded.get('unknown_timestamp',0)+1;continue
                    filtered.append(e)
                result=search(filtered,q,set(targets),deadline,neighborhood=kind=='neighborhood') if (targets or kind=='neighborhood') else {'paths':[],'truncated':False,'limiting_reasons':[],'explored_nodes':0,'explored_edges':0}
                result['analytics']=metrics(filtered,q.source,q.max_nodes,deadline)
                used_transactions={step.get('transaction_provenance_ref') for path in result['paths'] for step in path['steps']}
                result['utxo_transactions']=[e for e in filtered if e['id'] in used_transactions]
            result['limiting_reasons']=sorted(set(result['limiting_reasons']+limits+target_limits+result['analytics']['limiting_reasons']+(['execution_timeout'] if 'execution_timeout' in excluded else [])))
            result['truncated']=bool(result['limiting_reasons'])
            result.update({'chain':q.chain,'parameters':q.model_dump(mode='json'),'kind':kind,'algorithm_version':VERSION,
                'resolved_targets':targets,'source_data_fingerprint':source_fingerprint,'source_row_count':len(rows),
                'source_data_cutoff':{'snapshot_at':created,'latest_observed_timestamp':max((iso(r.timestamp) for r in rows if r.timestamp),default=None)},
                'excluded_records':excluded,'disclaimer':DISCLAIMER,
                'coverage':'Only locally stored, bounded activity is analyzed. No path does not establish absence of activity. Additional collection may be required.',
                'metric_scope':'Selected asset/time scope in the bounded loaded dataset; amounts remain separated by asset.'})
            # Generated run/capture time never participates in result identity.
            stable={k:v for k,v in result.items() if k!='source_data_cutoff'}
            result['result_fingerprint']=digest(stable)
            result['id']=str(uuid4());result['created_at']=created
            self.db.add(FlowRun(id=result['id'],chain=q.chain,source=q.source,created_at=created,snapshot=result))
            self.db.commit()
            return result
        except Exception:self.db.rollback();raise

    def run(self,run_id):
        self.ready();row=self.db.get(FlowRun,run_id)
        if row is None:raise FlowError('Fund-flow run not found.',404)
        return row.snapshot

    def pin(self,case_id,run_id):
        self.ready()
        if self.db.in_transaction():raise FlowError('Pinning requires a separate transaction.',409)
        try:
            self.db.execute(text('BEGIN IMMEDIATE'))
            if self.db.get(Case,case_id) is None:raise FlowError('Case not found.',404)
            snapshot=self.run(run_id)
            existing=self.db.scalar(select(CaseEntity).where(CaseEntity.case_id==case_id,CaseEntity.entity_type=='fund_flow',CaseEntity.entity_ref==run_id))
            if existing:
                result={'id':existing.id,'pinned':existing.metadata_json['fund_flow_pin']}
            else:
                row=CaseEntity(id=str(uuid4()),case_id=case_id,entity_type='fund_flow',entity_ref=run_id,metadata_json={'chain':snapshot['chain'],'fund_flow_pin':snapshot})
                self.db.add(row);self.db.flush();result={'id':row.id,'pinned':snapshot}
            self.db.commit();return result
        except Exception:self.db.rollback();raise
