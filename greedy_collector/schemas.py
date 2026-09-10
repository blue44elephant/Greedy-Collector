from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ChainName = Literal["ethereum", "bitcoin"]


class NormalizedTransaction(BaseModel):
    tx_hash: str
    chain: str
    from_address: str = ""
    to_address: str = ""
    value_native: str = "0"
    value_usd: str | None = None
    token_symbol: str = ""
    timestamp: datetime | None = None
    block_number: str = ""
    fee: str = "0"
    direction: str = "unknown"
    source_api: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class LookupRequest(BaseModel):
    chain: ChainName
    address: str = Field(min_length=8, max_length=128)
    refresh: bool = False


class TransactionLookupRequest(BaseModel):
    chain: ChainName
    tx_hash: str = Field(min_length=16, max_length=128)


class WatchlistCreate(BaseModel):
    chain: ChainName
    address: str
    label: str = ""
    case_id: str | None = None
    notes: str = ""
    enabled: bool = True
    priority: Literal["low", "normal", "high", "critical"] = "normal"


class AlertUpdate(BaseModel):
    status: Literal["New", "Reviewed", "Dismissed", "Escalated"] | None = None
    notes: str | None = None


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""


class CaseEntityCreate(BaseModel):
    entity_type: Literal["wallet", "transaction", "label", "graph_snapshot", "attachment"]
    entity_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalystNoteCreate(BaseModel):
    body: str = Field(min_length=1)
    author: str = "analyst"


class ManualLabelCreate(BaseModel):
    chain: str = "any"
    address: str
    label: str
    type: Literal["Exchange", "Mixer", "Bridge", "Scam", "Sanctioned", "Unknown"]
    source: str = "Manual analyst label"
    confidence: float = Field(default=0.7, ge=0, le=1)


class KycQuery(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    date_of_birth: str | None = None
    identifier: str | None = None
    domain: str | None = None
    include_manual_sources: bool = True


class KycReviewUpdate(BaseModel):
    review_status: Literal[
        "Unreviewed", "Potential match", "False positive", "Confirmed source match"
    ]
