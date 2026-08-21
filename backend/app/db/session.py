"""Engine and session management.

The API and the Celery workers share one engine configuration but obtain sessions
differently: FastAPI uses the `get_db` dependency, workers use the `session_scope`
context manager.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
_sqlite_memory = _is_sqlite and (":memory:" in settings.database_url)

if _is_sqlite:
    # StaticPool (one shared connection) is only safe for in-memory SQLite. A file
    # database under FastAPI's threadpool must not share a connection or sqlite3
    # raises InterfaceError: "bad parameter or other API misuse".
    sqlite_kwargs: dict = {
        "connect_args": {"check_same_thread": False, "timeout": 30},
        "echo": settings.db_echo,
        "future": True,
    }
    if _sqlite_memory:
        sqlite_kwargs["poolclass"] = StaticPool
    engine = create_engine(settings.database_url, **sqlite_kwargs)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if not _sqlite_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

else:
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        echo=settings.db_echo,
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Commits on success, rolls back on any exception."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for Celery tasks and scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
