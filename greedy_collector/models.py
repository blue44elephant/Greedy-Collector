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
