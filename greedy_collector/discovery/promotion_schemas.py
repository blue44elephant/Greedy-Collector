"""ED-6 IDs and analyst choices only; source snapshots are server-owned."""
from ..chain_types import ChainName
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from .schemas import Input
from ..attribution.schemas import LinkFields, ClaimRead, QualityFields
from ..attribution.domain import EvidenceContentInput

class PromotionInput(QualityFields):
    result_id: str = Field(min_length=1,max_length=36)
    claim_id: str = Field(min_length=1,max_length=36)
    expected_claim_version: int = Field(strict=True,ge=1)
    expected_source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    link: LinkFields

class PromotionEvidence(EvidenceContentInput):
    evidence_type: Literal['discovery_snapshot']
    origin: Literal['analyst_added','public_osint']
    collection_method: Literal['discovery_snapshot']
    origin_discovery_observation_id: str
    origin_label_id: None
    origin_match_id: None

class PromotionPreview(BaseModel):
    observation_id: str
    result_id: str
    observation_fingerprint: str
    source_fingerprint: str
    review_id: str | None
    review_status: Literal['unreviewed','relevant','irrelevant']
    eligible: bool
    reason: Literal['source_not_promotable','review_required'] | None
    context_only: bool
    chain: ChainName
    address: str
    evidence: PromotionEvidence

class PromotionRead(BaseModel):
    id: str
    observation_id: str
    claim_id: str
    evidence_id: str
    link_id: str
    source_fingerprint: str
    capture_fingerprint: str
    claim_version_before: int
    claim_version_after: int
    actor_ref: str
    created_at: datetime
    stance: Literal['supports','contradicts','context']
    directness: Literal['direct','indirect','context']
    rationale: str
    withdrawn_at: datetime | None

class PromotionResult(BaseModel):
    promotion: PromotionRead
    claim: ClaimRead
