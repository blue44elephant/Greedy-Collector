"""Code-owned execution bindings and separate manual-action generators."""
from dataclasses import dataclass
from datetime import datetime
import inspect
from typing import Awaitable,Callable,Protocol,TypeVar
from pydantic import BaseModel,ConfigDict,Field
from .domain import DiscoveryError
from .schemas import Batch,QuotaReport
from .registry import REGISTRY

class QuotaPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    daily_units:int=Field(strict=True,ge=0,le=1000000)
    monthly_units:int=Field(strict=True,ge=0,le=31000000)
    units_per_request:int=Field(default=1,strict=True,ge=1,le=1000000)
    enabled:bool=True
    generation:str=Field(default='1',pattern=r'^[a-zA-Z0-9]{1,64}$')

class ExecutionSignal(Exception):
    """Closed error categories; never retain an upstream exception or message."""
    def __init__(self,category,quota=None):
        if category not in ('rate_limited','timeout','transport_failed','invalid_provider_response','budget_exhausted','configuration_unavailable','entitlement_unavailable'):
            raise DiscoveryError('Unsupported executor outcome')
        self.category=category
        self.quota=QuotaReport.model_validate(quota or {})
        super().__init__(category)

T=TypeVar('T')
class ExecutionContext:
    """No Session/config secrets. Every remote attempt must use request().

    Cancellation and timeouts require cooperative async implementations. This is
    a contract for reviewed code, not a sandbox for untrusted Python.
    """
    def __init__(self,subject,parameters,source_id,deadline,cancelled,charge):
        self.subject=dict(subject);self.parameters=dict(parameters);self.source_id=source_id
        self.deadline:datetime=deadline;self._cancelled=cancelled;self._charge=charge
    def checkpoint(self):
        import asyncio
        if self._cancelled.is_set():raise asyncio.CancelledError()
    async def request(self,operation:Callable[[],Awaitable[T]],request_class='query')->T:
        self.checkpoint()
        if request_class not in ('query','page','confirmation','retry'):raise DiscoveryError('Unsupported request class')
        self._charge(request_class)
        value=await operation()
        self.checkpoint()
        return value

class TransformExecutor(Protocol):
    async def execute(self,context:ExecutionContext)->Batch:...

@dataclass(frozen=True)
class Binding:
    transform_id:str
    source_id:str
    transform_version:int
    source_version:int
    executor:TransformExecutor
    quota:QuotaPolicy
    available:Callable[[],bool]|None=None

@dataclass(frozen=True)
class ManualBinding:
    transform_id:str
    source_id:str
    transform_version:int
    source_version:int
    actions:Callable

@dataclass(frozen=True)
class CaptureBinding:
    transform_id:str
    source_id:str
    transform_version:int
    source_version:int
    service:Callable

class ExecutorRegistry:
    def __init__(self,descriptors=REGISTRY):
        self.descriptors=descriptors;self._bindings={};self._manual={};self._captures={}
    def register(self,binding:Binding):
        if not isinstance(binding,Binding):raise DiscoveryError('Only code bindings may be registered')
        transform,source=self.descriptors.pair(binding.transform_id,binding.source_id)
        if (binding.transform_version,binding.source_version)!=(transform.version,source.version):raise DiscoveryError('Executor descriptor version mismatch')
        if source.mode=='manual':raise DiscoveryError('Manual navigation is not an executor')
        if not isinstance(binding.quota,QuotaPolicy) or not inspect.iscoroutinefunction(getattr(binding.executor,'execute',None)):raise DiscoveryError('An async typed executor and quota policy are required')
        key=(binding.transform_id,binding.source_id)
        if key in self._bindings:raise DiscoveryError('Duplicate executor')
        if any(b.source_id==binding.source_id and b.quota!=binding.quota for b in self._bindings.values()):raise DiscoveryError('Executors sharing a source must share its quota policy')
        self._bindings[key]=binding
    def get(self,transform_id,source_id):return self._bindings.get((transform_id,source_id))

    def register_capture(self,binding):
        if not isinstance(binding,CaptureBinding) or not callable(binding.service):raise DiscoveryError('Code-owned capture service required')
        transform,source=self.descriptors.pair(binding.transform_id,binding.source_id)
        if not transform.capture_only or (transform.version,source.version)!=(binding.transform_version,binding.source_version):raise DiscoveryError('Invalid capture binding')
        key=(binding.transform_id,binding.source_id)
        if key in self._captures:raise DiscoveryError('Duplicate capture handler')
        self._captures[key]=binding

    def capture(self,transform_id,source_id):return self._captures.get((transform_id,source_id))

    def register_manual(self,binding):
        if not isinstance(binding,ManualBinding) or not callable(binding.actions) or inspect.iscoroutinefunction(binding.actions):raise DiscoveryError('A code-owned local manual handler is required')
        transform,source=self.descriptors.pair(binding.transform_id,binding.source_id)
        if (transform.version,source.version)!=(binding.transform_version,binding.source_version):raise DiscoveryError('Manual descriptor version mismatch')
        if transform.capture_only or source.mode!='manual' or source.cost_class!='FREE_LOCAL' or transform.max_requests!=0:raise DiscoveryError('Manual generation must be free local with zero requests')
        key=(binding.transform_id,binding.source_id)
        if key in self._manual:raise DiscoveryError('Duplicate manual handler')
        self._manual[key]=binding

    def manual(self,transform_id,source_id):return self._manual.get((transform_id,source_id))

def production_executors(sessions):
    # Bound to the application's chosen database; construction neither queries
    # Labels nor performs Discovery. Tests can supply isolated sessions.
    from .local import LocalLabelsExecutor,exact_web_actions
    from .github import GitHubCodeExecutor
    from .graphsense import GraphSenseExecutor
    from .ens import EnsPrimaryNameExecutor,configured
    from .manual_source import ManualSourceService
    registry=ExecutorRegistry()
    from .broad.providers import WebSearchExecutor
    registry.register(Binding('wallet.broad_web','brave_search',1,1,WebSearchExecutor(),QuotaPolicy(daily_units=100,monthly_units=1000)))
    registry.register(Binding('wallet.graphsense_public_tags','github',1,1,GraphSenseExecutor(),QuotaPolicy(daily_units=100,monthly_units=3000)))
    registry.register_capture(CaptureBinding('wallet.manual_source_observation','manual_source',1,1,ManualSourceService))
    registry.register(Binding('wallet.ens_primary_name','ens_ethereum',1,1,EnsPrimaryNameExecutor(),QuotaPolicy(daily_units=100,monthly_units=3000),available=configured))
    registry.register(Binding('wallet.local_labels','gc_labels',1,1,LocalLabelsExecutor(sessions),QuotaPolicy(daily_units=0,monthly_units=0)))
    registry.register_manual(ManualBinding('wallet.manual_exact_web','google',1,1,exact_web_actions))
    registry.register(Binding('wallet.public_code_mentions','github',1,1,GitHubCodeExecutor(),QuotaPolicy(daily_units=100,monthly_units=3000)))
    return registry
