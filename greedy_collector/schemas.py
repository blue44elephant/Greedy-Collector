from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator, field_validator
import re


from .chain_types import ChainName, LabelChain


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
    event_key: str | None = Field(default=None, max_length=160)
    event_index: str | None = Field(default=None, max_length=80)
    asset_contract: str | None = Field(default=None, max_length=128)


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


class WatchlistUpdate(BaseModel):
    enabled: bool | None = None
    priority: Literal["low", "normal", "high", "critical"] | None = None
    label: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    case_id: str | None = None


class AlertUpdate(BaseModel):
    status: Literal["New", "Reviewed", "Dismissed", "Escalated"] | None = None
    notes: str | None = None


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Case title must not be blank")
        return value.strip()


class CaseSummary(BaseModel):
    scope: str = Field(default="", max_length=20000)
    key_findings: str = Field(default="", max_length=20000)
    unresolved_questions: str = Field(default="", max_length=20000)
    limitations: str = Field(default="", max_length=20000)
    next_actions: str = Field(default="", max_length=20000)


class CaseUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: Literal["Open", "Paused", "Closed"] | None = None
    archived: bool | None = None
    summary: CaseSummary | None = None

    @model_validator(mode="after")
    def values(self):
        if self.title is not None and not self.title.strip():
            raise ValueError("Case title must not be blank")
        if any(getattr(self, k) is None for k in self.model_fields_set if k != "expected_version"):
            raise ValueError("Case update fields cannot be null")
        if self.title is not None:
            self.title = self.title.strip()
        return self


class NoteUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    body: str | None = Field(default=None, min_length=1, max_length=100000)
    archived: bool | None = None


class CaseRiskPin(BaseModel):
    chain: ChainName
    address: str


class CaseDiscoveryPin(BaseModel):
    run_id: str = Field(min_length=1, max_length=36)


class CaseEntityCreate(BaseModel):
    entity_type: Literal["wallet", "transaction", "label", "graph_snapshot", "attachment"]
    entity_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def chain_context(self):
        if self.entity_type in ('wallet','transaction','graph_snapshot') and 'chain' in self.metadata:
            from .chains import get_chain,Capability
            required = [Capability.CASES]
            if self.entity_type == 'transaction':
                required.append(Capability.TRANSACTION_LOOKUP)
            elif self.entity_type == 'graph_snapshot':
                required.append(Capability.GRAPH)
            get_chain(self.metadata['chain']).require(*required)
        return self


class AnalystNoteCreate(BaseModel):
    body: str = Field(min_length=1)
    author: str = "analyst"


class ManualLabelCreate(BaseModel):
    chain: LabelChain = "any"
    address: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=255)
    type: Literal["Exchange", "Mixer", "Bridge", "Scam", "Sanctioned", "Unknown"]
    source: str = Field(default="Manual analyst label", min_length=1, max_length=255)
    confidence: float = Field(default=0.7, ge=0, le=1)


    @model_validator(mode="after")
    def validate_public_address(self):
        if not self.address.strip() or not self.label.strip() or not self.source.strip():
            raise ValueError("Address, label, and source must not be blank")
        if self.chain != "any":
            from .chains import get_chain_adapter,Capability
            get_chain_adapter(self.chain,Capability.LABELS).validate_address(self.address)
        return self


class LabelStateUpdate(BaseModel):
    active: bool


class KycQuery(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    date_of_birth: str | None = None
    identifier: str | None = None
    domain: str | None = None
    include_manual_sources: bool = True


    @field_validator("name")
    @classmethod
    def validate_research_name(cls, value):
        value=value.strip()
        if len(value)<2:
            raise ValueError("Enter a research name of at least two characters")
        return value

    @field_validator("domain")
    @classmethod
    def validate_research_domain(cls, value):
        if value is None or not value.strip():
            return None
        try:
            domain=value.strip().rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Enter a domain name without a URL, path, or port") from exc
        parts=domain.split(".")
        if len(domain)>253 or len(parts)<2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",part) for part in parts) or parts[-1].isdigit():
            raise ValueError("Enter a domain name without a URL, path, or port")
        return domain


class KycReviewUpdate(BaseModel):
    review_status: Literal[
        "Unreviewed", "Potential match", "False positive", "Confirmed source match"
    ]


class ResolveRequest(BaseModel):
    input: str
    chain_hint: ChainName | None = None
