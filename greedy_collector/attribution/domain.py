"""Local validation and JSON-safe capture values. Never retrieves source URLs."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
import re
import unicodedata
from typing import Annotated, Literal
from urllib.parse import urlsplit, parse_qsl, unquote

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from ..chains import get_chain_adapter
from ..config import get_settings
from ..kyc.presentation import sanitize_research, sensitive_name
from . import enums

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class AttributionError(ValueError):
    """Safe domain error; no HTTP coupling at AT-1."""


class NotFound(AttributionError):
    pass


class Conflict(AttributionError):
    def __init__(self, message, existing_id=None):
        super().__init__(message)
        self.existing_id = existing_id


class SchemaUnavailable(AttributionError):
    pass


def choice(value, vocabulary):
    if value not in vocabulary:
        raise AttributionError("Unsupported attribution value")
    return value


def json_safe(value, depth=0):
    if depth > 32:
        raise AttributionError("Metadata nesting is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_safe(item, depth + 1) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_safe(item, depth + 1) for key, item in value.items()}
    raise AttributionError("Metadata must contain finite JSON values or dates")


def canonical_json(value):
    return json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_subject(chain, address):
    choice(chain, ("bitcoin", "ethereum"))
    if not isinstance(address, str):
        raise AttributionError("A supported public address is required")
    try:
        value = get_chain_adapter(chain).validate_address(address)
    except ValueError:
        raise AttributionError("Address does not match the supported chain format") from None
    return value.lower() if chain == "ethereum" or value.lower().startswith("bc1") else value


def name_key(value):
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or len(normalized) > 255:
        raise AttributionError("Normalized entity name is too long or empty")
    return normalized


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityInput(Input):
    canonical_name: Short
    entity_type: str = "unknown"
    description: str = Field(default="", max_length=8000)
    aliases: list[Short] = Field(default_factory=list, max_length=50)

    @field_validator("entity_type")
    @classmethod
    def valid_type(cls, value):
        return choice(value, enums.ENTITY_TYPES)


class ClaimInput(Input):
    entity_id: Annotated[str, StringConstraints(min_length=1, max_length=36)]
    subject_type: Literal["wallet"] = "wallet"
    chain: Literal["bitcoin", "ethereum"]
    subject_ref: str
    relationship: str
    valid_from: date | None = None
    valid_to: date | None = None
    scope_note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

    @field_validator("relationship")
    @classmethod
    def valid_relationship(cls, value):
        return choice(value, enums.RELATIONSHIPS)

    @model_validator(mode="after")
    def normalize(self):
        self.subject_ref = normalize_subject(self.chain, self.subject_ref)
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise AttributionError("Claim time bounds are reversed")
        return self


class ScopeInput(Input):
    valid_from: date | None = None
    valid_to: date | None = None
    scope_note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def dates(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise AttributionError("Claim time bounds are reversed")
        return self


class LinkInput(Input):
    stance: str
    directness: str
    rationale: Long

    @model_validator(mode="after")
    def relevance(self):
        choice(self.stance, enums.STANCES)
        choice(self.directness, enums.DIRECTNESS)
        if self.stance == "context" and self.directness != "context":
            raise AttributionError("Context relevance requires context directness")
        return self


class EvidenceInput(Input):
    evidence_type: str
    title: Short
    summary: Long
    excerpt: str | None = Field(default=None, max_length=8000)
    source_name: Short
    source_url: str | None = Field(default=None, max_length=2048)
    source_locator: str | None = Field(default=None, max_length=512)
    source_catalog_id: str | None = Field(default=None, max_length=128)
    origin: str
    published_on: date | None = None
    observed_on: date | None = None
    analyst_note: str = Field(default="", max_length=8000)
    source_reliability: str = "unassessed"
    reliability_rationale: str = Field(default="", max_length=8000)
    origin_group: str | None = Field(default=None, max_length=128)
    metadata_json: dict = Field(default_factory=dict)

    @field_validator("metadata_json", mode="before")
    @classmethod
    def metadata(cls, value):
        if not isinstance(value, dict):
            raise AttributionError("Evidence metadata must be an object")
        clean = sanitize_research(json_safe(value))
        if len(canonical_json(clean).encode("utf-8")) > 32768:
            raise AttributionError("Evidence metadata exceeds 32 KiB")
        return clean

    @model_validator(mode="after")
    def provenance(self):
        choice(self.evidence_type, enums.EVIDENCE_TYPES)
        # Snapshot ingestion belongs to AT-5, not a trusted-ID bypass here.
        if self.evidence_type in ("label_snapshot", "research_snapshot"):
            raise AttributionError("Source snapshot handoffs are not enabled in AT-1")
        choice(self.origin, ("public_osint", "analyst_added"))
        choice(self.source_reliability, enums.RELIABILITIES)
        if self.source_reliability != "unassessed" and not self.reliability_rationale.strip():
            raise AttributionError("Assessed source reliability requires a rationale")
        if self.source_locator:
            self.source_locator = self.source_locator.strip()
            if re.match(r"^(?:[a-zA-Z]:[\\/]|[\\/]|file:)", self.source_locator, re.I):
                raise AttributionError("Use a citation locator, not a filesystem path")
        if self.source_url:
            self.source_url = self.source_url.strip()
            try:
                url = urlsplit(self.source_url)
                url.port  # Reject malformed ports locally, without DNS or requests.
                unsafe = url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                unsafe = unsafe or any(sensitive_name(key) for key, _ in parse_qsl(url.query) + parse_qsl(url.fragment))
                unsafe = unsafe or any(ord(char) < 33 for char in self.source_url)
                for name, secret in get_settings().model_dump().items():
                    if ("api_key" in name or "password" in name) and isinstance(secret, str) and secret and secret in unquote(self.source_url):
                        unsafe = True
                if unsafe:
                    raise ValueError()
            except ValueError:
                raise AttributionError("Use a public HTTP(S) citation without credentials") from None
        if self.evidence_type == "analyst_observation":
            if not self.analyst_note.strip():
                raise AttributionError("Analyst observations require an explanatory note")
        elif not (self.source_url or self.source_locator):
            raise AttributionError("A source URL or citation locator is required")
        return self


def reason_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise AttributionError("A concise nonblank reason is required")
    return sanitize_research(value.strip())
