from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
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
    __table_args__ = (
        CheckConstraint("evidence_type IN ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation')", name="ck_attribution_evidence_1"),
        CheckConstraint("origin IN ('public_osint', 'analyst_added', 'commercial_proprietary', 'privileged_nonpublic')", name="ck_attribution_evidence_2"),
        CheckConstraint("collection_method IN ('analyst_entry', 'label_snapshot', 'research_snapshot')", name="ck_attribution_evidence_3"),
        CheckConstraint("source_reliability IN ('unassessed', 'reliable', 'uncertain', 'unreliable')", name="ck_attribution_evidence_4"),
        CheckConstraint('length(trim(title)) > 0 AND length(trim(summary)) > 0 AND length(trim(source_name)) > 0', name="ck_attribution_evidence_5"),
        CheckConstraint('length(content_sha256) = 64', name="ck_attribution_evidence_6"),
        CheckConstraint("source_reliability = 'unassessed' OR length(trim(reliability_rationale)) > 0", name="ck_attribution_evidence_7"),
        CheckConstraint("(collection_method = 'analyst_entry' AND origin_label_id IS NULL AND origin_match_id IS NULL AND evidence_type NOT IN ('label_snapshot','research_snapshot')) OR (collection_method = 'label_snapshot' AND origin_label_id IS NOT NULL AND origin_match_id IS NULL AND evidence_type = 'label_snapshot') OR (collection_method = 'research_snapshot' AND origin_match_id IS NOT NULL AND origin_label_id IS NULL AND evidence_type = 'research_snapshot')", name="ck_attribution_evidence_8"),
        CheckConstraint("(evidence_type = 'analyst_observation' AND length(trim(analyst_note)) > 0) OR (evidence_type != 'analyst_observation' AND (length(trim(coalesce(source_url,''))) > 0 OR length(trim(coalesce(source_locator,''))) > 0))", name="ck_attribution_evidence_9"),
        Index('ix_attribution_evidence_1', 'captured_at', 'id'),
        Index('ix_attribution_evidence_2', 'content_sha256'),
        Index('ix_attribution_evidence_3', 'source_catalog_id', 'captured_at'),
        Index('ix_attribution_evidence_4', 'origin_label_id'),
        Index('ix_attribution_evidence_5', 'origin_match_id'),
        Index('ix_attribution_evidence_6', 'origin_group'),
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
