"""Migration-only append-only records, separate from blockchain/identity state."""
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, Table, Index, UniqueConstraint, event
from sqlalchemy.orm import declarative_base

Base = declarative_base()
Table("cases", Base.metadata, Column("id", String(36), primary_key=True))

class Profile(Base):
    __tablename__ = "narcotics_case_profiles"
    id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("cases.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("case_id", "revision"),)

class Substance(Base):
    __tablename__ = "narcotics_profile_substances"
    id = Column(String(36), primary_key=True)
    profile_id = Column(String(36), ForeignKey("narcotics_case_profiles.id"), nullable=False, index=True)
    case_id = Column(String(36), ForeignKey("cases.id"), nullable=False)
    category = Column(String(160), nullable=True)
    record = Column(JSON, nullable=False)

class Logistics(Base):
    __tablename__ = "narcotics_logistics_objects"
    id = Column(String(36), primary_key=True)
    profile_id = Column(String(36), ForeignKey("narcotics_case_profiles.id"), nullable=False, index=True)
    case_id = Column(String(36), ForeignKey("cases.id"), nullable=False)
    record = Column(JSON, nullable=False)

class Identifier(Base):
    __tablename__ = "narcotics_profile_identifiers"
    id = Column(String(36), primary_key=True)
    profile_id = Column(String(36), ForeignKey("narcotics_case_profiles.id"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    value = Column(String(300), nullable=False)
    __table_args__ = (Index("ix_narcotics_identifiers_lookup", "kind", "value"),)

class Fingerprint(Base):
    __tablename__ = "narcotics_mo_fingerprints"
    id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("cases.id"), nullable=False, index=True)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)

class LinkRun(Base):
    __tablename__ = "narcotics_case_link_runs"
    id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("cases.id"), nullable=False, index=True)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)

class Link(Base):
    __tablename__ = "narcotics_case_links"
    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("narcotics_case_link_runs.id"), nullable=False, index=True)
    case_a = Column(String(36), ForeignKey("cases.id"), nullable=False)
    case_b = Column(String(36), ForeignKey("cases.id"), nullable=False)
    link_type = Column(String(48), nullable=False)
    strength = Column(String(16), nullable=False)
    record = Column(JSON, nullable=False)

class Review(Base):
    __tablename__ = "narcotics_link_reviews"
    id = Column(String(36), primary_key=True)
    link_id = Column(String(36), ForeignKey("narcotics_case_links.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("link_id", "sequence"),)

class Nexus(Base):
    __tablename__ = "narcotics_nexus_runs"
    id = Column(String(36), primary_key=True)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)

class Priority(Base):
    __tablename__ = "narcotics_priority_runs"
    id = Column(String(36), primary_key=True)
    nexus_id = Column(String(36), ForeignKey("narcotics_nexus_runs.id"), nullable=False, index=True)
    created_at = Column(String(40), nullable=False)
    record = Column(JSON, nullable=False)

RECORD_MODELS = (Profile, Substance, Logistics, Identifier, Fingerprint, LinkRun, Link, Review, Nexus, Priority)
def immutable(*args):
    raise ValueError("Narcotics intelligence history is immutable")
for model in RECORD_MODELS:
    event.listen(model, "before_update", immutable)
    event.listen(model, "before_delete", immutable)
