"""Read-only, bounded projection of immutable run membership. No execution."""
from ..chain_types import ChainName
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from ..models import (DiscoveryRun as Run, DiscoverySubject as Subject,
    DiscoveryResult as Result, DiscoveryObservation as Observation,
    DiscoveryRunItem as Item, DiscoveryRunSource as Source, DiscoveryPromotion as Promotion)
from ..attribution.domain import SchemaUnavailable as AttributionUnavailable
from .domain import clean, DiscoveryError
from .promotion import PromotionService, PromotionUnavailable


class GraphRoot(BaseModel):
    id: str
    type: Literal['wallet'] = 'wallet'
    subject_id: str
    chain: ChainName
    address: str


class GraphResult(BaseModel):
    id: str
    type: Literal['label_annotation','code_location','ens_name','source_page','public_annotation']
    result_id: str
    observation_id: str
    observation_fingerprint: str
    title: str
    subtitle: str
    source_id: str
    transform_id: str
    predicate: Literal['locally_labeled_as','repository_contains','resolves_to','mentions_wallet','publicly_labeled_as']
    summary: str
    excerpt: str | None
    url: str | None
    public_annotation: dict | None = None
    manual_source: dict | None = None
    captured_at: datetime | None = None
    label_type: str | None = None
    annotation_source: str | None = None
    confidence: float | None = None
    repository: str | None = None
    path: str | None = None
    blob_sha: str | None = None
    primary_name: str | None = None
    namespace: str | None = None
    wallet: str | None = None
    verification: str | None = None
    verification_method: str | None = None
    universal_resolver: str | None = None
    resolver: str | None = None
    reverse_resolver: str | None = None
    run_observation_count: int
    first_retrieved_at: datetime
    last_retrieved_at: datetime
    current_observation_count: int
    current_review_status: Literal['unreviewed','relevant','irrelevant']
    current_review_required: bool
    promotion_count: int | None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    result_id: str
    predicate: Literal['locally_labeled_as','repository_contains','resolves_to','mentions_wallet','publicly_labeled_as']


class GraphUnrenderedResult(BaseModel):
    """Known stored material awaiting a separately implemented presentation."""
    result_id: str
    observation_id: str
    endpoint_type: Literal['ens_name'] = 'ens_name'
    reason: Literal['presentation_not_implemented'] = 'presentation_not_implemented'


class GraphRead(BaseModel):
    run_id: str
    root: GraphRoot
    items: list[GraphResult] = Field(max_length=100)
    edges: list[GraphEdge] = Field(max_length=100)
    total: int
    limit: int
    offset: int
    next_offset: int | None
    promotion_available: bool
    unrendered_results: list[GraphUnrenderedResult] = Field(default_factory=list,max_length=100)


def graph_summary(service, run_id, *, limit=100, offset=0, metadata_only=False):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise DiscoveryError('Invalid graph pagination')
    db=service.db
    run=service._get(Run,run_id)
    subject=service._get(Subject,run.subject_id)
    root=dict(id='discovery:subject:'+subject.id,subject_id=subject.id,type='wallet',
              chain=subject.namespace,address=subject.canonical_value)
    # Pick a deterministic included observation, never the globally latest one.
    members=select(Observation.id.label('observation_id'),Observation.result_id,
        func.row_number().over(partition_by=Observation.result_id,
            order_by=(Source.ordinal,Item.ordinal,Observation.id)).label('position'))\
        .join(Item,Item.observation_id==Observation.id).join(Source,Source.id==Item.run_source_id)\
        .where(Source.run_id==run_id).subquery()
    total=db.scalar(select(func.count()).select_from(members).where(members.c.position==1))
    rows=db.execute(select(Result,Observation,Source).join(members,members.c.result_id==Result.id)
        .join(Observation,Observation.id==members.c.observation_id)
        .join(Source,Source.id==Observation.execution_id).where(members.c.position==1)
        .order_by(Result.predicate,Result.id).limit(limit).offset(offset)).all()
    ids=[r.id for r,_,_ in rows]
    included={};counts={};promotions={}
    if ids:
        included={r[0]:r[1:] for r in db.execute(select(Observation.result_id,
            func.count(func.distinct(Observation.id)),func.min(Observation.retrieved_at),func.max(Observation.retrieved_at))
            .join(Item,Item.observation_id==Observation.id).join(Source,Source.id==Item.run_source_id)
            .where(Source.run_id==run_id,Observation.result_id.in_(ids)).group_by(Observation.result_id))}
        counts=dict(db.execute(select(Observation.result_id,func.count()).where(Observation.result_id.in_(ids))
            .group_by(Observation.result_id)).all())
    promotion_available=True
    try:PromotionService(db,metadata_only=metadata_only,registry=service.registry)
    except (PromotionUnavailable,AttributionUnavailable):promotion_available=False
    if ids and promotion_available:
        promotions=dict(db.execute(select(Observation.result_id,func.count(Promotion.id))
            .join(Promotion,Promotion.observation_id==Observation.id)
            .where(Observation.result_id.in_(ids)).group_by(Observation.result_id)).all())
    ens_ids=[r.from_subject_id for r,o,_ in rows if (r.predicate,o.kind)==('resolves_to','name_service_record')]
    ens_subjects={s.id:s for s in db.scalars(select(Subject).where(Subject.id.in_(ens_ids)))} if ens_ids else {}
    nodes=[];edges=[];unrendered=[]
    for result,observation,source in rows:
        local=(result.predicate,observation.kind)==('locally_labeled_as','local_label_snapshot')
        code=(result.predicate,observation.kind)==('repository_contains','code_search_result')
        from .ens import verified_material
        ens=verified_material(result,observation,source,subject,ens_subjects.get(result.from_subject_id))
        from .manual_source import is_manual_material
        manual=is_manual_material(result,observation,source)
        from .graphsense import public_material
        endpoint=db.get(Subject,result.to_subject_id) if result.predicate=='publicly_labeled_as' else None
        public=public_material(result,observation,source,subject,endpoint)
        if not (local or code or ens or manual or public):
            endpoint=ens_subjects.get(result.from_subject_id)
            if (result.predicate,observation.kind)==('resolves_to','name_service_record') and endpoint and (endpoint.kind,endpoint.namespace)==('ens_name','ethereum') and subject.namespace=='ethereum' and result.to_subject_id==subject.id:
                # Retain page membership/counts and inspectable IDs, without
                # inventing an ENS node or flipping the literal edge direction.
                unrendered.append(dict(result_id=result.id,observation_id=observation.id))
                continue
            raise DiscoveryError('Unsupported Discovery graph relationship')
        snapshot=clean(observation.source_snapshot);record=snapshot.get('record',{})
        count,first,last=included[result.id]
        node=dict(id='discovery:result:'+result.id,type='label_annotation' if local else 'ens_name' if ens else 'source_page' if manual else 'public_annotation' if public else 'code_location',
            result_id=result.id,observation_id=observation.id,observation_fingerprint=observation.content_sha256,
            title=record.get('label',observation.title) if local else snapshot.get('repository_full_name',observation.title),
            subtitle=record.get('source','') if local else snapshot.get('file_path',''),
            source_id=source.source_id,transform_id=source.transform_id,predicate=result.predicate,
            summary=observation.summary,excerpt=observation.excerpt,url=observation.source_url,
            run_observation_count=count,first_retrieved_at=first,last_retrieved_at=last,
            current_observation_count=counts[result.id],current_review_status=result.review_status,
            current_review_required=result.reviewed_material_revision>0 and result.material_revision>result.reviewed_material_revision,
            promotion_count=promotions.get(result.id,0) if promotion_available else None)
        if local:node.update(label_type=record.get('type'),annotation_source=record.get('source'),confidence=record.get('confidence'))
        elif public:node.update(title=snapshot['tag']['label'],subtitle='GraphSense / Third-party public annotation',public_annotation=snapshot,repository=snapshot['repository'],path=snapshot['file_path'],blob_sha=snapshot['blob_sha'])
        elif manual:node.update(title=snapshot.get('title') or 'Manual source observation',subtitle=snapshot['source_type'],manual_source=snapshot,captured_at=observation.created_at)
        elif ens:
            node.update(title=snapshot['primary_name'],subtitle='Ethereum / Forward verified',**{key:snapshot.get(key) for key in ('primary_name','namespace','wallet','verification','verification_method','universal_resolver','resolver','reverse_resolver')})
        else:node.update(repository=snapshot.get('repository_full_name'),path=snapshot.get('file_path'),blob_sha=snapshot.get('blob_sha'))
        nodes.append(clean(node))
        # Preserve the architecture's literal direction, not query direction.
        edges.append(dict(id=result.id,result_id=result.id,predicate=result.predicate,
            source=root['id'] if local or public else node['id'],target=node['id'] if local or public else root['id']))
    return GraphRead.model_validate(dict(run_id=run_id,root=clean(root),items=nodes,edges=edges,total=total,
        limit=limit,offset=offset,next_offset=offset+limit if offset+limit<total else None,
        promotion_available=promotion_available,unrendered_results=unrendered))
