"""Code-owned async executor bindings. Production deliberately registers none."""
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
        if category not in ('rate_limited','timeout','transport_failed','invalid_provider_response','budget_exhausted','configuration_unavailable'):
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

class ExecutorRegistry:
    def __init__(self,descriptors=REGISTRY):
        self.descriptors=descriptors;self._bindings={}
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

# Never populated by imports, environment variables, database rows or API input.
PRODUCTION_EXECUTORS=ExecutorRegistry()
