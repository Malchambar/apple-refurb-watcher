from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Base

_ENGINE_CACHE: dict[str, Engine] = {}
_SESSION_FACTORY_CACHE: dict[str, sessionmaker[Session]] = {}


def _resolve_sqlite_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    relative = database_url.replace("sqlite:///", "", 1)
    return Path(relative)


def ensure_database_directory(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return
    db_path = _resolve_sqlite_path(database_url)
    if db_path is None:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(database_url: str) -> Engine:
    if database_url not in _ENGINE_CACHE:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _ENGINE_CACHE[database_url] = create_engine(
            database_url,
            future=True,
            connect_args=connect_args,
        )
    return _ENGINE_CACHE[database_url]


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    if database_url not in _SESSION_FACTORY_CACHE:
        _SESSION_FACTORY_CACHE[database_url] = sessionmaker(
            bind=get_engine(database_url),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SESSION_FACTORY_CACHE[database_url]


def init_db(database_url: str) -> None:
    ensure_database_directory(database_url)
    engine = get_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    required = set(Base.metadata.tables.keys())
    if required.issubset(table_names):
        return
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session(database_url: str) -> Iterator[Session]:
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
