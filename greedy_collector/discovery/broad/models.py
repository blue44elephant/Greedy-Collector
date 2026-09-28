"""Supplementary candidate reviews; observations remain in existing Discovery tables."""
from sqlalchemy import Column,String,Integer,JSON,ForeignKey,UniqueConstraint
from sqlalchemy.orm import declarative_base
Base=declarative_base()
class Candidate(Base):
    __tablename__='discovery_broad_candidates'
    id=Column(String(64),primary_key=True)
    observation_id=Column(String(36),nullable=False)
    chain=Column(String(32),nullable=False)
    wallet=Column(String(128),nullable=False)
    provider=Column(String(128),nullable=False)
    kind=Column(String(16),nullable=False)
    value=Column(String(255),nullable=False)
    canonical_url=Column(String(2048),nullable=False)
    material=Column(JSON,nullable=False)
    status=Column(String(16),nullable=False,default='unreviewed')
    version=Column(Integer,nullable=False,default=1)
class Review(Base):
    __tablename__='discovery_broad_candidate_reviews'
    id=Column(String(36),primary_key=True)
    candidate_id=Column(String(64),ForeignKey(Candidate.id),nullable=False)
    sequence=Column(Integer,nullable=False)
    status=Column(String(16),nullable=False)
    note=Column(String(2000),nullable=False)
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint('candidate_id','sequence'),)
