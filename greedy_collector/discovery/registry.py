"""Typed, code-owned descriptors only. ED-1 has no executable transforms."""
import os,re
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .domain import DiscoveryError,choice
from . import enums as e

class SourceDescriptor(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str=Field(pattern=r'^[a-z][a-z0-9_.-]{0,127}$')
    version:int=Field(default=1,strict=True,ge=1)
    display_name:str
    category:str
    mode:str
    cost_class:str
    credential_env:str|None=None
    rate_limit_per_minute:int=Field(default=1,strict=True,ge=1)
    cost_unit:str='request'
    retention_policy_id:str
    storage_allowed:bool=False
    provenance_note:str
    @model_validator(mode='after')
    def validate_descriptor(self):
        choice(self.mode,('local','manual','automated'));choice(self.cost_class,e.COSTS)
        if self.credential_env and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',self.credential_env):raise DiscoveryError('Invalid credential reference')
        for value in (self.display_name,self.category,self.retention_policy_id,self.provenance_note):
            if not value.strip():raise DiscoveryError('Descriptor text required')
        return self

class TransformDescriptor(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str=Field(pattern=r'^[a-z][a-z0-9_.-]{0,127}$')
    version:int=Field(default=1,strict=True,ge=1)
    display_name:str
    description:str
    source_ids:tuple[str,...]
    input_types:tuple[str,...]=('blockchain_address',)
    chains:tuple[str,...]=('bitcoin','ethereum')
    output_types:tuple[str,...]
    result_kinds:tuple[str,...]
    predicates:tuple[str,...]
    observation_kinds:tuple[str,...]
    mode:str
    cost_class:str
    matching_version:int=Field(default=1,strict=True,ge=1)
    max_results:int=Field(default=100,strict=True,ge=1,le=100)
    max_requests:int=Field(default=1,strict=True,ge=0,le=12)
    max_bytes:int=Field(default=1048576,strict=True,ge=1,le=1048576)
    deadline_seconds:int=Field(default=60,strict=True,ge=1,le=60)
    cache_seconds:int=Field(default=0,strict=True,ge=0,le=86400)
    implemented:bool=False
    @model_validator(mode='after')
    def validate_descriptor(self):
        if self.implemented:raise DiscoveryError('ED-1 transforms are descriptor-only')
        if self.input_types!=('blockchain_address',):raise DiscoveryError('Only wallet input is enabled')
        if not self.source_ids or len(set(self.source_ids))!=len(self.source_ids):raise DiscoveryError('Unique source references required')
        if not self.chains or not self.display_name.strip() or not self.description.strip():raise DiscoveryError('Descriptor contract required')
        for chain in self.chains:choice(chain,('bitcoin','ethereum'))
        for typ in self.output_types:choice(typ,e.SUBJECT_KINDS)
        for kind in self.result_kinds:choice(kind,e.RESULT_KINDS)
        for predicate in self.predicates:choice(predicate,e.PREDICATES)
        for kind in self.observation_kinds:choice(kind,e.OBSERVATION_KINDS)
        choice(self.mode,('local','manual','automated'));choice(self.cost_class,e.COSTS)
        if self.mode=='manual' and (self.predicates or self.observation_kinds):raise DiscoveryError('Manual instructions do not create findings')
        if self.mode!='manual':
            if not self.result_kinds or not self.predicates or not self.observation_kinds:raise DiscoveryError('Result contract required')
            types=set(self.input_types+self.output_types)
            for predicate in self.predicates:
                if not any(start in types and end in types for start,end in e.PAIRS.get(predicate,())):raise DiscoveryError('Unsupported predicate/type combination')
        return self

class Registry:
    def __init__(self,sources,transforms):
        self.sources={};self.transforms={}
        for item in sources:
            item=SourceDescriptor.model_validate(item)
            if item.id in self.sources:raise DiscoveryError('Duplicate source descriptor')
            self.sources[item.id]=item
        for item in transforms:
            item=TransformDescriptor.model_validate(item)
            if item.id in self.transforms:raise DiscoveryError('Duplicate transform descriptor')
            for source_id in item.source_ids:
                source=self.sources.get(source_id)
                if not source or (source.mode,source.cost_class)!=(item.mode,item.cost_class):raise DiscoveryError('Incompatible source reference')
            self.transforms[item.id]=item
    def pair(self,transform_id,source_id):
        transform=self.transforms.get(transform_id);source=self.sources.get(source_id)
        if not transform or not source or source_id not in transform.source_ids:raise DiscoveryError('Unknown transform/source pair')
        return transform,source
    def capabilities(self):
        sources=[]
        for source in self.sources.values():
            sources.append({**source.model_dump(),'credential_required':source.credential_env is not None,
                'configured':bool(os.getenv(source.credential_env,'')) if source.credential_env else True,
                'executable':False,'unavailable_reason':'Transform execution is not implemented'})
        return {'sources':sources,'transforms':[{**t.model_dump(),'executable':False} for t in self.transforms.values()]}

REGISTRY=Registry([
    dict(id='gc_labels',display_name='Stored GC Labels',category='local_annotation',mode='local',cost_class='FREE_LOCAL',retention_policy_id='gc-local-v1',storage_allowed=True,provenance_note='Secondary local annotation; no new public corroboration'),
    dict(id='google',display_name='Manual exact web search',category='web',mode='manual',cost_class='FREE_LOCAL',retention_policy_id='manual-navigation-v1',provenance_note='Not queried by Greedy Collector'),
    dict(id='github',display_name='Public GitHub code',category='code',mode='automated',cost_class='LIMITED_FREE',credential_env='DISCOVERY_GITHUB_TOKEN',rate_limit_per_minute=10,retention_policy_id='github-pending-review-v1',provenance_note='Public-only; source retention policy requires verification before execution'),
],[
    dict(id='wallet.local_labels',display_name='Stored Label context',description='Future local exact-address annotation context',source_ids=('gc_labels',),output_types=('annotation',),result_kinds=('candidate_evidence',),predicates=('locally_labeled_as',),observation_kinds=('local_label_snapshot',),mode='local',cost_class='FREE_LOCAL',max_requests=0),
    dict(id='wallet.manual_exact_web',display_name='Manual exact web search',description='Future manual navigation only; no captured results',source_ids=('google',),output_types=(),result_kinds=(),predicates=(),observation_kinds=(),mode='manual',cost_class='FREE_LOCAL',max_requests=0),
    dict(id='wallet.public_code_mentions',display_name='Public code mentions',description='Future exact-address public code context',source_ids=('github',),output_types=('repository',),result_kinds=('candidate_evidence','candidate_relationship'),predicates=('repository_contains',),observation_kinds=('code_search_result',),mode='automated',cost_class='LIMITED_FREE',cache_seconds=86400),
])
