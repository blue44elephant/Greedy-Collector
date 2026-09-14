"""Explicit case references with server-owned historical attribution pins."""
from sqlalchemy import select
from pydantic import ValidationError
from ..models import Case,CaseEntity,utcnow
from .service import AttributionService,Claim,Entity,Link,Evidence,atomic,row_data
from .domain import AttributionError,Conflict,SchemaUnavailable,json_safe
from .handoff import safe_snapshot
from . import schemas as s

KINDS=('entity','attribution_claim')


class CaseAttributionService(AttributionService):
    @atomic
    def add_reference(self,case_id,kind,target_id,*,expected_version):
        self._get(Case,case_id)
        if kind not in KINDS:raise AttributionError('Unsupported case attribution reference')
        existing=self.db.scalar(select(CaseEntity).where(CaseEntity.case_id==case_id,CaseEntity.entity_type==kind,CaseEntity.entity_ref==target_id))
        if existing:raise Conflict('This attribution reference is already in the case',existing.id)
        claim=self._claim(target_id,active=False) if kind=='attribution_claim' else None
        entity=self._entity(claim.entity_id if claim else target_id,active=False)
        target=claim if claim else entity
        if type(expected_version) is not int or target.version!=expected_version:raise Conflict('Attribution version changed; reload before pinning')
        links=self.db.scalars(select(Link).where(Link.claim_id==claim.id).order_by(Link.added_at,Link.id).limit(10001)).all() if claim else []
        if len(links)>10000:raise AttributionError('Claim exceeds the case pin limit of 10000 evidence links')
        pin=s.CaseAttributionPin.model_validate(safe_snapshot({
            'schema_version':1,'reference_type':kind,'target_id':target_id,'captured_at':utcnow(),
            'claim':row_data(claim) if claim else None,'entity':row_data(entity),'links':[row_data(link) for link in links]
        })).model_dump(mode='json')
        row=CaseEntity(case_id=case_id,entity_type=kind,entity_ref=target_id,metadata_json={'attribution_pin':pin})
        self.db.add(row);self.db.flush()
        return self._summaries([row])[0]

    def _summaries(self,rows):
        pins=[]
        for row in rows:
            try:pin=s.CaseAttributionPin.model_validate(row.metadata_json['attribution_pin']).model_dump(mode='json')
            except (KeyError,TypeError,ValidationError):raise AttributionError('Case attribution pin is unavailable or incompatible') from None
            pins.append((row,pin))
        claim_ids=[pin['target_id'] for _,pin in pins if pin['claim']]
        entity_ids=[pin['entity']['id'] for _,pin in pins]
        claims={r.id:row_data(r) for r in self.db.scalars(select(Claim).where(Claim.id.in_(claim_ids)))} if claim_ids else {}
        entities={r.id:row_data(r) for r in self.db.scalars(select(Entity).where(Entity.id.in_(entity_ids)))} if entity_ids else {}
        result=[]
        for row,pin in pins:
            current_claim=claims.get(pin['target_id']) if pin['claim'] else None;current_entity=entities.get(pin['entity']['id'])
            changed=not current_entity or current_entity['version']!=pin['entity']['version']
            if pin['claim']:changed=changed or not current_claim or current_claim['version']!=pin['claim']['version']
            counts={stance:sum(link['stance']==stance and not link['withdrawn_at'] for link in pin['links']) for stance in ('supports','contradicts','context')}
            result.append(s.CaseAttributionReference.model_validate(safe_snapshot({
                'id':row.id,'case_id':row.case_id,'pinned':pin,'current':{'claim':current_claim,'entity':current_entity,'changed':bool(changed)},'pinned_evidence_counts':counts
            })).model_dump(mode='json'))
        return result

    def list_references(self,case_id,*,limit=20,offset=0):
        self._get(Case,case_id)
        query=select(CaseEntity).where(CaseEntity.case_id==case_id,CaseEntity.entity_type.in_(KINDS)).order_by(CaseEntity.id)
        page=self._page(CaseEntity,query,limit=limit,offset=offset)
        ids=[row['id'] for row in page['items']]
        rows=list(self.db.scalars(query.where(CaseEntity.id.in_(ids)))) if ids else []
        page['items']=self._summaries(rows)
        return page

    def report_references(self,case_id):
        rows=list(self.db.scalars(select(CaseEntity).where(CaseEntity.case_id==case_id,CaseEntity.entity_type.in_(KINDS)).order_by(CaseEntity.id).limit(1001)))
        if len(rows)>1000:raise AttributionError('Case exceeds the report limit of 1000 attribution references')
        summaries=self._summaries(rows)
        ids={link['evidence_id'] for item in summaries for link in item['pinned']['links']}
        link_ids={link['id'] for item in summaries for link in item['pinned']['links']}
        # Bounded batches avoid per-claim/per-evidence/history request amplification.
        def fetch(model,identifiers):
            ordered=sorted(identifiers);result={}
            for start in range(0,len(ordered),200):
                result.update({row.id:row_data(row) for row in self.db.scalars(select(model).where(model.id.in_(ordered[start:start+200])))})
            return result
        captures=fetch(Evidence,ids);current_links=fetch(Link,link_ids)
        for item in summaries:
            item['evidence']=[]
            for link in item['pinned']['links']:
                if link['evidence_id'] not in captures:raise AttributionError('Pinned evidence is unavailable')
                if captures[link['evidence_id']]['origin'] not in ('public_osint','analyst_added'):
                    raise AttributionError('Restricted-origin evidence cannot be exported by this report workflow')
                item['evidence'].append({'pinned_link':link,'current_link':current_links.get(link['id']),'capture':safe_snapshot(captures[link['evidence_id']])})
        return {'status':'ready','generated_at':json_safe(utcnow()),'references':summaries}


def report_attribution(db,case_id):
    try:return CaseAttributionService(db).report_references(case_id)
    except SchemaUnavailable:
        return {'status':'unavailable','generated_at':json_safe(utcnow()),'references':[]}
