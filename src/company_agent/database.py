"""Database connection, engine configuration, and session management."""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from company_agent.config import settings

# SQLite connection arguments for concurrency & WAL mode
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30.0}

# Global SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
)

# Enable WAL (Write-Ahead Logging) mode on SQLite for high-concurrency safety
if settings.DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base
Base = declarative_base()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Provide a transactional database session context."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initializes tables and records schema version."""
    import company_agent.models  # Ensure models are imported before create_all
    # Ensure data directory exists
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    
    with get_db_session() as session:
        from company_agent.models import SchemaVersion
        existing = session.query(SchemaVersion).filter_by(version="1.0.0").first()
        if not existing:
            session.add(SchemaVersion(version="1.0.0", description="Initial competition ready schema"))
