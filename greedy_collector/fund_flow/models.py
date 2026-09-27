from sqlalchemy import Column, String, JSON, Index
from sqlalchemy.orm import declarative_base
Base=declarative_base()
class FlowRun(Base):
    __tablename__='fund_flow_runs'
    id=Column(String(36),primary_key=True)
    chain=Column(String(32),nullable=False)
    source=Column(String(128),nullable=False)
    created_at=Column(String(40),nullable=False)
    snapshot=Column(JSON,nullable=False)
    __table_args__=(Index('ix_fund_flow_runs_source','chain','source','created_at'),)
