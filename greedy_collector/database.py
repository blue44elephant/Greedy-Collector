from contextlib import contextmanager
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base


def _ensure_sqlite_directory(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    path = url.removeprefix("sqlite:///")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _enable_sqlite_foreign_keys(dbapi_conn, connection_record):
    """Enable PRAGMA foreign_keys=ON for SQLite connections.
    
    This ensures foreign-key constraints are enforced on every connection.
    Called automatically via SQLAlchemy connection event.
    Only applies to SQLite; other databases are unaffected.
    """
    if "sqlite" in str(dbapi_conn):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_fk_enabled_engine(url, **engine_kwargs):
    """Create a SQLAlchemy engine with SQLite FK enforcement enabled.
    
    Scope: Greedy Collector engines only.
    Non-SQLite database URLs are unaffected by FK enforcement.
    
    Args:
        url: Database URL
        **engine_kwargs: Additional arguments passed to create_engine()
    
    Returns:
        SQLAlchemy Engine with FK enforcement listener registered
    """
    created_engine = create_engine(url, **engine_kwargs)
    # Register FK enforcement for this specific engine only (not global)
    event.listen(created_engine, "connect", _enable_sqlite_foreign_keys)
    return created_engine


settings = get_settings()
_ensure_sqlite_directory(settings.database_url)
engine = create_fk_enabled_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_database() -> None:
    # Existing workspaces retain their startup behavior; both new families are migration-only.
    legacy_tables = [table for table in Base.metadata.tables.values()
                     if not table.name.startswith(("attribution_", "discovery_"))]
    Base.metadata.create_all(bind=engine, tables=legacy_tables)


@contextmanager
def session_scope():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
