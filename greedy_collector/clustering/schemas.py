from pydantic import BaseModel, Field, field_validator
from ..chain_types import ChainName

class Analyze(BaseModel):
    chain: ChainName

class Exclude(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    @field_validator("reason")
    @classmethod
    def rationale(cls, value):
        if not value.strip(): raise ValueError("Rationale required")
        return value.strip()

class Pin(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)
