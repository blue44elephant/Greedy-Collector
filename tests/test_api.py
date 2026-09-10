from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from greedy_collector.database import get_db, create_fk_enabled_engine
from greedy_collector.models import Base
from greedy_collector.router import router


engine = create_fk_enabled_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)


def override_db():
    with Session(engine) as session:
        yield session


app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def test_status_and_openapi():
    assert client.get("/api/greedy-collector/status").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/greedy-collector/kyc/screen" in schema["paths"]


def test_case_and_watchlist_workflow():
    case = client.post(
        "/api/greedy-collector/cases",
        json={"title": "Review Case", "description": "Fixture"},
    )
    assert case.status_code == 200
    wallet = client.post(
        "/api/greedy-collector/watchlist",
        json={
            "chain": "bitcoin",
            "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "label": "Genesis fixture",
            "case_id": case.json()["id"],
        },
    )
    assert wallet.status_code == 200
    dashboard = client.get("/api/greedy-collector/dashboard").json()
    assert dashboard["statistics"]["total_watched_wallets"] == 1


def test_reports_include_disclaimer():
    case = client.post(
        "/api/greedy-collector/cases",
        json={"title": "Report Case", "description": "Fixture"},
    ).json()
    report = client.get(
        f"/api/greedy-collector/reports/{case['id']}?format=markdown"
    )
    assert report.status_code == 200
    assert "does not prove criminal activity" in report.text


def test_sqlite_foreign_keys_enforcement():
    """Regression test: verify PRAGMA foreign_keys is ON and FK constraints are enforced."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from greedy_collector.models import WalletAlert
    
    # Verify PRAGMA foreign_keys is enabled
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "PRAGMA foreign_keys should be 1 (ON), but got {}".format(result)
    
    # Verify invalid FK is rejected (no Case with this ID exists)
    with Session(engine) as session:
        invalid_alert = WalletAlert(
            wallet="test_fk_check",
            chain="bitcoin",
            tx_hash="tx_fk_test",
            trigger_type="test",
            severity="high",
            risk_score=50,
            explanation="Testing FK enforcement",
            case_id="nonexistent-case-id-does-not-exist",
            dedupe_key="fk_enforcement_test_001"
        )
        session.add(invalid_alert)
        
        # Should raise IntegrityError due to FK constraint
        try:
            session.commit()
            # If we get here, FK enforcement is not working
            assert False, "Expected IntegrityError for invalid FK, but insert succeeded"
        except IntegrityError:
            # Expected: FK constraint violation
            session.rollback()
            # This is the correct behavior
            pass
