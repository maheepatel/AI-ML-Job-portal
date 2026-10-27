from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import DATA_DIR, settings
from .models import Base


def _normalise_url(url: str) -> str:
    """Accept provider URLs as pasted (Neon/Render give postgres:// or postgresql://)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalise_url(settings.database_url)
_is_sqlite = DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Path(DATABASE_URL.split("sqlite:///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)

if _is_sqlite:
    _connect_args: dict = {"check_same_thread": False, "timeout": 30}
else:
    # Pooled endpoints (PgBouncer, e.g. Neon "-pooler" hosts) break server-side prepared statements.
    _connect_args = {"prepare_threshold": None} if "-pooler" in DATABASE_URL else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    # Serverless Postgres (Neon) drops idle connections when it suspends; recycle before that.
    pool_recycle=-1 if _is_sqlite else 240,
    pool_size=5,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _record):
        # WAL lets the API keep reading while the worker writes a run.
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    _seed_if_empty()
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _seed_if_empty() -> None:
    """On a fresh disk, start from the bundled snapshot instead of an empty site."""
    if not _is_sqlite or not settings.seed_db.exists():
        return
    target = Path(DATABASE_URL.split("sqlite:///", 1)[1])
    if target.exists() and target.stat().st_size > 0:
        return
    import sqlite3

    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.seed_db) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _add_missing_columns() -> None:
    """Additive auto-migration: new nullable/defaulted model columns are added in place.
    Renames and drops still need a real migration (Alembic) once the schema settles."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            present = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                clause = f" DEFAULT {default!r}" if isinstance(default, (int, float, str)) and not isinstance(default, bool) else ""
                if isinstance(default, bool):  # Postgres booleans reject 0/1; SQLite accepts both forms
                    clause = f" DEFAULT {'true' if default else 'false'}" if not _is_sqlite else f" DEFAULT {int(default)}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}{clause}'))
            for index in table.indexes:  # create_all only builds indexes with brand-new tables
                index.create(conn, checkfirst=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
