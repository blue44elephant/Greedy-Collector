"""Append-only capture, review and promotion material (separate metadata)."""
from sqlalchemy import Column,String,Integer,JSON,LargeBinary,UniqueConstraint
from sqlalchemy.orm import declarative_base
Base=declarative_base()
class PublicSourceCapture(Base):
    __tablename__='discovery_public_captures'
    id=Column(String(36),primary_key=True)
    observation_id=Column(String(36),nullable=False)
    result_id=Column(String(36),nullable=False)
    normalized_url=Column(String(2048),nullable=False)
    retrieved_at=Column(String(40),nullable=False)
    body_sha256=Column(String(64))
    status=Column(String(16),nullable=False)
    material=Column(JSON,nullable=False)
    raw_body=Column(LargeBinary)
class CaptureReview(Base):
    __tablename__='discovery_capture_reviews'
    id=Column(String(36),primary_key=True)
    capture_id=Column(String(36),nullable=False)
    sequence=Column(Integer,nullable=False)
    status=Column(String(16),nullable=False)
    note=Column(String(2000),nullable=False)
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint('capture_id','sequence'),)
class CapturePromotion(Base):
    __tablename__='discovery_capture_promotions'
    id=Column(String(36),primary_key=True)
    capture_id=Column(String(36),nullable=False)
    claim_id=Column(String(36),nullable=False)
    evidence_id=Column(String(36),nullable=False)
    link_id=Column(String(36),nullable=False)
    source_fingerprint=Column(String(64),nullable=False)
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint('capture_id','claim_id'),)
