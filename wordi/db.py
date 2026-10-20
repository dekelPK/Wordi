from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


def normalize_url(url: str) -> str:
    """Accept the plain postgres URLs that hosting providers hand out (Neon, Render, …)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_url(url)
    kwargs: dict = {}
    if url.startswith("postgresql"):
        # Serverless Postgres (e.g. Neon) drops idle connections: check before use, recycle often.
        kwargs.update(pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
