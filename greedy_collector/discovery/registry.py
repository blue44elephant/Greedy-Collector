"""Typed descriptors; runtime implementation state is determined by code bindings."""
import os,re
from ..chains import get_chain,list_chains,Capability
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
    chains:tuple[str,...]
    required_capability:Capability=Field(default=Capability.DISCOVERY,exclude=True)
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
    capture_only:bool=False
    implemented:bool=False
    @model_validator(mode='before')
    @classmethod
    def compatible_chains(cls,value):
        if isinstance(value,dict) and 'chains' not in value:
            required=Capability(value.get('required_capability',Capability.DISCOVERY))
            value={**value,'chains':tuple(d.chain_id for d in list_chains()
                if {Capability.DISCOVERY,required} <= d.capabilities)}
        return value
    @model_validator(mode='after')
    def validate_descriptor(self):
        if self.implemented:raise DiscoveryError('Implementation state is binding-owned, not a descriptor assertion')
        if self.input_types!=('blockchain_address',):raise DiscoveryError('Only wallet input is enabled')
        if not self.source_ids or len(set(self.source_ids))!=len(self.source_ids):raise DiscoveryError('Unique source references required')
        if not self.chains or not self.display_name.strip() or not self.description.strip():raise DiscoveryError('Descriptor contract required')
        for chain in self.chains:get_chain(chain).require(self.required_capability)
        for typ in self.output_types:choice(typ,e.SUBJECT_KINDS)
        for kind in self.result_kinds:choice(kind,e.RESULT_KINDS)
        for predicate in self.predicates:choice(predicate,e.PREDICATES)
        for kind in self.observation_kinds:choice(kind,e.OBSERVATION_KINDS)
        choice(self.mode,('local','manual','automated'));choice(self.cost_class,e.COSTS)
        if self.capture_only and (self.mode!='manual' or self.cost_class!='FREE_LOCAL' or self.max_requests!=0 or self.max_results!=1):raise DiscoveryError('Capture must be manual, free local and bounded')
        if self.mode=='manual' and not self.capture_only and (self.predicates or self.observation_kinds):raise DiscoveryError('Manual instructions do not create findings')
        if self.mode!='manual' or self.capture_only:
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
    dict(id='manual_source',display_name='Manual analyst capture',category='analyst_capture',mode='manual',cost_class='FREE_LOCAL',retention_policy_id='manual-source-v1',storage_allowed=True,provenance_note='Analyst supplied observation. No network retrieval or independent source verification.'),
    dict(id='ens_ethereum',display_name='ENS / Ethereum',category='name_service',mode='automated',cost_class='LIMITED_FREE',credential_env='ALCHEMY_API_KEY',rate_limit_per_minute=10,retention_policy_id='ens-primary-name-v1',storage_allowed=True,provenance_note='Current forward-verified technical naming relationship; not real-world attribution.'),
    dict(id='github',display_name='Public GitHub code',category='code',mode='automated',cost_class='LIMITED_FREE',credential_env='DISCOVERY_GITHUB_TOKEN',rate_limit_per_minute=10,retention_policy_id='github-public-excerpt-v1',storage_allowed=True,provenance_note='Bounded public code fragments and GraphSense tag metadata; no ownership inference. Use a token without private-repository access.'),
],[
    dict(id='wallet.graphsense_public_tags',display_name='GraphSense Public Tags',description='Exact BTC/ETH address annotations from public GraphSense TagPacks. Third-party annotations, not verified ownership or clustering.',source_ids=('github',),chains=('bitcoin','ethereum'),output_types=('annotation',),result_kinds=('candidate_relationship',),predicates=('publicly_labeled_as',),observation_kinds=('verified_page_observation',),mode='automated',cost_class='LIMITED_FREE',max_results=100,max_requests=10,deadline_seconds=60,cache_seconds=86400),
    dict(id='wallet.local_labels',display_name='Stored Label context',description='Read current exact-address local annotations. No external collection or ownership inference.',source_ids=('gc_labels',),required_capability=Capability.LABELS,output_types=('annotation',),result_kinds=('candidate_evidence',),predicates=('locally_labeled_as',),observation_kinds=('local_label_snapshot',),mode='local',cost_class='FREE_LOCAL',max_requests=0),
    dict(id='wallet.manual_exact_web',display_name='Manual exact web search',description='Generate an exact-wallet search link for explicit analyst use. The search engine is not queried by Greedy Collector.',source_ids=('google',),output_types=(),result_kinds=(),predicates=(),observation_kinds=(),mode='manual',cost_class='FREE_LOCAL',max_requests=0),
    dict(id='wallet.manual_source_observation',display_name='Record source observation',description='Manually preserve where this wallet was observed. Preview and confirm; no network or ownership inference.',source_ids=('manual_source',),output_types=('url','annotation'),result_kinds=('candidate_relationship',),predicates=('mentions_wallet',),observation_kinds=('analyst_capture',),mode='manual',cost_class='FREE_LOCAL',max_requests=0,max_results=1,capture_only=True),
    dict(id='wallet.ens_primary_name',display_name='ENS Primary Name',description='Retrieve one forward-verified Ethereum ENS primary name. Requires Ethereum RPC and the local ENS normalizer. No ownership inference.',source_ids=('ens_ethereum',),chains=('ethereum',),output_types=('ens_name',),result_kinds=('candidate_relationship',),predicates=('resolves_to',),observation_kinds=('name_service_record',),mode='automated',cost_class='LIMITED_FREE',max_results=1,max_requests=1,max_bytes=16384,deadline_seconds=30,cache_seconds=3600),
    dict(id='wallet.public_code_mentions',display_name='Public code mentions',description='Find full wallet mentions in returned public GitHub code fragments. Bounded search, no file fetching or ownership inference.',source_ids=('github',),output_types=('repository',),result_kinds=('candidate_evidence','candidate_relationship'),predicates=('repository_contains',),observation_kinds=('code_search_result',),mode='automated',cost_class='LIMITED_FREE',max_results=30,deadline_seconds=30,cache_seconds=86400),
])
