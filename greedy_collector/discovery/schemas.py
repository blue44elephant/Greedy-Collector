"""Bounded Discovery API and executor contracts. No executable input fields."""
from ..chain_types import ChainName
from datetime import date,datetime
from enum import Enum
from typing import Generic,TypeVar,Literal
from pydantic import BaseModel,ConfigDict,Field,JsonValue,StrictInt,model_validator
from . import enums as e
from .domain import ObservationInput,canonical_subject

RunState=Enum('RunState',{x:x for x in e.RUN_STATES},type=str)
SourceState=Enum('SourceState',{x:x for x in e.SOURCE_STATES},type=str)
ReviewState=Enum('ReviewState',{x:x for x in e.REVIEWS},type=str)
CostClass=Enum('CostClass',{x:x for x in e.COSTS},type=str)
SourceError=Enum('SourceError',{x:x for x in e.ERRORS},type=str)
Predicate=Enum('Predicate',{x:x for x in e.PREDICATES},type=str)
CandidateKind=Enum('CandidateKind',{x:x for x in e.RESULT_KINDS},type=str)
Mode=Literal['local','manual','automated']
Eligibility=Literal['eligible','not_implemented','configuration_unavailable','retention_not_permitted','budget_exhausted','disabled']

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')

class SubjectInput(Input):
    chain:ChainName
    address:str=Field(min_length=1,max_length=128)
    @model_validator(mode='after')
    def normalize(self):
        self.address=canonical_subject('blockchain_address',self.chain,self.address)['canonical_value']
        return self

class Parameters(Input):
    max_results:int|None=Field(default=None,strict=True,ge=1,le=100)

class Selection(Input):
    transform_id:str=Field(min_length=1,max_length=128)
    source_id:str|None=Field(default=None,min_length=1,max_length=128)
    parameters:Parameters=Field(default_factory=Parameters)

class Budget(Input):
    allow_free_local:bool=True
    allow_free_remote:bool=True
    allow_limited_free:bool=True
    # Each source has an explicit integer unit; do not sum unlike currencies/units.
    paid_units:dict[str,StrictInt]=Field(default_factory=dict,max_length=3)
    @model_validator(mode='after')
    def units(self):
        if any(not isinstance(k,str) or not 1<=len(k)<=128 or type(v) is not int or not 0<=v<=1000000 for k,v in self.paid_units.items()):raise ValueError('Invalid source budget')
        return self

class PlanRequest(Input):
    subject:SubjectInput
    selections:list[Selection]=Field(min_length=1,max_length=3)
    refresh:bool=False
    budget:Budget=Field(default_factory=Budget)

class RunCreate(PlanRequest):
    expected_plan_fingerprint:str=Field(pattern=r'^[0-9a-f]{64}$')

class VersionInput(Input):
    expected_version:int=Field(strict=True,ge=1)

class ReviewInput(VersionInput):
    observation_id:str=Field(min_length=1,max_length=36)
    expected_source_fingerprint:str=Field(pattern=r'^[0-9a-f]{64}$')
    status:ReviewState
    reason:str=Field(min_length=1,max_length=4000)

class SubjectRead(BaseModel):
    id:str|None=None
    kind:str
    namespace:str
    canonical_value:str
    display_value:str
    identity_sha256:str

class SourceCapability(BaseModel):
    id:str
    version:int
    display_name:str
    category:str
    mode:Mode
    cost_class:CostClass
    configured:bool
    credential_required:bool
    executable:bool
    storage_allowed:bool
    rate_limit_per_minute:int
    cost_unit:str
    retention_policy_id:str
    provenance_note:str

class TransformCapability(BaseModel):
    capture_only:bool=False
    id:str
    version:int
    display_name:str
    description:str
    source_ids:list[str]
    input_types:list[str]
    chains:list[ChainName]
    output_types:list[str]
    result_kinds:list[CandidateKind]
    predicates:list[Predicate]
    observation_kinds:list[str]
    mode:Mode
    cost_class:CostClass
    implemented:bool
    executable:bool
    configured:bool
    max_results:int
    max_requests:int
    max_bytes:int
    deadline_seconds:int
    cache_seconds:int
    unavailable_reason:Eligibility|None=None

class PlannedSource(BaseModel):
    transform_id:str
    source_id:str
    transform_version:int
    source_version:int
    parameters:Parameters
    query_fingerprint:str
    eligibility:Eligibility
    cost_class:CostClass
    cost_unit:str
    max_requests:int
    max_units:int
    cache_seconds:int

class PlanRead(BaseModel):
    subject:SubjectRead
    selections:list[PlannedSource]
    budget:Budget
    refresh:bool
    fingerprint:str
    expires_at:datetime

class Accounting(BaseModel):
    requests_reserved:int
    requests_attempted:int
    units_reserved:int
    units_consumed:int
    cost_unit:str
    quota_snapshot:dict[str,JsonValue]

class ManualAction(Input):
    source_id:Literal['google']
    source_name:Literal['Google']
    query:str=Field(min_length=3,max_length=130)
    url:str=Field(pattern=r'^https://www\.google\.com/search\?q=',max_length=512)
    status:Literal['manual_action_available']
    note:str=Field(min_length=1,max_length=1000)

class SourceRead(Accounting):
    manual_actions:list[ManualAction]=Field(default_factory=list,max_length=1)
    id:str
    transform_id:str
    transform_version:int
    source_id:str
    source_version:int
    ordinal:int
    status:SourceState
    started_at:datetime|None
    completed_at:datetime|None
    expires_at:datetime|None
    cache_from_id:str|None
    coverage:Literal['bounded','provider_incomplete','limit_reached','unknown']
    returned_count:int
    provider_total:int|None
    error_code:SourceError|None
    retry_after_at:datetime|None

class RunRead(BaseModel):
    id:str
    subject_id:str
    subject:SubjectRead
    status:RunState
    version:int
    actor_ref:str
    idempotency_key:str
    budget:Budget
    sources:list[SourceRead]
    returned_count:int
    created_at:datetime
    started_at:datetime|None
    completed_at:datetime|None
    deadline_at:datetime
    cancel_requested_at:datetime|None
    archived_at:datetime|None

class RunSummary(BaseModel):
    id:str
    subject_id:str
    status:RunState
    version:int
    created_at:datetime
    started_at:datetime|None
    completed_at:datetime|None
    archived_at:datetime|None

class ResultRead(BaseModel):
    id:str
    query_subject_id:str
    kind:CandidateKind
    predicate:Predicate
    from_subject_id:str
    to_subject_id:str|None
    fact_key:dict[str,JsonValue]
    identity_sha256:str
    first_seen_at:datetime
    last_seen_at:datetime
    material_revision:int
    reviewed_material_revision:int
    review_status:ReviewState
    new_material_since_review:bool
    version:int

class ObservationSummary(BaseModel):
    created_at:datetime
    id:str
    result_id:str
    execution_id:str
    source_id:str
    transform_id:str
    kind:str
    title:str
    summary:str
    source_url:str|None
    source_locator:str|None
    verification:str
    observed_at:datetime|None
    observed_on:date|None
    retrieved_at:datetime
    content_sha256:str

class ObservationRead(ObservationSummary):
    source_record_key:str
    excerpt:str|None
    excerpt_complete:bool
    match_context:dict[str,JsonValue]
    source_class:str
    published_at:datetime|None
    published_on:date|None
    source_snapshot:dict[str,JsonValue]
    origin_label_id:str|None
    origin_match_id:str|None

class RunResult(BaseModel):
    result:ResultRead
    observation:ObservationSummary
    source_run_id:str
    inclusion_kind:Literal['retrieved','local','cache']
    ordinal:int
    provenance_count:int

class ReviewRead(BaseModel):
    id:str
    result_id:str
    observation_id:str
    sequence:int
    material_revision:int
    status:ReviewState
    reason:str
    actor_ref:str
    occurred_at:datetime

class ReviewResult(BaseModel):
    result:ResultRead
    review:ReviewRead

T=TypeVar('T')
class Page(BaseModel,Generic[T]):
    items:list[T]
    total:int
    limit:int
    offset:int
    next_offset:int|None

class DiscoveryErrorDetail(BaseModel):
    code:Literal['invalid_request','not_found','conflict','schema_unavailable','storage_unavailable','internal_error','origin_rejected']
    message:str
class DiscoveryErrorResponse(BaseModel):
    detail:DiscoveryErrorDetail

class Endpoint(Input):
    kind:str
    namespace:str
    value:str=Field(min_length=1,max_length=2048)

class Candidate(Input):
    kind:CandidateKind
    predicate:Predicate
    from_:Endpoint=Field(alias='from')
    to:Endpoint
    fact_key:dict[str,JsonValue]
    observation:ObservationInput

class GitHubResourceQuota(Input):
    limit:int|None=Field(default=None,strict=True,ge=0)
    remaining:int|None=Field(default=None,strict=True,ge=0)
    reset_at:datetime|None=None
    retry_after_at:datetime|None=None

class QuotaReport(Input):
    github_resources:dict[Literal['code_search','search','core'],GitHubResourceQuota]|None=None
    # Closed source diagnostic persisted in the existing execution metadata.
    diagnostic:Literal['empty_primary_name','reverse_forward_mismatch','ccip_read_unsupported','resolver_not_found','resolver_not_contract','unsupported_resolver_profile','resolver_error','rpc_error','malformed_abi','invalid_ens_name','normalizer_unavailable','normalizer_timeout','normalizer_protocol_error','ens_configuration_unavailable']|None=None
    limit:int|None=Field(default=None,strict=True,ge=0)
    resource:Literal['code_search','search','core']|None=None
    remaining:int|None=Field(default=None,strict=True,ge=0)
    reported_units:int|None=Field(default=None,strict=True,ge=0,le=1000000)
    reset_at:datetime|None=None
    retry_after_at:datetime|None=None

class Batch(Input):
    records:list[Candidate]=Field(default_factory=list,max_length=100)
    coverage:Literal['bounded','provider_incomplete','limit_reached','unknown']='bounded'
    provider_total:int|None=Field(default=None,strict=True,ge=0)
    quota:QuotaReport|None=None
