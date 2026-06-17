"""Database engine and session factory.

DATABASE_URL defaults to SQLite (local). Set it to a postgres:// URL in production.
"""

from __future__ import annotations

import os

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./overlay.db")

_connect_args = (
    {"check_same_thread": False} if _DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(_DATABASE_URL, connect_args=_connect_args)


@event.listens_for(engine, "connect")
def _set_sqlite_wal(dbapi_conn, _):
    if _DATABASE_URL.startswith("sqlite"):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")


def get_session():
    with Session(engine) as session:
        yield session


def create_tables():
    SQLModel.metadata.create_all(engine)
