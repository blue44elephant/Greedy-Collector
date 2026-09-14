"""Regression found by ED-3 using the application's actual SessionLocal options."""
import asyncio
from sqlalchemy.orm import sessionmaker
from tests.test_discovery_execution import h,job

def test_executor_preserves_reservation_with_application_session_options(h):
    h.sessions=sessionmaker(h.engine,autoflush=False,expire_on_commit=False)
    h.runtime.sessions=h.sessions
    executor=h.bind()
    row=asyncio.run(job(h))
    assert row['status']=='completed'
    assert executor.calls==1
    assert row['sources'][0]['requests_reserved']==1
    assert row['sources'][0]['requests_attempted']==1
    assert row['sources'][0]['units_consumed']==1
    assert row['sources'][0]['quota_snapshot']['policy']['units_per_request']==1
