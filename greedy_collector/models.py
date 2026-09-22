from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
    FetchedValue,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    balance_native: Mapped[str] = mapped_column(String(80), default="0")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="Low")
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("chain", "address", name="uq_address_chain"),)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tx_hash: Mapped[str] = mapped_column(String(128), index=True)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    from_address: Mapped[str] = mapped_column(String(128), index=True, default="")
    to_address: Mapped[str] = mapped_column(String(128), index=True, default="")
    value_native: Mapped[str] = mapped_column(String(80), default="0")
    value_usd: Mapped[str | None] = mapped_column(String(80))
    token_symbol: Mapped[str] = mapped_column(String(32), default="")
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    block_number: Mapped[str] = mapped_column(String(80), default="")
    fee: Mapped[str] = mapped_column(String(80), default="0")
    direction: Mapped[str] = mapped_column(String(16), default="unknown")
    source_api: Mapped[str] = mapped_column(String(64), default="")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint(
            "chain",
            "tx_hash",
            "from_address",
            "to_address",
            "value_native",
            "token_symbol",
            name="uq_transaction_transfer",
        ),
    )


class Label(Base):
    __tablename__ = "labels"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    address: Mapped[str] = mapped_column(String(128), index=True)
    chain: Mapped[str] = mapped_column(String(32), default="any")
    label: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32), default="Unknown")
    source: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("chain", "address", "label", "source", name="uq_label_source"),
    )


class RiskRule(Base):
    __tablename__ = "risk_rules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16))
    weight: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)


class RiskResult(Base):
    __tablename__ = "risk_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    score: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(16))
    findings: Mapped[list] = mapped_column(JSON, default=list)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistWallet(Base):
    __tablename__ = "watchlist_wallets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str] = mapped_column(String(255), default="")
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cases.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_block: Mapped[str | None] = mapped_column(String(80))
    last_seen_tx: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("chain", "address", name="uq_watchlist_wallet"),)


class WalletAlert(Base):
    __tablename__ = "wallet_alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet: Mapped[str] = mapped_column(String(128), index=True)
    chain: Mapped[str] = mapped_column(String(32))
    tx_hash: Mapped[str | None] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trigger_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[str | None] = mapped_column(String(80))
    token: Mapped[str | None] = mapped_column(String(32))
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cases.id"))
    status: Mapped[str] = mapped_column(String(16), default="New")
    notes: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="Open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseEntity(Base):
    __tablename__ = "case_entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_ref: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class AnalystNote(Base):
    __tablename__ = "analyst_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(128), default="analyst")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(String(36), ForeignKey("watchlist_wallets.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    new_transactions: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class NotificationSetting(Base):
    __tablename__ = "notification_settings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    channel: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)


class ApiFetchLog(Base):
    __tablename__ = "api_fetch_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detail: Mapped[str] = mapped_column(Text, default="")


class KycScreeningRun(Base):
    __tablename__ = "kyc_screening_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    query: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    checked_sources: Mapped[list] = mapped_column(JSON, default=list)
    unavailable_sources: Mapped[list] = mapped_column(JSON, default=list)
    manual_sources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KycMatch(Base):
    __tablename__ = "kyc_matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kyc_screening_runs.id"), index=True
    )
    source: Mapped[str] = mapped_column(String(128))
    subject_name: Mapped[str] = mapped_column(String(255))
    match_score: Mapped[float] = mapped_column(Float)
    match_rationale: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(32), default="Unreviewed")


# AT-1 attribution persistence; independent from wallet/risk/label state.
from sqlalchemy import CheckConstraint, Date, Index, DDL, event, text


class AttributionEntity(Base):
    __tablename__ = 'attribution_entities'
    id = mapped_column(String(36), nullable=False, primary_key=True, default=new_id)
    canonical_name = mapped_column(String(255), nullable=False)
    name_key = mapped_column(String(255), nullable=False)
    entity_type = mapped_column(String(32), nullable=False, default='unknown', server_default=text("'unknown'"))
    description = mapped_column(Text, nullable=False, default='', server_default=text("''"))
    aliases = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    created_by = mapped_column(String(128), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    archived_at = mapped_column(DateTime(timezone=True), nullable=True)
    version = mapped_column(Integer, nullable=False, default=1, server_default=text('1'))
    __table_args__ = (
        CheckConstraint("entity_type IN ('organization', 'person', 'service', 'protocol', 'public_body', 'online_identity', 'unknown')", name="ck_attribution_entities_1"),
        CheckConstraint('version >= 1', name="ck_attribution_entities_2"),
        CheckConstraint('length(trim(canonical_name)) > 0', name="ck_attribution_entities_3"),
        CheckConstraint('length(trim(name_key)) > 0', name="ck_attribution_entities_4"),
        Index('ix_attribution_entities_1', 'name_key', 'id'),
        Index('ix_attribution_entities_2', 'archived_at', 'entity_type', 'id'),
    )


class AttributionClaim(Base):
    __tablename__ = 'attribution_claims'
    id = mapped_column(String(36), nullable=False, primary_key=True, default=new_id)
    subject_type = mapped_column(String(16), nullable=False, default='wallet', server_default=text("'wallet'"))
    chain = mapped_column(String(32), nullable=False)
    subject_ref = mapped_column(String(128), nullable=False)
    entity_id = mapped_column(String(36), ForeignKey('attribution_entities.id', name='fk_attribution_claims_entity_id', ondelete="RESTRICT"), nullable=False)
    relationship = mapped_column(String(32), nullable=False)
    valid_from = mapped_column(Date, nullable=True)
    valid_to = mapped_column(Date, nullable=True)
    scope_note = mapped_column(Text, nullable=False)
    assessment = mapped_column(String(32), nullable=False, default='unassessed', server_default=text("'unassessed'"))
    assessment_rationale = mapped_column(Text, nullable=False, default='', server_default=text("''"))
    assessed_at = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_by = mapped_column(String(128), nullable=True)
    needs_review = mapped_column(Boolean, nullable=False, default=True, server_default=text('1'))
    created_by = mapped_column(String(128), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    archived_at = mapped_column(DateTime(timezone=True), nullable=True)
    version = mapped_column(Integer, nullable=False, default=1, server_default=text('1'))
    __table_args__ = (
        CheckConstraint("subject_type = 'wallet'", name="ck_attribution_claims_1"),
        CheckConstraint("chain IN ('bitcoin','ethereum')", name="ck_attribution_claims_2"),
        CheckConstraint("relationship IN ('operated_by', 'controlled_by', 'publicly_declared_by')", name="ck_attribution_claims_3"),
        CheckConstraint("assessment IN ('unassessed', 'possible', 'supported', 'strongly_supported', 'rejected')", name="ck_attribution_claims_4"),
        CheckConstraint('version >= 1', name="ck_attribution_claims_5"),
        CheckConstraint('length(trim(scope_note)) > 0', name="ck_attribution_claims_6"),
        CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from', name="ck_attribution_claims_7"),
        CheckConstraint('(assessed_at IS NULL AND assessed_by IS NULL) OR (assessed_at IS NOT NULL AND assessed_by IS NOT NULL)', name="ck_attribution_claims_8"),
        CheckConstraint("assessment = 'unassessed' OR (length(trim(assessment_rationale)) > 0 AND assessed_at IS NOT NULL AND assessed_by IS NOT NULL)", name="ck_attribution_claims_9"),
        CheckConstraint("chain != 'ethereum' OR subject_ref = lower(subject_ref)", name="ck_attribution_claims_10"),
        CheckConstraint("chain != 'bitcoin' OR lower(substr(subject_ref,1,3)) != 'bc1' OR subject_ref = lower(subject_ref)", name="ck_attribution_claims_11"),
        UniqueConstraint('subject_type', 'chain', 'subject_ref', 'relationship', 'entity_id', name="uq_attribution_claims_1"),
        Index('ix_attribution_claims_1', 'chain', 'subject_ref', 'archived_at'),
        Index('ix_attribution_claims_2', 'entity_id', 'archived_at', 'id'),
        Index('ix_attribution_claims_3', 'assessment', 'needs_review', 'updated_at', 'id'),
    )


class AttributionEvidence(Base):
    __tablename__ = 'attribution_evidence'
    # Deferred server-owned extension: legacy captures omit this column on old schemas.
    __mapper_args__ = {'eager_defaults': False}
    id = mapped_column(String(36), nullable=False, primary_key=True, default=new_id)
    evidence_type = mapped_column(String(32), nullable=False)
    title = mapped_column(String(255), nullable=False)
    summary = mapped_column(Text, nullable=False)
    excerpt = mapped_column(Text, nullable=True)
    source_name = mapped_column(String(255), nullable=False)
    source_url = mapped_column(Text, nullable=True)
    source_locator = mapped_column(String(512), nullable=True)
    source_catalog_id = mapped_column(String(128), nullable=True)
    origin = mapped_column(String(32), nullable=False)
    collection_method = mapped_column(String(32), nullable=False)
    published_on = mapped_column(Date, nullable=True)
    observed_on = mapped_column(Date, nullable=True)
    captured_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    captured_by = mapped_column(String(128), nullable=False)
    analyst_note = mapped_column(Text, nullable=False, default='', server_default=text("''"))
    source_reliability = mapped_column(String(16), nullable=False, default='unassessed', server_default=text("'unassessed'"))
    reliability_rationale = mapped_column(Text, nullable=False, default='', server_default=text("''"))
    origin_group = mapped_column(String(128), nullable=True)
    origin_label_id = mapped_column(String(36), ForeignKey('labels.id', name='fk_attribution_evidence_origin_label_id', ondelete="RESTRICT"), nullable=True)
    origin_match_id = mapped_column(String(36), ForeignKey('kyc_matches.id', name='fk_attribution_evidence_origin_match_id', ondelete="RESTRICT"), nullable=True)
    metadata_json = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    content_sha256 = mapped_column(String(64), nullable=False)
    origin_discovery_observation_id = mapped_column(String(36), ForeignKey('discovery_observations.id', name='fk_attribution_evidence_origin_discovery_observation_id', ondelete='RESTRICT'), nullable=True, deferred=True, server_default=FetchedValue())
    __table_args__ = (
        CheckConstraint("evidence_type IN ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation', 'discovery_snapshot')", name="ck_attribution_evidence_1"),
        CheckConstraint("origin IN ('public_osint', 'analyst_added', 'commercial_proprietary', 'privileged_nonpublic')", name="ck_attribution_evidence_2"),
        CheckConstraint("collection_method IN ('analyst_entry', 'label_snapshot', 'research_snapshot', 'discovery_snapshot')", name="ck_attribution_evidence_3"),
        CheckConstraint("source_reliability IN ('unassessed', 'reliable', 'uncertain', 'unreliable')", name="ck_attribution_evidence_4"),
        CheckConstraint('length(trim(title)) > 0 AND length(trim(summary)) > 0 AND length(trim(source_name)) > 0', name="ck_attribution_evidence_5"),
        CheckConstraint('length(content_sha256) = 64', name="ck_attribution_evidence_6"),
        CheckConstraint("source_reliability = 'unassessed' OR length(trim(reliability_rationale)) > 0", name="ck_attribution_evidence_7"),
        CheckConstraint("((collection_method = 'analyst_entry' AND origin_label_id IS NULL AND origin_match_id IS NULL AND evidence_type NOT IN ('label_snapshot','research_snapshot','discovery_snapshot')) OR (collection_method = 'label_snapshot' AND origin_label_id IS NOT NULL AND origin_match_id IS NULL AND evidence_type = 'label_snapshot') OR (collection_method = 'research_snapshot' AND origin_match_id IS NOT NULL AND origin_label_id IS NULL AND evidence_type = 'research_snapshot')) AND origin_discovery_observation_id IS NULL OR (collection_method = 'discovery_snapshot' AND evidence_type = 'discovery_snapshot' AND origin_discovery_observation_id IS NOT NULL AND origin_label_id IS NULL AND origin_match_id IS NULL)", name="ck_attribution_evidence_8"),
        CheckConstraint("(evidence_type = 'analyst_observation' AND length(trim(analyst_note)) > 0) OR (evidence_type != 'analyst_observation' AND (length(trim(coalesce(source_url,''))) > 0 OR length(trim(coalesce(source_locator,''))) > 0))", name="ck_attribution_evidence_9"),
        Index('ix_attribution_evidence_1', 'captured_at', 'id'),
        Index('ix_attribution_evidence_2', 'content_sha256'),
        Index('ix_attribution_evidence_3', 'source_catalog_id', 'captured_at'),
        Index('ix_attribution_evidence_4', 'origin_label_id'),
        Index('ix_attribution_evidence_5', 'origin_match_id'),
        Index('ix_attribution_evidence_6', 'origin_group'),
        Index('ix_attribution_evidence_7', 'origin_discovery_observation_id'),
    )


class AttributionClaimEvidence(Base):
    __tablename__ = 'attribution_claim_evidence'
    id = mapped_column(String(36), nullable=False, primary_key=True, default=new_id)
    claim_id = mapped_column(String(36), ForeignKey('attribution_claims.id', name='fk_attribution_claim_evidence_claim_id', ondelete="RESTRICT"), nullable=False)
    evidence_id = mapped_column(String(36), ForeignKey('attribution_evidence.id', name='fk_attribution_claim_evidence_evidence_id', ondelete="RESTRICT"), nullable=False)
    stance = mapped_column(String(16), nullable=False)
    directness = mapped_column(String(16), nullable=False)
    rationale = mapped_column(Text, nullable=False)
    added_by = mapped_column(String(128), nullable=False)
    added_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    withdrawn_at = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("stance IN ('supports', 'contradicts', 'context')", name="ck_attribution_claim_evidence_1"),
        CheckConstraint("directness IN ('direct', 'indirect', 'context')", name="ck_attribution_claim_evidence_2"),
        CheckConstraint("stance != 'context' OR directness = 'context'", name="ck_attribution_claim_evidence_3"),
        CheckConstraint('length(trim(rationale)) > 0', name="ck_attribution_claim_evidence_4"),
        UniqueConstraint('claim_id', 'evidence_id', name="uq_attribution_claim_evidence_1"),
        Index('ix_attribution_claim_evidence_1', 'evidence_id', 'claim_id'),
        Index('ix_attribution_claim_evidence_2', 'claim_id', 'withdrawn_at'),
    )


class AttributionEvent(Base):
    __tablename__ = 'attribution_events'
    id = mapped_column(String(36), nullable=False, primary_key=True, default=new_id)
    entity_id = mapped_column(String(36), ForeignKey('attribution_entities.id', name='fk_attribution_events_entity_id', ondelete="RESTRICT"), nullable=True)
    claim_id = mapped_column(String(36), ForeignKey('attribution_claims.id', name='fk_attribution_events_claim_id', ondelete="RESTRICT"), nullable=True)
    evidence_id = mapped_column(String(36), ForeignKey('attribution_evidence.id', name='fk_attribution_events_evidence_id', ondelete="RESTRICT"), nullable=True)
    sequence = mapped_column(Integer, nullable=False)
    event_type = mapped_column(String(32), nullable=False)
    actor_kind = mapped_column(String(16), nullable=False)
    actor_ref = mapped_column(String(128), nullable=False)
    occurred_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = mapped_column(Text, nullable=False)
    payload = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint('sequence >= 1', name="ck_attribution_events_1"),
        CheckConstraint("event_type IN ('created', 'descriptor_changed', 'scope_changed', 'evidence_linked', 'evidence_changed', 'evidence_withdrawn', 'evidence_restored', 'assessment_changed', 'review_required', 'archived', 'restored')", name="ck_attribution_events_2"),
        CheckConstraint("actor_kind IN ('analyst', 'system')", name="ck_attribution_events_3"),
        CheckConstraint('(CASE WHEN entity_id IS NULL THEN 0 ELSE 1 END + CASE WHEN claim_id IS NULL THEN 0 ELSE 1 END + CASE WHEN evidence_id IS NULL THEN 0 ELSE 1 END) = 1', name="ck_attribution_events_4"),
        CheckConstraint('length(trim(reason)) > 0', name="ck_attribution_events_5"),
        CheckConstraint("evidence_id IS NULL OR (event_type = 'created' AND sequence = 1)", name="ck_attribution_events_6"),
        CheckConstraint("entity_id IS NULL OR event_type IN ('created','descriptor_changed','archived','restored')", name="ck_attribution_events_7"),
        UniqueConstraint('entity_id', 'sequence', name="uq_attribution_events_1"),
        UniqueConstraint('claim_id', 'sequence', name="uq_attribution_events_2"),
        UniqueConstraint('evidence_id', 'sequence', name="uq_attribution_events_3"),
        Index('ix_attribution_events_1', 'occurred_at', 'id'),
    )


# Metadata-created test/development DBs receive the same SQLite protections.
ATTRIBUTION_TRIGGER_SQL = {'attribution_events_no_delete': 'CREATE TRIGGER attribution_events_no_delete BEFORE DELETE ON '
                                 "attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and "
                                 "events are immutable'); END",
 'attribution_events_no_replace': 'CREATE TRIGGER attribution_events_no_replace BEFORE INSERT ON '
                                  'attribution_events WHEN EXISTS (SELECT 1 FROM attribution_events WHERE id '
                                  '= NEW.id OR (sequence = NEW.sequence AND (entity_id = NEW.entity_id OR '
                                  'claim_id = NEW.claim_id OR evidence_id = NEW.evidence_id))) BEGIN SELECT '
                                  "RAISE(ABORT, 'Attribution evidence and events are immutable'); END",
 'attribution_events_no_update': 'CREATE TRIGGER attribution_events_no_update BEFORE UPDATE ON '
                                 "attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and "
                                 "events are immutable'); END",
 'attribution_evidence_no_delete': 'CREATE TRIGGER attribution_evidence_no_delete BEFORE DELETE ON '
                                   "attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and "
                                   "events are immutable'); END",
 'attribution_evidence_no_replace': 'CREATE TRIGGER attribution_evidence_no_replace BEFORE INSERT ON '
                                    'attribution_evidence WHEN EXISTS (SELECT 1 FROM attribution_evidence '
                                    "WHERE id = NEW.id) BEGIN SELECT RAISE(ABORT, 'Attribution evidence and "
                                    "events are immutable'); END",
 'attribution_evidence_no_update': 'CREATE TRIGGER attribution_evidence_no_update BEFORE UPDATE ON '
                                   "attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and "
                                   "events are immutable'); END"}
for _trigger_name, _trigger_sql in ATTRIBUTION_TRIGGER_SQL.items():
    _table_name = _trigger_name.rsplit("_no_", 1)[0]
    event.listen(Base.metadata.tables[_table_name], "after_create", DDL(_trigger_sql).execute_if(dialect="sqlite"))


def _immutable_attribution_row(mapper, connection, target):
    raise ValueError("Attribution evidence and events are immutable")


for _immutable_model in (AttributionEvidence, AttributionEvent):
    event.listen(_immutable_model, "before_update", _immutable_attribution_row)
    event.listen(_immutable_model, "before_delete", _immutable_attribution_row)

# ED-1 Discovery persistence; no transforms execute on model construction.
import sqlalchemy as sa

class DiscoverySubject(Base):
    __table__ = sa.Table('discovery_subjects', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('namespace', sa.String(128), nullable=False),
        sa.Column('canonical_value', sa.Text, nullable=False),
        sa.Column('display_value', sa.Text, nullable=False),
        sa.Column('normalization_version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('identity_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, default=utcnow),
        sa.CheckConstraint("kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation', 'ens_name')", name="ck_discovery_subjects_1"),
        sa.CheckConstraint('normalization_version >= 1', name="ck_discovery_subjects_2"),
        sa.CheckConstraint('length(identity_sha256) = 64', name="ck_discovery_subjects_3"),
        sa.CheckConstraint('length(canonical_value) BETWEEN 1 AND 2048', name="ck_discovery_subjects_4"),
        sa.CheckConstraint('length(namespace) > 0', name="ck_discovery_subjects_5"),
        sa.CheckConstraint("kind != 'blockchain_address' OR namespace IN ('bitcoin','ethereum')", name="ck_discovery_subjects_6"),
        sa.CheckConstraint("kind != 'blockchain_address' OR namespace != 'ethereum' OR canonical_value = lower(canonical_value)", name="ck_discovery_subjects_7"),
        sa.CheckConstraint("kind != 'ens_name' OR namespace = 'ethereum'", name="ck_discovery_subjects_8"),
        sa.UniqueConstraint('identity_sha256', name="uq_discovery_subjects_1"),
    )
sa.Index("ix_discovery_subjects_1", DiscoverySubject.__table__.c.kind, DiscoverySubject.__table__.c.namespace, DiscoverySubject.__table__.c.id)

class DiscoveryRun(Base):
    __table__ = sa.Table('discovery_runs', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_runs_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_runs_parent_observation_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('root_run_id', sa.String(36), sa.ForeignKey('discovery_runs.id', name='fk_discovery_runs_root_run_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('lineage_depth', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('request_snapshot', sa.JSON, nullable=False),
        sa.Column('actor_ref', sa.String(128), nullable=False, server_default=sa.text("'local_analyst'")),
        sa.Column('status', sa.String(24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, default=utcnow),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled', 'interrupted')", name="ck_discovery_runs_1"),
        sa.CheckConstraint('version >= 1', name="ck_discovery_runs_2"),
        sa.CheckConstraint('lineage_depth >= 0', name="ck_discovery_runs_3"),
        sa.CheckConstraint('(lineage_depth = 0 AND parent_observation_id IS NULL AND root_run_id IS NULL) OR (lineage_depth > 0 AND parent_observation_id IS NOT NULL AND root_run_id IS NOT NULL)', name="ck_discovery_runs_4"),
        sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name="ck_discovery_runs_5"),
        sa.CheckConstraint('deadline_at >= created_at', name="ck_discovery_runs_6"),
        sa.UniqueConstraint('idempotency_key', name="uq_discovery_runs_1"),
    )
sa.Index("ix_discovery_runs_1", DiscoveryRun.__table__.c.subject_id, DiscoveryRun.__table__.c.created_at, DiscoveryRun.__table__.c.id)
sa.Index("ix_discovery_runs_2", DiscoveryRun.__table__.c.status, DiscoveryRun.__table__.c.created_at, DiscoveryRun.__table__.c.id)
sa.Index("ix_discovery_runs_3", DiscoveryRun.__table__.c.root_run_id, DiscoveryRun.__table__.c.created_at, DiscoveryRun.__table__.c.id)
sa.Index("ix_discovery_runs_4", DiscoveryRun.__table__.c.parent_observation_id)

class DiscoveryRunSource(Base):
    __table__ = sa.Table('discovery_run_sources', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('discovery_runs.id', name='fk_discovery_run_sources_run_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('ordinal', sa.Integer, nullable=False),
        sa.Column('transform_id', sa.String(128), nullable=False),
        sa.Column('transform_version', sa.Integer, nullable=False),
        sa.Column('source_id', sa.String(128), nullable=False),
        sa.Column('source_version', sa.Integer, nullable=False),
        sa.Column('config_generation', sa.String(64), nullable=False),
        sa.Column('descriptor_snapshot', sa.JSON, nullable=False),
        sa.Column('parameters', sa.JSON, nullable=False),
        sa.Column('query_fingerprint', sa.String(64), nullable=False),
        sa.Column('cache_from_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_run_sources_cache_from_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('status', sa.String(24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_policy_id', sa.String(128), nullable=False),
        sa.Column('coverage', sa.String(24), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('provider_total', sa.Integer, nullable=True),
        sa.Column('returned_count', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('requests_reserved', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('requests_attempted', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('cost_unit', sa.String(32), nullable=False),
        sa.Column('units_reserved', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('units_consumed', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('quota_bucket', sa.String(128), nullable=False),
        sa.Column('quota_window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('quota_snapshot', sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('attempt_log', sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('retry_after_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'cache_hit', 'manual_ready', 'unavailable', 'rate_limited', 'budget_exhausted', 'timeout', 'failed', 'cancelled', 'interrupted')", name="ck_discovery_run_sources_1"),
        sa.CheckConstraint("coverage IN ('bounded', 'provider_incomplete', 'limit_reached', 'unknown')", name="ck_discovery_run_sources_2"),
        sa.CheckConstraint('ordinal > 0 AND transform_version > 0 AND source_version > 0', name="ck_discovery_run_sources_3"),
        sa.CheckConstraint('returned_count >= 0 AND requests_reserved >= 0 AND requests_attempted >= 0 AND units_reserved >= 0 AND units_consumed >= 0', name="ck_discovery_run_sources_4"),
        sa.CheckConstraint('provider_total IS NULL OR provider_total >= 0', name="ck_discovery_run_sources_5"),
        sa.CheckConstraint("status NOT IN ('cache_hit','manual_ready') OR (requests_attempted = 0 AND units_consumed = 0)", name="ck_discovery_run_sources_6"),
        sa.CheckConstraint("(status = 'cache_hit') = (cache_from_id IS NOT NULL)", name="ck_discovery_run_sources_7"),
        sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name="ck_discovery_run_sources_8"),
        sa.UniqueConstraint('run_id', 'ordinal', name="uq_discovery_run_sources_1"),
        sa.UniqueConstraint('run_id', 'transform_id', 'source_id', name="uq_discovery_run_sources_2"),
    )
sa.Index("ix_discovery_run_sources_1", DiscoveryRunSource.__table__.c.query_fingerprint, DiscoveryRunSource.__table__.c.status, DiscoveryRunSource.__table__.c.expires_at, DiscoveryRunSource.__table__.c.completed_at)
sa.Index("ix_discovery_run_sources_2", DiscoveryRunSource.__table__.c.quota_bucket, DiscoveryRunSource.__table__.c.quota_window_start, DiscoveryRunSource.__table__.c.status)
sa.Index("ix_discovery_run_sources_3", DiscoveryRunSource.__table__.c.cache_from_id)

class DiscoveryResult(Base):
    __table__ = sa.Table('discovery_results', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('query_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_query_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('predicate', sa.String(64), nullable=False),
        sa.Column('from_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_from_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('to_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_to_subject_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('fact_key', sa.JSON, nullable=False),
        sa.Column('identity_sha256', sa.String(64), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('material_revision', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('review_status', sa.String(16), nullable=False, server_default=sa.text("'unreviewed'")),
        sa.Column('reviewed_material_revision', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("kind IN ('candidate_evidence', 'candidate_identifier', 'candidate_relationship')", name="ck_discovery_results_1"),
        sa.CheckConstraint("predicate IN ('mentioned_at', 'repository_contains', 'explorer_labeled_as', 'locally_labeled_as', 'publicly_listed_by', 'reverse_name_record', 'resolves_to', 'registration_record_for', 'certificate_names', 'observed_at', 'archived_at', 'uses_tracking_id', 'advertises_at', 'mentions_wallet', 'publicly_labeled_as')", name="ck_discovery_results_2"),
        sa.CheckConstraint("review_status IN ('unreviewed', 'relevant', 'irrelevant')", name="ck_discovery_results_3"),
        sa.CheckConstraint('material_revision >= 1 AND version >= 1', name="ck_discovery_results_4"),
        sa.CheckConstraint('reviewed_material_revision BETWEEN 0 AND material_revision', name="ck_discovery_results_5"),
        sa.CheckConstraint('last_seen_at >= first_seen_at', name="ck_discovery_results_6"),
        sa.UniqueConstraint('identity_sha256', name="uq_discovery_results_1"),
    )
sa.Index("ix_discovery_results_1", DiscoveryResult.__table__.c.query_subject_id, DiscoveryResult.__table__.c.last_seen_at, DiscoveryResult.__table__.c.id)
sa.Index("ix_discovery_results_2", DiscoveryResult.__table__.c.from_subject_id, DiscoveryResult.__table__.c.predicate, DiscoveryResult.__table__.c.id)
sa.Index("ix_discovery_results_3", DiscoveryResult.__table__.c.to_subject_id, DiscoveryResult.__table__.c.predicate, DiscoveryResult.__table__.c.id)
sa.Index("ix_discovery_results_4", DiscoveryResult.__table__.c.review_status, DiscoveryResult.__table__.c.last_seen_at, DiscoveryResult.__table__.c.id)

class DiscoveryObservation(Base):
    __table__ = sa.Table('discovery_observations', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('result_id', sa.String(36), sa.ForeignKey('discovery_results.id', name='fk_discovery_observations_result_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('execution_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_observations_execution_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_record_key', sa.String(512), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('source_url', sa.Text, nullable=True),
        sa.Column('source_locator', sa.String(512), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text, nullable=False),
        sa.Column('excerpt', sa.Text, nullable=True),
        sa.Column('excerpt_complete', sa.Boolean, nullable=False, server_default=sa.text('0')),
        sa.Column('verification', sa.String(32), nullable=False),
        sa.Column('match_context', sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('source_class', sa.String(40), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('observed_on', sa.Date, nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_on', sa.Date, nullable=True),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_snapshot', sa.JSON, nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('origin_label_id', sa.String(36), sa.ForeignKey('labels.id', name='fk_discovery_observations_origin_label_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('origin_match_id', sa.String(36), sa.ForeignKey('kyc_matches.id', name='fk_discovery_observations_origin_match_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, default=utcnow),
        sa.CheckConstraint("kind IN ('search_result', 'code_search_result', 'local_label_snapshot', 'verified_page_observation', 'explorer_annotation', 'name_service_record', 'research_result', 'archive_index_record', 'analyst_capture')", name="ck_discovery_observations_1"),
        sa.CheckConstraint("verification IN ('not_checked', 'exact_in_excerpt', 'exact_in_document', 'technical_verified', 'mismatch', 'not_applicable')", name="ck_discovery_observations_2"),
        sa.CheckConstraint('length(content_sha256) = 64', name="ck_discovery_observations_3"),
        sa.CheckConstraint('observed_at IS NULL OR observed_on IS NULL', name="ck_discovery_observations_4"),
        sa.CheckConstraint('published_at IS NULL OR published_on IS NULL', name="ck_discovery_observations_5"),
        sa.CheckConstraint('origin_label_id IS NULL OR origin_match_id IS NULL', name="ck_discovery_observations_6"),
        sa.CheckConstraint("kind != 'local_label_snapshot' OR origin_label_id IS NOT NULL", name="ck_discovery_observations_7"),
        sa.CheckConstraint("length(trim(coalesce(source_url,''))) > 0 OR length(trim(coalesce(source_locator,''))) > 0", name="ck_discovery_observations_8"),
        sa.UniqueConstraint('execution_id', 'result_id', 'source_record_key', 'content_sha256', name="uq_discovery_observations_1"),
    )
sa.Index("ix_discovery_observations_1", DiscoveryObservation.__table__.c.result_id, DiscoveryObservation.__table__.c.retrieved_at, DiscoveryObservation.__table__.c.id)
sa.Index("ix_discovery_observations_2", DiscoveryObservation.__table__.c.result_id, DiscoveryObservation.__table__.c.content_sha256)
sa.Index("ix_discovery_observations_3", DiscoveryObservation.__table__.c.origin_label_id)
sa.Index("ix_discovery_observations_4", DiscoveryObservation.__table__.c.origin_match_id)

class DiscoveryRunItem(Base):
    __table__ = sa.Table('discovery_run_items', Base.metadata,
        sa.Column('run_source_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_run_items_run_source_id', ondelete='RESTRICT'), nullable=False, primary_key=True),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_run_items_observation_id', ondelete='RESTRICT'), nullable=False, primary_key=True),
        sa.Column('ordinal', sa.Integer, nullable=False),
        sa.Column('rank', sa.Integer, nullable=True),
        sa.Column('included_at', sa.DateTime(timezone=True), nullable=False, default=utcnow),
        sa.Column('inclusion_kind', sa.String(16), nullable=False),
        sa.CheckConstraint('ordinal > 0', name="ck_discovery_run_items_1"),
        sa.CheckConstraint('rank IS NULL OR rank >= 0', name="ck_discovery_run_items_2"),
        sa.CheckConstraint("inclusion_kind IN ('retrieved', 'local', 'cache')", name="ck_discovery_run_items_3"),
        sa.UniqueConstraint('run_source_id', 'ordinal', name="uq_discovery_run_items_1"),
    )
sa.Index("ix_discovery_run_items_1", DiscoveryRunItem.__table__.c.observation_id)

class DiscoveryReview(Base):
    __table__ = sa.Table('discovery_reviews', Base.metadata,
        sa.Column('id', sa.String(36), nullable=False, primary_key=True, default=new_id),
        sa.Column('result_id', sa.String(36), sa.ForeignKey('discovery_results.id', name='fk_discovery_reviews_result_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_reviews_observation_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.Column('material_revision', sa.Integer, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('actor_ref', sa.String(128), nullable=False, server_default=sa.text("'local_analyst'")),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, default=utcnow),
        sa.CheckConstraint('sequence > 0 AND material_revision > 0', name="ck_discovery_reviews_1"),
        sa.CheckConstraint("status IN ('unreviewed', 'relevant', 'irrelevant')", name="ck_discovery_reviews_2"),
        sa.CheckConstraint('length(trim(reason)) BETWEEN 1 AND 4000', name="ck_discovery_reviews_3"),
        sa.UniqueConstraint('result_id', 'sequence', name="uq_discovery_reviews_1"),
    )
sa.Index("ix_discovery_reviews_1", DiscoveryReview.__table__.c.observation_id)
sa.Index("ix_discovery_reviews_2", DiscoveryReview.__table__.c.occurred_at, DiscoveryReview.__table__.c.id)

DISCOVERY_TRIGGER_SQL = {'discovery_observations_no_update': "CREATE TRIGGER discovery_observations_no_update BEFORE UPDATE ON discovery_observations BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_observations_no_delete': "CREATE TRIGGER discovery_observations_no_delete BEFORE DELETE ON discovery_observations BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_observations_no_replace': "CREATE TRIGGER discovery_observations_no_replace BEFORE INSERT ON discovery_observations WHEN EXISTS (SELECT 1 FROM discovery_observations WHERE id = NEW.id OR (execution_id = NEW.execution_id AND result_id = NEW.result_id AND source_record_key = NEW.source_record_key AND content_sha256 = NEW.content_sha256)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_run_items_no_update': "CREATE TRIGGER discovery_run_items_no_update BEFORE UPDATE ON discovery_run_items BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_run_items_no_delete': "CREATE TRIGGER discovery_run_items_no_delete BEFORE DELETE ON discovery_run_items BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_run_items_no_replace': "CREATE TRIGGER discovery_run_items_no_replace BEFORE INSERT ON discovery_run_items WHEN EXISTS (SELECT 1 FROM discovery_run_items WHERE (run_source_id = NEW.run_source_id AND observation_id = NEW.observation_id) OR (run_source_id = NEW.run_source_id AND ordinal = NEW.ordinal)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_reviews_no_update': "CREATE TRIGGER discovery_reviews_no_update BEFORE UPDATE ON discovery_reviews BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_reviews_no_delete': "CREATE TRIGGER discovery_reviews_no_delete BEFORE DELETE ON discovery_reviews BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END", 'discovery_reviews_no_replace': "CREATE TRIGGER discovery_reviews_no_replace BEFORE INSERT ON discovery_reviews WHEN EXISTS (SELECT 1 FROM discovery_reviews WHERE id = NEW.id OR (result_id = NEW.result_id AND sequence = NEW.sequence)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END"}
for _name, _sql in DISCOVERY_TRIGGER_SQL.items():
    _table = next(table for table in Base.metadata.tables.values() if _name.startswith(table.name + '_no_'))
    event.listen(_table, 'after_create', DDL(_sql).execute_if(dialect='sqlite'))

def _immutable_discovery_row(mapper, connection, target):
    raise ValueError('Discovery history is immutable')

for _model in (DiscoveryObservation, DiscoveryReview, DiscoveryRunItem):
    event.listen(_model, 'before_update', _immutable_discovery_row)
    event.listen(_model, 'before_delete', _immutable_discovery_row)


# ED-6 immutable cross-subsystem provenance. Stance/rationale history belongs to
# the referenced Attribution link and events, not a mutable copy here.
class DiscoveryPromotion(Base):
    __tablename__ = 'discovery_promotions'
    id = mapped_column(String(36), primary_key=True, default=new_id)
    observation_id = mapped_column(String(36), ForeignKey('discovery_observations.id', name='fk_discovery_promotions_observation_id', ondelete='RESTRICT'), nullable=False)
    claim_id = mapped_column(String(36), ForeignKey('attribution_claims.id', name='fk_discovery_promotions_claim_id', ondelete='RESTRICT'), nullable=False)
    evidence_id = mapped_column(String(36), ForeignKey('attribution_evidence.id', name='fk_discovery_promotions_evidence_id', ondelete='RESTRICT'), nullable=False)
    link_id = mapped_column(String(36), ForeignKey('attribution_claim_evidence.id', name='fk_discovery_promotions_link_id', ondelete='RESTRICT'), nullable=False)
    source_fingerprint = mapped_column(String(64), nullable=False)
    capture_fingerprint = mapped_column(String(64), nullable=False)
    claim_version_before = mapped_column(Integer, nullable=False)
    claim_version_after = mapped_column(Integer, nullable=False)
    actor_ref = mapped_column(String(128), nullable=False, default='local_analyst', server_default=text("'local_analyst'"))
    created_at = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        UniqueConstraint('observation_id','claim_id',name='uq_discovery_promotions_1'),
        CheckConstraint('length(source_fingerprint) = 64 AND length(capture_fingerprint) = 64',name='ck_discovery_promotions_1'),
        CheckConstraint('claim_version_before >= 1 AND claim_version_after = claim_version_before + 1',name='ck_discovery_promotions_2'),
        CheckConstraint("actor_ref = 'local_analyst'",name='ck_discovery_promotions_3'),
        Index('ix_discovery_promotions_1','claim_id','created_at','id'),
        Index('ix_discovery_promotions_2','evidence_id'),
        Index('ix_discovery_promotions_3','link_id'),
    )

PROMOTION_TRIGGER_SQL = {
    'discovery_promotions_no_update': "CREATE TRIGGER discovery_promotions_no_update BEFORE UPDATE ON discovery_promotions BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END",
    'discovery_promotions_no_delete': "CREATE TRIGGER discovery_promotions_no_delete BEFORE DELETE ON discovery_promotions BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END",
    'discovery_promotions_no_replace': "CREATE TRIGGER discovery_promotions_no_replace BEFORE INSERT ON discovery_promotions WHEN EXISTS (SELECT 1 FROM discovery_promotions WHERE id = NEW.id OR (observation_id = NEW.observation_id AND claim_id = NEW.claim_id)) BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END",
    'discovery_promotions_valid_link': "CREATE TRIGGER discovery_promotions_valid_link BEFORE INSERT ON discovery_promotions WHEN NOT EXISTS (SELECT 1 FROM attribution_claim_evidence l JOIN attribution_evidence e ON e.id = l.evidence_id WHERE l.id = NEW.link_id AND l.claim_id = NEW.claim_id AND l.evidence_id = NEW.evidence_id AND e.origin_discovery_observation_id = NEW.observation_id AND e.content_sha256 = NEW.capture_fingerprint) BEGIN SELECT RAISE(ABORT, 'Discovery promotion references must agree'); END",
}
for _sql in PROMOTION_TRIGGER_SQL.values():
    event.listen(DiscoveryPromotion.__table__, 'after_create', DDL(_sql).execute_if(dialect='sqlite'))
event.listen(DiscoveryPromotion, 'before_update', _immutable_discovery_row)
event.listen(DiscoveryPromotion, 'before_delete', _immutable_discovery_row)
