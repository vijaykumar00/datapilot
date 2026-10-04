"""
db.py — Database helper with SQLAlchemy connection pooling, supporting SQLite locally and PostgreSQL in production.
"""

import os
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from core.models import Base

logger = logging.getLogger("datapilot.db")

# Setup database paths and URLs
DB_DIR = Path(__file__).parent.parent / "uploads"
DB_PATH = DB_DIR / "datapilot.db"
DB_DIR.mkdir(exist_ok=True)

PRODUCTION_ENVS = {"production", "prod"}


def _is_production(app_env: str | None = None) -> bool:
    return (app_env or os.getenv("APP_ENV", "development")).strip().lower() in PRODUCTION_ENVS


def validate_database_url_for_runtime(database_url: str | None, app_env: str | None = None) -> None:
    """Prevent unsafe database defaults in production."""
    if not _is_production(app_env):
        return

    if not database_url or not database_url.strip():
        raise RuntimeError("DATABASE_URL is required in production and must use PostgreSQL.")

    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must use PostgreSQL in production.")


def _resolve_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL")
    database_url = raw_url.strip() if raw_url else ""
    if not database_url:
        database_url = f"sqlite:///{DB_PATH.as_posix()}"
    validate_database_url_for_runtime(database_url)
    return database_url


# Determine database URL: default to local sqlite outside production.
DATABASE_URL = _resolve_database_url()
is_postgres = DATABASE_URL.startswith("postgresql") or "postgres" in DATABASE_URL

def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# SQLAlchemy engine config
connect_args = {}
engine_kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 1800}
if DATABASE_URL.startswith("sqlite"):
    # Wait for the write lock instead of failing immediately under concurrency.
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    # Explicit, configurable pool sizing.  Every API process and worker process
    # gets its own pool, so size against Postgres max_connections:
    #   (api_processes + worker_processes) * (DB_POOL_SIZE + DB_MAX_OVERFLOW) < max_connections
    engine_kwargs.update(
        pool_size=_int_env("DB_POOL_SIZE", 10),
        max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
        pool_timeout=_int_env("DB_POOL_TIMEOUT_SECONDS", 10),
    )

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ─────────────────────────────────────────────────────────────
# DB Wrapper classes to adapt SQLite-style calls to PostgreSQL
# ─────────────────────────────────────────────────────────────

class RowWrapper:
    def __init__(self, raw_row, description):
        self.raw_row = raw_row
        self.keys_list = [desc[0] for desc in description] if description else []
        self.key_map = {name: i for i, name in enumerate(self.keys_list)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.raw_row[key]
        elif isinstance(key, str):
            idx = self.key_map.get(key)
            if idx is None:
                raise KeyError(key)
            return self.raw_row[idx]
        else:
            raise TypeError("Key must be string or integer")

    def keys(self):
        return self.keys_list

    def __iter__(self):
        return iter(self.raw_row)

    def __len__(self):
        return len(self.raw_row)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

class DBCursorWrapper:
    def __init__(self, raw_cursor, is_pg: bool):
        self.raw_cursor = raw_cursor
        self.is_pg = is_pg

    def execute(self, sql, parameters=None):
        if self.is_pg and sql:
            # Convert SQLite placeholders (?) to PostgreSQL (%s)
            sql = sql.replace("?", "%s")
            
            # SQLite "INSERT OR REPLACE" has no PostgreSQL equivalent; it must be written
            # as an explicit upsert by the caller.  Fail loudly instead of silently
            # producing invalid SQL (this previously broke chat history on Postgres).
            if "INSERT OR REPLACE" in sql.upper():
                raise ValueError("INSERT OR REPLACE is SQLite-only; use INSERT ... ON CONFLICT ... DO UPDATE")
            # Simple conversion of SQLite INSERT OR IGNORE to standard SQL + conflict clause
            if "INSERT OR IGNORE INTO" in sql.upper():
                # The conflict clause must precede the statement terminator.
                sql = sql.rstrip().rstrip(";").rstrip()
                sql_upper = sql.upper()
                if "SESSIONS" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (session_id) DO NOTHING"
                elif "MESSAGES" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (id) DO NOTHING"
                elif "SAVED_ANALYSES" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (analysis_id) DO NOTHING"
                elif "REPORTS" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (report_id) DO NOTHING"
                elif "DATASET_REGISTRY" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (dataset_id) DO NOTHING"
                elif "TEMPLATES" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (template_id) DO NOTHING"
                elif "USERS" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (user_id) DO NOTHING"
                elif "WORKSPACES" in sql_upper:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (workspace_id) DO NOTHING"
                else:
                    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")

        if parameters is not None:
            # PostgreSQL requires tuple or list
            if not isinstance(parameters, (tuple, list)):
                parameters = (parameters,)
            self.raw_cursor.execute(sql, parameters)
        else:
            self.raw_cursor.execute(sql)
        return self

    def fetchone(self):
        row = self.raw_cursor.fetchone()
        if row is None:
            return None
        return RowWrapper(row, self.raw_cursor.description)

    def fetchall(self):
        rows = self.raw_cursor.fetchall()
        desc = self.raw_cursor.description
        return [RowWrapper(r, desc) for r in rows]

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount

    def close(self):
        self.raw_cursor.close()

class DBConnectionWrapper:
    def __init__(self, raw_conn, is_pg: bool):
        self.raw_conn = raw_conn
        self.is_pg = is_pg

    def cursor(self):
        return DBCursorWrapper(self.raw_conn.cursor(), self.is_pg)

    def execute(self, sql, parameters=None):
        cur = self.cursor()
        cur.execute(sql, parameters)
        return cur

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()

# ─────────────────────────────────────────────────────────────
# Connection and Session Helpers
# ─────────────────────────────────────────────────────────────

def get_connection():
    """Exposes a wrapped database connection matching the legacy API."""
    raw_conn = engine.raw_connection()
    # If SQLite, ensure we enable foreign keys and row factory
    if not is_postgres:
        raw_conn.execute("PRAGMA foreign_keys = ON;")
    return DBConnectionWrapper(raw_conn, is_postgres)

def release_connection(db, *detach) -> None:
    """End the session's current transaction so its pooled connection goes back to the pool.

    Call this before any long wait or CPU-heavy work (job waits, exports, report
    generation, password hashing).  A Session only holds a pooled connection while
    a transaction is open; leaving one open across a wait shows up in Postgres as
    "idle in transaction" and exhausts the pool under load.

    ``detach`` objects are expunged first so later attribute reads never trigger a
    lazy reload (which would silently check a connection out again).  Pending
    changes are committed; a read-only transaction is simply rolled back.
    """
    if db is None:
        return
    for obj in detach:
        if obj is not None and obj in db:
            db.expunge(obj)
    if db.new or db.dirty or db.deleted:
        db.commit()
    else:
        db.rollback()


@contextmanager
def connection_released(db):
    """Run a block of session work and end its transaction in the SAME thread.

    On success pending changes are committed (see :func:`release_connection`); on
    error the transaction is rolled back — partial work is never committed.  Use it
    inside every ``run_in_threadpool`` call whose session is used again later from
    the event loop: an open transaction must never wait for another threadpool slot.
    """
    try:
        yield db
    except BaseException:
        try:
            db.rollback()
        except Exception:  # pragma: no cover - connection already broken
            logger.warning("Rollback after failed request step also failed", exc_info=True)
        raise
    else:
        release_connection(db)


def get_db():
    """FastAPI Dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def log_api_error(
    request_id: str | None,
    endpoint: str,
    error_type: str,
    message: str,
    traceback: str | None = None,
    dataset_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Log an API error to the error_logs table."""
    conn = get_connection()
    try:
        err_id = f"err_{os.urandom(4).hex()}_{int(datetime.utcnow().timestamp())}"
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO error_logs (
                id, request_id, endpoint, error_type, message,
                traceback, dataset_id, session_id, user_id, workspace_id, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                err_id,
                request_id,
                endpoint,
                error_type,
                message,
                traceback,
                dataset_id,
                session_id,
                user_id or "default_user",
                workspace_id or "default_workspace",
                now
            )
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to log API error to DB: %s", e)
    finally:
        conn.close()

def _drop_stale_alembic_tmp_tables(tables: list[str]) -> None:
    """Remove ``_alembic_tmp_<table>`` leftovers from an interrupted SQLite batch migration.

    Alembic's SQLite batch mode copies a table into ``_alembic_tmp_<name>``, drops the
    original and renames the copy.  If the process is killed in between, the temp
    table survives and every later upgrade fails with "table _alembic_tmp_... already
    exists", so the API never starts.  The temp table is only dropped when the
    original table still exists (i.e. the copy never replaced it); otherwise we stop
    with a clear message instead of guessing which copy holds the data.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    prefix = "_alembic_tmp_"
    for name in tables:
        if not name.startswith(prefix):
            continue
        original = name[len(prefix):]
        if original in tables:
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE "{name}"'))
            logger.warning("Dropped stale %s left by an interrupted migration (%s is intact).", name, original)
        else:
            raise RuntimeError(
                f"Found {name} but no {original} table: a previous migration was interrupted mid-copy. "
                f"Back up the database, then rename {name} to {original} and restart."
            )


def run_migrations() -> None:
    """Apply Alembic migrations to head.  Raises on failure (never silently diverges)."""
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import inspect

    backend_dir = Path(__file__).parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    _drop_stale_alembic_tmp_tables(tables)
    if "sessions" in tables and "alembic_version" not in tables:
        command.stamp(alembic_cfg, "96e4e347edff")
        logger.info("Stamped legacy database to baseline revision 96e4e347edff.")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic database migrations applied.")


def _migrations_on_startup() -> bool:
    raw = os.getenv("RUN_MIGRATIONS_ON_STARTUP")
    if raw is None:
        # Production runs migrations once as a deploy step (compose `migrate`
        # service / release job), never concurrently from every replica.
        return not _is_production()
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def init_db() -> None:
    """Prepare the database at process start.

    * Development: apply migrations automatically.
    * Production: migrations are a separate deploy step; startup only verifies
      that the schema is at the expected head and fails loudly if not.
    """
    if _migrations_on_startup():
        run_migrations()
    else:
        verify_schema_at_head()
    seed_plans()


def verify_schema_at_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text as _text

    backend_dir = Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as conn:
        try:
            current = conn.execute(_text("SELECT version_num FROM alembic_version")).scalar()
        except Exception as exc:
            raise RuntimeError("Database is not migrated. Run `alembic upgrade head` before starting.") from exc
    if current != head:
        raise RuntimeError(
            f"Database schema revision {current!r} does not match code head {head!r}. "
            "Run `alembic upgrade head` as a deploy step before starting the API/worker."
        )


def seed_plans() -> None:
    """Seed pricing plans in database plans table."""
    db = SessionLocal()
    try:
        from core.subscriptions import seed_subscription_catalog
        seed_subscription_catalog(db)
        logger.info("Subscription plan catalog successfully seeded.")
    except Exception as e:
        logger.warning(f"Failed to seed plans: {e}")
    finally:
        db.close()


# Initialize database on module import removed to prevent re-entrant Alembic conflicts
