"""Read-only, bounded projection of immutable run membership. No execution."""
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
    chain: Literal['bitcoin','ethereum']
    address: str


class GraphResult(BaseModel):
    id: str
    type: Literal['label_annotation','code_location']
    result_id: str
    observation_id: str
    observation_fingerprint: str
    title: str
    subtitle: str
    source_id: str
    transform_id: str
    predicate: Literal['locally_labeled_as','repository_contains']
    summary: str
    excerpt: str | None
    url: str | None
    label_type: str | None = None
    annotation_source: str | None = None
    confidence: float | None = None
    repository: str | None = None
    path: str | None = None
    blob_sha: str | None = None
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
    predicate: Literal['locally_labeled_as','repository_contains']


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
    nodes=[];edges=[]
    for result,observation,source in rows:
        local=(result.predicate,observation.kind)==('locally_labeled_as','local_label_snapshot')
        code=(result.predicate,observation.kind)==('repository_contains','code_search_result')
        if not (local or code):raise DiscoveryError('Unsupported Discovery graph relationship')
        snapshot=clean(observation.source_snapshot);record=snapshot.get('record',{})
        count,first,last=included[result.id]
        node=dict(id='discovery:result:'+result.id,type='label_annotation' if local else 'code_location',
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
        else:node.update(repository=snapshot.get('repository_full_name'),path=snapshot.get('file_path'),blob_sha=snapshot.get('blob_sha'))
        nodes.append(clean(node))
        # Preserve the architecture's literal direction, not query direction.
        edges.append(dict(id=result.id,result_id=result.id,predicate=result.predicate,
            source=root['id'] if local else node['id'],target=node['id'] if local else root['id']))
    return GraphRead.model_validate(dict(run_id=run_id,root=clean(root),items=nodes,edges=edges,total=total,
        limit=limit,offset=offset,next_offset=offset+limit if offset+limit<total else None,
        promotion_available=promotion_available))
