"""Database engine, session factory, and schema bootstrap.

SQLite is the default for local development and early deployment. The
engine is module-global and cached via :func:`get_engine` so tests can
swap it out with :func:`configure_engine`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def _apply_sqlite_pragmas(engine: Engine) -> None:
    """Enable WAL + foreign keys when the engine points at SQLite.

    WAL mode makes concurrent reads during background refreshes cheap;
    foreign keys are off by default in SQLite and we want them on.
    """

    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def configure_engine(database_url: str) -> Engine:
    """Build an engine for the given URL and install SQLite pragmas.

    Exposed for tests that want an isolated in-memory engine.
    """

    engine_kwargs: dict[str, object] = {"echo": False}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **engine_kwargs)
    _apply_sqlite_pragmas(engine)
    return engine


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first call."""

    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = configure_engine(settings.database_url)
    return _engine


def reset_engine() -> None:
    """Dispose of the cached engine; used by tests."""

    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    """Create all tables for the currently-configured engine."""

    SQLModel.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a SQLModel ``Session`` that commits on success, rolls back on error."""

    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
