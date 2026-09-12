"""Typed AT-2 transport contracts; AT-1 input validators remain authoritative."""
from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, JsonValue

from . import domain, enums

EntityType = Literal[*enums.ENTITY_TYPES]
Relationship = Literal[*enums.RELATIONSHIPS]
Assessment = Literal[*enums.ASSESSMENTS]
Stance = Literal[*enums.STANCES]
Directness = Literal[*enums.DIRECTNESS]
Origin = Literal[*enums.ORIGINS]
EvidenceType = Literal[*enums.EVIDENCE_TYPES]
Reliability = Literal[*enums.RELIABILITIES]
Chain = Literal['bitcoin', 'ethereum']
Identifier = Annotated[str, Field(min_length=1, max_length=36)]
Version = Annotated[int, Field(strict=True, ge=1, description='Current entity/claim version read by the analyst. Reload after HTTP 409.')]


class EntityCreate(domain.EntityInput):
    entity_type: EntityType = 'unknown'


class VersionAction(domain.Input):
    expected_version: Version
    reason: domain.Long


class EntityUpdate(VersionAction):
    # Full descriptor replacement is deliberate: PATCH updates this one component.
    descriptor: EntityCreate


class ClaimCreate(domain.ClaimInput):
    relationship: Relationship


class ScopeUpdate(VersionAction):
    scope: domain.ScopeInput


class AssessmentUpdate(domain.Input):
    expected_version: Version
    assessment: Assessment
    rationale: domain.Long
    reviewed_link_ids: list[Identifier] = Field(max_length=10000, description='Every current active link ID; gather all evidence pages.')
    acknowledged_contradictions: list[Identifier] = Field(max_length=10000, description='Explicitly acknowledged active contradicting link IDs; never defaulted by the server.')
    conflict_discussion: str = Field(default='', max_length=8000)
    source_verification: str = Field(default='', max_length=8000)


class EvidenceCreate(domain.EvidenceInput):
    evidence_type: Literal['official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'analyst_observation']
    origin: Literal['public_osint', 'analyst_added']
    source_reliability: Reliability = 'unassessed'


class LinkFields(domain.LinkInput):
    stance: Stance
    directness: Directness


class LinkCreate(domain.Input):
    expected_version: Version
    evidence_id: Identifier
    link: LinkFields


class CaptureAndLink(domain.Input):
    expected_version: Version
    evidence: EvidenceCreate
    link: LinkFields


class LinkUpdate(VersionAction):
    link: LinkFields


class EvidenceReplacement(CaptureAndLink):
    reason: domain.Long


class EntityRead(BaseModel):
    id: str
    canonical_name: str
    entity_type: EntityType
    description: str
    aliases: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int


class ClaimRead(BaseModel):
    id: str
    subject_type: Literal['wallet']
    chain: Chain
    subject_ref: str
    entity_id: str
    relationship: Relationship
    valid_from: date | None
    valid_to: date | None
    scope_note: str
    assessment: Assessment
    assessment_rationale: str
    assessed_at: datetime | None
    assessed_by: str | None
    needs_review: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int


class EvidenceRead(BaseModel):
    id: str
    evidence_type: EvidenceType
    title: str
    summary: str
    excerpt: str | None
    source_name: str
    source_url: str | None
    source_locator: str | None
    source_catalog_id: str | None
    origin: Origin
    collection_method: Literal[*enums.COLLECTION_METHODS]
    published_on: date | None
    observed_on: date | None
    captured_at: datetime
    captured_by: str
    analyst_note: str
    source_reliability: Reliability
    reliability_rationale: str
    origin_group: str | None
    origin_label_id: str | None
    origin_match_id: str | None
    metadata_json: dict[str, JsonValue]
    content_sha256: str


class LinkRead(BaseModel):
    id: str
    claim_id: str
    evidence_id: str
    stance: Stance
    directness: Directness
    rationale: str
    added_by: str
    added_at: datetime
    updated_at: datetime
    withdrawn_at: datetime | None


class EvidenceSummary(BaseModel):
    id: str
    title: str
    evidence_type: EvidenceType
    source_name: str
    source_url: str | None
    source_locator: str | None
    origin: Origin
    source_reliability: Reliability
    captured_at: datetime


class LinkDetail(LinkRead):
    evidence: EvidenceSummary


T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int
    next_offset: int | None


class StanceCounts(BaseModel):
    supports: int
    contradicts: int
    context: int


class ClaimDetail(ClaimRead):
    entity: EntityRead
    entity_archived: bool
    active_evidence_counts: StanceCounts
    active_evidence: Page[LinkDetail]


class LinkResult(BaseModel):
    claim: ClaimRead
    link: LinkRead


class ReplacementResult(LinkResult):
    withdrawn_link: LinkRead


class EventPayload(BaseModel):
    # Additional typed JSON keys retain AT-1 event-specific material.
    model_config = {'extra': 'allow'}
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    schema_version: Literal[1]
    before: JsonValue
    after: JsonValue


class EventRead(BaseModel):
    id: str
    entity_id: str | None
    claim_id: str | None
    evidence_id: str | None
    sequence: int
    event_type: Literal[*enums.EVENT_TYPES]
    actor_kind: Literal[*enums.ACTOR_KINDS]
    actor_ref: str
    occurred_at: datetime
    reason: str
    payload: EventPayload


class ErrorDetail(BaseModel):
    code: Literal['invalid_request', 'not_found', 'conflict', 'schema_unavailable', 'storage_unavailable', 'internal_error']
    message: str
    existing_id: str | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail
