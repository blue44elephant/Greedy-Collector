"""Migration-only tables, deliberately separate from legacy startup create_all."""
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import declarative_base
Base = declarative_base()

class Cluster(Base):
    __tablename__ = "technical_clusters"
    id = Column(String(36), primary_key=True)
    chain = Column(String(32), nullable=False, index=True)
    current_version = Column(Integer, nullable=False)
    created_at = Column(String(40), nullable=False)

class Version(Base):
    __tablename__ = "technical_cluster_versions"
    id = Column(String(36), primary_key=True)
    cluster_id = Column(String(36), ForeignKey("technical_clusters.id"), nullable=False)
    number = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("cluster_id", "number"),)

class Member(Base):
    __tablename__ = "technical_cluster_members"
    version_id = Column(String(36), ForeignKey("technical_cluster_versions.id"), primary_key=True)
    address = Column(String(128), primary_key=True)
    chain = Column(String(32), nullable=False)
    __table_args__ = (Index("ix_technical_member_lookup", "chain", "address"),)

class Evidence(Base):
    __tablename__ = "technical_cluster_evidence"
    id = Column(String(64), primary_key=True)
    chain = Column(String(32), nullable=False)
    tx_hash = Column(String(128), nullable=False)
    material = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False)
    __table_args__ = (Index("ix_technical_evidence_transaction", "chain", "tx_hash"),)

class Exclusion(Base):
    __tablename__ = "technical_cluster_exclusions"
    id = Column(String(36), primary_key=True)
    evidence_id = Column(String(64), ForeignKey("technical_cluster_evidence.id"), nullable=False)
    chain = Column(String(32), nullable=False)
    tx_hash = Column(String(128), nullable=False)
    reason = Column(String(1000), nullable=False)
    created_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("chain", "tx_hash"),)

class Link(Base):
    __tablename__ = "technical_cluster_evidence_links"
    version_id = Column(String(36), ForeignKey("technical_cluster_versions.id"), primary_key=True)
    evidence_id = Column(String(64), ForeignKey("technical_cluster_evidence.id"), primary_key=True)
