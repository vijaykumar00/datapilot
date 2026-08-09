"""
db.py — Database helper with SQLAlchemy connection pooling, supporting SQLite locally and PostgreSQL in production.
"""

import os
import logging
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

# SQLAlchemy engine config
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800
)

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
            
            # Simple conversion of SQLite INSERT OR IGNORE to standard SQL + conflict clause
            if "INSERT OR IGNORE INTO" in sql.upper():
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
        print(f"Failed to log API error to DB: {e}")
    finally:
        conn.close()

def init_db() -> None:
    """Initialize database schemas programmatically using Alembic migrations on startup."""
    try:
        # Run alembic migrations dynamically
        import sys
        from alembic.config import Config
        from alembic import command

        backend_dir = Path(__file__).parent.parent
        alembic_ini_path = backend_dir / "alembic.ini"
        
        # Configure and run migrations
        alembic_cfg = Config(str(alembic_ini_path))
        # Override the migration path to be absolute
        alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        
        # Check if legacy database (has tables but no alembic history)
        from sqlalchemy import inspect
        inspector = inspect(engine)
        has_sessions = "sessions" in inspector.get_table_names()
        has_alembic = "alembic_version" in inspector.get_table_names()
        
        if has_sessions and not has_alembic:
            command.stamp(alembic_cfg, "96e4e347edff")
            logger.info("Stamped legacy database to baseline revision 96e4e347edff.")
            print("Stamped legacy database to baseline revision 96e4e347edff.")

        # Run upgrade head
        command.upgrade(alembic_cfg, "head")

        logger.info("Alembic database migrations successfully applied.")
        print("Alembic migrations successfully applied.")

        # Seed plan records into database
        seed_plans()
    except Exception as e:
        logger.error(f"Failed to run database migrations: {e}")
        print(f"Failed to run database migrations: {e}")
        # Fallback: create tables using SQLAlchemy if migrations fail
        try:
            Base.metadata.create_all(bind=engine)
            print("Fallback table creation applied.")
            seed_plans()
        except Exception as fe:
            print(f"Fallback table creation also failed: {fe}")


def seed_plans() -> None:
    """Seed pricing plans in database plans table."""
    try:
        from core.subscriptions import seed_subscription_catalog
        db = SessionLocal()
        seed_subscription_catalog(db)
        logger.info("Subscription plan catalog successfully seeded.")
        print("Subscription plan catalog successfully seeded.")
    except Exception as e:
        logger.warning(f"Failed to seed plans: {e}")
        print(f"Failed to seed plans: {e}")
    finally:
        db.close()


# Initialize database on module import removed to prevent re-entrant Alembic conflicts
