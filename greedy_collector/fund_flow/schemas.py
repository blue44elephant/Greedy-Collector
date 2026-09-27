from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..chain_types import ChainName
from ..chains import get_chain, Capability

class FlowQuery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chain: ChainName
    source: str=Field(min_length=1,max_length=128)
    target: str|None=Field(None,max_length=128)
    label: str|None=Field(None,min_length=1,max_length=255)
    label_category: str|None=Field(None,min_length=1,max_length=32)
    asset: str|None=Field(None,max_length=180)
    algorithm: Literal['shortest','simple','widest']='shortest'
    max_hops: int=Field(3,ge=1,le=6)
    max_paths: int=Field(20,ge=1,le=100)
    max_nodes: int=Field(1000,ge=2,le=5000)
    max_edges: int=Field(10000,ge=1,le=20000)
    temporal_order: bool=True
    start_time: datetime|None=None
    end_time: datetime|None=None

    @model_validator(mode='after')
    def validate_scope(self):
        d=get_chain(self.chain)
        if Capability.GRAPH not in d.capabilities:return self
        adapter=d.adapter()
        self.source=adapter.normalize_address(self.source)
        if self.target:self.target=adapter.normalize_address(self.target)
        if sum(bool(x) for x in (self.target,self.label,self.label_category))>1:raise ValueError('Choose one target definition')
        for field in ('start_time','end_time'):
            value=getattr(self,field)
            if value:
                if value.tzinfo is None:raise ValueError('Timezone is required')
                setattr(self,field,value.astimezone(timezone.utc))
        if self.start_time and self.end_time and self.start_time>self.end_time:raise ValueError('Time window is reversed')
        if self.asset:
            if self.asset=='native':self.asset=f'{self.chain}:native'
            if self.asset!=f'{self.chain}:native':
                prefix=f'{self.chain}:token:'
                if not self.asset.startswith(prefix):raise ValueError('Use native or chain:token:contract/mint')
                self.asset=prefix+adapter.normalize_address(self.asset[len(prefix):])
        return self

class FlowPin(BaseModel):
    run_id: str=Field(min_length=1,max_length=36)
