"""Read projections and explicit candidate reviews/pins over existing Discovery runs."""
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select,inspect,update,text
from ...models import DiscoveryObservation as Observation,DiscoveryRunItem as Item,DiscoveryRunSource as Source,DiscoveryResult as Result,DiscoveryRun as Run,DiscoveryReview as SourceReview,Case,CaseEntity
from ...migration_state import supports_revision
from ...attribution.domain import fingerprint,json_safe
from ..domain import SchemaUnavailable,DiscoveryError,Conflict,NotFound,clean
from ..service import row_data,atomic
from .models import Candidate,Review

def ensure(db):
    if not supports_revision(db.connection(),'20260928_01') or not {'discovery_broad_candidates','discovery_broad_candidate_reviews'}<=set(inspect(db.connection()).get_table_names()):raise SchemaUnavailable('Broad Discovery requires migration 20260928_01')

def capture_candidates(db,observation,source,subject):
    ensure(db)
    snap=observation.source_snapshot
    for item in snap.get('candidates',[]):
        identity=fingerprint({'observation':observation.id,'kind':item['kind'],'value':item['value']})
        if not db.get(Candidate,identity):db.add(Candidate(id=identity,observation_id=observation.id,chain=subject.namespace,wallet=subject.canonical_value,
            provider=source.source_id,kind=item['kind'],value=item['value'],canonical_url=observation.source_url,material=clean(item),status='unreviewed',version=1))
    db.flush()

class BroadService:
    def __init__(self,db,discovery):self.db=db;self.discovery=discovery;ensure(db)
    def snapshot(self,identifier):
        # Explicit transaction gives consistent memberships/reviews for Case pins.
        connection=self.db.connection()
        if not connection.connection.driver_connection.in_transaction:connection.exec_driver_sql('BEGIN')
        run=self.discovery.read_run(identifier)
        stored=self.db.get(Run,identifier)
        if not stored.request_snapshot.get('execution_policy',{}).get('broad'):raise DiscoveryError('Not a Broad Discovery run')
        rows=self.db.execute(select(Observation,Source,Item,Result).join(Item,Item.observation_id==Observation.id).join(Source,Source.id==Item.run_source_id).join(Result,Result.id==Observation.result_id).where(Source.run_id==identifier).order_by(Source.ordinal,Item.ordinal).limit(201)).all()
        if len(rows)>200:raise DiscoveryError('Broad run exceeds aggregate bound')
        ids={o.id for o,_,_,_ in rows}
        candidates=[row_data(c) for c in self.db.scalars(select(Candidate).where(Candidate.observation_id.in_(ids)).order_by(Candidate.kind,Candidate.value,Candidate.id))] if ids else []
        reviews=[row_data(r) for r in self.db.scalars(select(Review).where(Review.candidate_id.in_([c['id'] for c in candidates])).order_by(Review.candidate_id,Review.sequence))] if candidates else []
        groups={}
        for observation,source,item,result in rows:
            snap=observation.source_snapshot;url=observation.source_url
            key=snap.get('canonical_url') or url or 'result:'+result.id
            entry=groups.setdefault(key,{'canonical_url':url,'result_ids':[],'observations':[]})
            if result.id not in entry['result_ids']:entry['result_ids'].append(result.id)
            entry['observations'].append({**row_data(observation),'provider':source.source_id,'transform_id':source.transform_id,'cache_state':item.inclusion_kind,
                'rank':snap.get('rank',item.rank),'result_version':result.version,'review_status':result.review_status,'review_required':result.material_revision>result.reviewed_material_revision,
                'first_seen_at':json_safe(result.first_seen_at),'last_seen_at':json_safe(result.last_seen_at)})
        source_reviews=[row_data(r) for r in self.db.scalars(select(SourceReview).where(SourceReview.observation_id.in_(ids)).order_by(SourceReview.result_id,SourceReview.sequence))] if ids else []
        groups=[groups[k] for k in sorted(groups)]
        data={'schema_version':1,'run':run,'query':{'type':'EXACT_WALLET','chain':run['subject']['namespace'],'wallet':run['subject']['canonical_value'],'text':'"'+run['subject']['canonical_value']+'"'},
            'bounds':{'max_providers':6,'aggregate_results':200,'run_deadline_seconds':60},'groups':groups,'candidates':candidates,'candidate_reviews':reviews,'source_reviews':source_reviews,
            'providers_requested':[{k:s[k] for k in ('transform_id','source_id','transform_version','source_version','status','coverage','requests_attempted','returned_count','quota_snapshot')} for s in run['sources']],
            'partial':run['status'] in ('partial','failed','cancelled','interrupted'),'truncated':any(s['coverage'] in ('provider_incomplete','limit_reached') for s in run['sources'])}
        data=json_safe(data);data['source_data_fingerprint']=fingerprint(data)
        return data
    @atomic
    def review_candidate(self,identifier,status,note,version):
        if status not in ('unreviewed','relevant','irrelevant') or not isinstance(note,str) or not note.strip() or len(note)>2000:raise DiscoveryError('Candidate review requires status and note')
        c=self.db.get(Candidate,identifier)
        if not c:raise NotFound('Candidate not found')
        result=self.db.execute(update(Candidate).where(Candidate.id==identifier,Candidate.version==version).values(status=status,version=version+1))
        if result.rowcount!=1:raise Conflict('Candidate review changed; reload')
        self.db.add(Review(id=str(uuid4()),candidate_id=identifier,sequence=version,status=status,note=clean(note.strip()),created_at=datetime.now(timezone.utc).isoformat()))
        self.db.flush();self.db.refresh(c);return row_data(c)
    @atomic
    def pin(self,case_id,run_id):
        if not self.db.get(Case,case_id):raise NotFound('Case not found')
        snapshot=self.snapshot(run_id)
        if snapshot['run']['status'] in ('queued','running'):raise Conflict('Wait for terminal run before pinning')
        row=CaseEntity(case_id=case_id,entity_type='broad_discovery',entity_ref=run_id,metadata_json={'broad_discovery_pin':snapshot})
        self.db.add(row);self.db.flush();return row_data(row)

def report_lines(entities):
    import json
    lines=[]
    for entity in entities:
        if entity.get('entity_type')=='broad_discovery':
            pin=entity.get('metadata_json',{}).get('broad_discovery_pin')
            lines.extend(['','## Pinned Broad Discovery','Public source metadata and analyst review, not verified identity or ownership.',json.dumps(pin,ensure_ascii=True,sort_keys=True)])
    return lines
