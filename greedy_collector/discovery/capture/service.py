"""Immutable source material with separate append-only review/promotion history."""
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, func, inspect
from ...models import DiscoveryObservation, DiscoveryResult, DiscoverySubject, DiscoveryRunSource, Case, CaseEntity
from ...migration_state import supports_revision
from ...attribution.service import AttributionService, Evidence, ACTOR
from ...attribution.domain import EvidenceContentInput, LinkInput, fingerprint, apply_evidence_quality
from ..domain import DiscoveryError, Conflict, NotFound, SchemaUnavailable, clean
from ..service import atomic, row_data
from ..broad import is_web_source
from ..broad.providers import DiscoveryQuery, exact_match
from .models import PublicSourceCapture as Capture, CaptureReview as Review, CapturePromotion as Promotion

REVISION='20260929_01_public_source_capture'

def ensure(db):
    if not supports_revision(db.connection(),REVISION) or not set(c.__tablename__ for c in (Capture,Review,Promotion)) <= set(inspect(db.connection()).get_table_names()):
        raise SchemaUnavailable('Explicit source capture migration required')

class CaptureService:
    def __init__(self,db):self.db=db;ensure(db)
    def origin(self,observation_id):
        o=self.db.get(DiscoveryObservation,observation_id)
        if not o:raise NotFound('Observation not found')
        r=self.db.get(DiscoveryResult,o.result_id);source=self.db.get(DiscoveryRunSource,o.execution_id)
        subject=self.db.get(DiscoverySubject,r.query_subject_id)
        if o.kind!='search_result' or not is_web_source(source.transform_id,source.source_id) or not o.source_url:
            raise DiscoveryError('Select a public search observation')
        return clean(dict(observation_id=o.id,result_id=r.id,run_id=source.run_id,chain=subject.namespace,wallet=subject.canonical_value,
            requested_url=o.source_url,observation_fingerprint=o.content_sha256,provider=source.source_id,
            search_query=o.source_snapshot.get('query'),search_exact_match=o.source_snapshot.get('exact_match'),
            search_retrieved_at=o.retrieved_at,search_title=o.title))
    def get(self,identifier):
        row=self.db.get(Capture,identifier)
        if not row:raise NotFound('Capture not found')
        return row
    def latest_review(self,identifier):
        row=self.db.scalar(select(Review).where(Review.capture_id==identifier).order_by(Review.sequence.desc()).limit(1))
        return row_data(row) if row else {'sequence':0,'status':'unreviewed','note':'','created_at':None}
    def read(self,identifier,*,text=True):
        row=self.get(identifier)
        material=dict(row.material)
        if not text:material.pop('text',None)
        return {**material,'review':self.latest_review(identifier)}
    def page(self,observation_id,limit=10,offset=0):
        self.origin(observation_id)
        query=select(Capture.id).where(Capture.observation_id==observation_id)
        total=self.db.scalar(select(func.count()).select_from(query.subquery()))
        ids=self.db.scalars(query.order_by(Capture.retrieved_at.desc(),Capture.id).offset(offset).limit(limit)).all()
        return dict(items=[self.read(i,text=False) for i in ids],total=total,limit=limit,offset=offset,next_offset=offset+limit if offset+limit<total else None)
    @atomic
    def store(self,origin,retrieved):
        current=self.origin(origin['observation_id'])
        if current!=origin:raise Conflict('Origin changed')
        previous=self.db.scalar(select(Capture).where(Capture.normalized_url==origin['requested_url'],Capture.status=='captured').order_by(Capture.retrieved_at.desc(),Capture.id.desc()).limit(1))
        values=asdict(retrieved);body=values.pop('body')
        present=exact_match(DiscoveryQuery(origin['chain'],origin['wallet']),values['text']) if values['status']=='captured' else None
        identifier=str(uuid4())
        material={**values,'id':identifier,'requested_url':origin['requested_url'],'origin':origin,
            'wallet_present_in_capture':present,'previous_capture_id':previous.id if previous else None,
            'change_state':('UNCHANGED' if previous.body_sha256==values['body_sha256'] else 'CHANGED') if previous and values['status']=='captured' else 'FIRST_CAPTURE' if values['status']=='captured' else 'NOT_COMPARED'}
        row=Capture(id=identifier,observation_id=origin['observation_id'],result_id=origin['result_id'],normalized_url=origin['requested_url'],
            retrieved_at=values['retrieved_at'],body_sha256=values['body_sha256'],status=values['status'],material=material,raw_body=body)
        self.db.add(row);self.db.flush()
        return self.read(identifier)
    @atomic
    def review(self,identifier,payload):
        self.get(identifier);previous=self.latest_review(identifier)
        if previous['sequence']!=payload.expected_version:raise Conflict('Review changed')
        self.db.add(Review(id=str(uuid4()),capture_id=identifier,sequence=previous['sequence']+1,status=payload.status,
            note=clean(payload.note.strip()),created_at=datetime.now(timezone.utc).isoformat()))
        self.db.flush();return self.read(identifier)
    def snapshot(self,identifier,excerpt=None):
        row=self.get(identifier);data=self.read(identifier,text=False)
        data.pop('review')
        if excerpt is not None:
            if not excerpt.strip() or excerpt not in row.material['text']:raise DiscoveryError('Select a literal excerpt from the captured text')
        return {'source_subsystem':'Greedy Collector Public Source Capture','capture':data,
            'review':self.latest_review(identifier),'selected_excerpt':excerpt}
    def preview(self,identifier):
        snapshot=self.snapshot(identifier);capture=snapshot['capture'];origin=capture['origin']
        return dict(capture_id=identifier,result_id=origin['result_id'],chain=origin['chain'],address=origin['wallet'],
            eligible=capture['status']=='captured' and snapshot['review']['status']=='relevant',
            context_only=capture['wallet_present_in_capture'] is not True,source_fingerprint=fingerprint(snapshot),snapshot=snapshot)
    @atomic
    def pin(self,identifier,case_id,payload):
        if not self.db.get(Case,case_id):raise NotFound('Case not found')
        preview=self.preview(identifier)
        if payload.expected_source_fingerprint!=preview['source_fingerprint']:raise Conflict('Capture review changed')
        if self.get(identifier).status!='captured':raise DiscoveryError('Only successful captures can be pinned')
        snapshot=self.snapshot(identifier,payload.excerpt)
        row=CaseEntity(case_id=case_id,entity_type='public_source_capture',entity_ref=identifier,metadata_json={'public_source_capture_pin':snapshot})
        self.db.add(row);self.db.flush();return row_data(row)
    @atomic
    def promote(self,identifier,payload):
        preview=self.preview(identifier)
        if not preview['eligible']:raise DiscoveryError('Review a successful capture as Relevant first')
        if preview['source_fingerprint']!=payload.expected_source_fingerprint:raise Conflict('Review changed; reload')
        if self.db.scalar(select(Promotion.id).where(Promotion.capture_id==identifier,Promotion.claim_id==payload.claim_id)):
            raise Conflict('Capture already promoted to this claim')
        snapshot=self.snapshot(identifier,payload.excerpt);capture=snapshot['capture'];origin=capture['origin']
        svc=AttributionService(self.db);claim=svc._claim(payload.claim_id)
        if (claim.chain,claim.subject_ref)!=(origin['chain'],origin['wallet']):raise DiscoveryError('Choose a claim for the exact chain and wallet')
        if claim.version!=payload.expected_claim_version:raise Conflict('Claim changed')
        link=LinkInput.model_validate(payload.link).model_dump()
        if preview['context_only'] and (link['stance'],link['directness'])!=('context','context'):raise DiscoveryError('Wallet-absent capture is contextual only')
        values=EvidenceContentInput.model_validate(dict(evidence_type='discovery_snapshot',title=capture['title'] or 'Public source capture',
            summary='Explicit public source capture; wallet presence does not prove ownership.',excerpt=payload.excerpt,
            source_name='Greedy Collector public source capture',source_url=capture['final_url'],source_locator='public-source-capture:'+identifier,
            origin='public_osint',observed_on=capture['retrieved_at'][:10],analyst_note=snapshot['review']['note'],metadata_json=snapshot)).model_dump()
        values.update(collection_method='discovery_snapshot',origin_discovery_observation_id=origin['observation_id'],origin_label_id=None,origin_match_id=None)
        values=apply_evidence_quality(values,payload.source_reliability,payload.reliability_rationale)
        digest=fingerprint(values)
        ev=self.db.scalar(select(Evidence).where(Evidence.content_sha256==digest,
            Evidence.source_locator=='public-source-capture:'+identifier,
            Evidence.origin_discovery_observation_id==origin['observation_id']).order_by(Evidence.id).limit(1))
        if ev is None:
            ev=Evidence(**values,captured_by=ACTOR,content_sha256=digest);self.db.add(ev);self.db.flush()
            svc._event(ev,'created','Reviewed public capture explicitly promoted with analyst-selected excerpt')
        linked=svc._link(claim,ev.id,link,payload.expected_claim_version)
        row=Promotion(id=str(uuid4()),capture_id=identifier,claim_id=claim.id,evidence_id=ev.id,link_id=linked['link']['id'],source_fingerprint=preview['source_fingerprint'],created_at=datetime.now(timezone.utc).isoformat())
        self.db.add(row);self.db.flush()
        return {'promotion':row_data(row),'claim':linked['claim']}
