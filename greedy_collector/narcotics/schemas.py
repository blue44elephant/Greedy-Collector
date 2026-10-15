from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Provenance(Input):
    kind: Literal["analyst_entry", "case_note", "public_source_capture", "discovery_result",
                  "attribution_evidence", "sanctions_record", "blockchain_observation"] = "analyst_entry"
    reference_id: str | None = Field(default=None, max_length=160)
    note: str = Field(default="", max_length=2000)

class Fact(Input):
    value: str = Field(max_length=300)
    provenance: Provenance = Field(default_factory=Provenance)

class Wallet(Input):
    chain: str = Field(max_length=32)
    address: str = Field(max_length=256)
    provenance: Provenance = Field(default_factory=Provenance)

class SubstanceInput(Input):
    source_name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=160)
    kind: Literal["substance", "precursor", "pre_precursor"] = "substance"
    quantity: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=80)
    note: str = Field(default="", max_length=4000)
    provenance: Provenance = Field(default_factory=Provenance)
    @field_validator("quantity")
    @classmethod
    def quantity_safe(cls, value):
        if value is not None:
            try:
                number = Decimal(value)
                if not number.is_finite() or number < 0: raise ValueError()
            except (InvalidOperation, ValueError): raise ValueError("Quantity must be a nonnegative decimal string") from None
        return value

class LogisticsInput(Input):
    kind: Literal["consignment", "parcel", "shipment", "courier_event"] = "consignment"
    fields: dict[str, list[Fact]] = Field(default_factory=dict, max_length=24)
    wallets: list[Wallet] = Field(default_factory=list, max_length=30)
    entity_reference_ids: list[str] = Field(default_factory=list, max_length=30)
    provenance: Provenance = Field(default_factory=Provenance)

FIELD_NAMES = {
    "marketplace", "marketplace_account", "vendor_alias", "platform", "payment_method", "logistics_method",
    "consignment_type", "origin_country", "origin_region", "origin_city", "destination_country",
    "destination_region", "destination_city", "seizure_location", "concealment", "packaging",
    "delivery_method", "drop_method", "recipient_pattern", "sender_pattern", "mo_tag", "domain",
    "public_profile", "notes", "extension", "carrier_reference", "carrier_service", "dispatch_at",
    "interception_at", "weight", "weight_unit",
}
COURIERS = ("international_post", "domestic_post", "courier_company", "air_cargo", "sea_cargo",
            "road_transport", "passenger_baggage", "hand_delivery", "unknown", "other")
PLATFORMS = ("darknet_market", "messaging_platform", "social_media", "website", "forum", "direct_contact", "unknown", "other")
def validate_fields(value):
    if set(value) - FIELD_NAMES: raise ValueError("Unsupported profile field; use extension for additional notes")
    for key, facts in value.items():
        if len(facts) > 30: raise ValueError("At most 30 values per field")
        for fact in facts:
            if key in ("platform", "logistics_method") and fact.value not in (PLATFORMS if key == "platform" else COURIERS):
                raise ValueError("Unsupported controlled value; use other and notes")
            if key in ("dispatch_at", "interception_at"):
                parse_time(fact.value)
    return value

def parse_time(value):
    if value is None: return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None: raise ValueError("Timestamps must include a timezone")
    return dt.astimezone(timezone.utc).isoformat()

class ProfileInput(Input):
    expected_revision: int = Field(default=0, ge=0)
    fields: dict[str, list[Fact]] = Field(default_factory=dict, max_length=40)
    wallets: list[Wallet] = Field(default_factory=list, max_length=100)
    substances: list[SubstanceInput] = Field(default_factory=list, max_length=100)
    logistics: list[LogisticsInput] = Field(default_factory=list, max_length=100)
    period_start: str | None = None
    period_end: str | None = None
    @field_validator("fields")
    @classmethod
    def fields_safe(cls, value): return validate_fields(value)
    @field_validator("period_start", "period_end")
    @classmethod
    def time_safe(cls, value): return parse_time(value)
    @model_validator(mode="after")
    def ordered_period(self):
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("Activity period end precedes start")
        for row in self.logistics: validate_fields(row.fields)
        return self

class FingerprintInput(Input):
    weights: dict[str, int] = Field(default_factory=dict, max_length=40)

class RelatedInput(FingerprintInput):
    case_ids: list[str] | None = Field(default=None, max_length=200)
    include_archived: bool = False
    max_cases: int = Field(default=100, ge=1, le=200)

class ReviewInput(Input):
    expected_sequence: int = Field(ge=0)
    status: Literal["RELEVANT", "IRRELEVANT", "UNREVIEWED"]
    rationale: str = Field(min_length=1, max_length=4000)

class NexusInput(Input):
    case_ids: list[str] = Field(min_length=1, max_length=20)
    link_run_ids: list[str] = Field(default_factory=list, max_length=20)
    max_nodes: int = Field(default=250, ge=1, le=300)
    max_edges: int = Field(default=800, ge=1, le=1200)

class PriorityInput(Input):
    nexus_id: str

class PinInput(Input):
    kind: Literal["mo_fingerprint", "case_comparison", "reviewed_link", "nexus", "priority"]
    reference_id: str
