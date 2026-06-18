"""
db.py — SQLite database helper with SQLAlchemy connection pooling, dynamic migrations, and logging.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy.pool import QueuePool

DB_DIR = Path(__file__).parent.parent / "uploads"
DB_PATH = DB_DIR / "datapilot.db"

def _create_sqlite_conn() -> sqlite3.Connection:
    """Create a raw sqlite3 connection configured for DataPilot."""
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# SQLAlchemy Connection Pool for thread safety and performance
_db_pool = QueuePool(
    creator=_create_sqlite_conn,
    pool_size=10,
    max_overflow=20,
    timeout=30
)

def get_connection() -> sqlite3.Connection:
    """Get a database connection from the pool."""
    return _db_pool.connect()

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
        # Prevent logging crashes from crashing the app
        print(f"Failed to log API error to DB: {e}")
    finally:
        conn.close()

def init_db() -> None:
    """Initialize SQLite tables and run migrations to ensure auth/multi-tenancy columns exist."""
    conn = get_connection()
    try:
        # Create core tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                user_id TEXT,
                workspace_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                type TEXT NOT NULL,
                chart_data TEXT,
                table_data TEXT,
                metadata TEXT,
                user_id TEXT,
                workspace_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_analyses (
                analysis_id TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                title       TEXT NOT NULL,
                query       TEXT NOT NULL,
                response    TEXT NOT NULL,
                type        TEXT NOT NULL DEFAULT 'insight',
                chart_data  TEXT,
                table_data  TEXT,
                metadata    TEXT,
                file_id     TEXT,
                filename    TEXT,
                tags        TEXT,
                starred     INTEGER NOT NULL DEFAULT 0,
                user_id     TEXT,
                workspace_id TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )

        # Create new tables for reports, datasets, templates, and errors
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                session_id TEXT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                parent_report_id TEXT REFERENCES reports(report_id) ON DELETE SET NULL,
                prompt TEXT DEFAULT '',
                content TEXT NOT NULL,
                report_type TEXT NOT NULL DEFAULT 'insight',
                chart_data TEXT,
                table_data TEXT,
                kpis TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                file_id TEXT,
                filename TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                starred INTEGER NOT NULL DEFAULT 0,
                scheduled INTEGER NOT NULL DEFAULT 0,
                schedule_cron TEXT,
                export_formats TEXT NOT NULL DEFAULT '[]',
                user_id TEXT,
                workspace_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_registry (
                dataset_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                display_name TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                row_count INTEGER DEFAULT 0,
                column_count INTEGER DEFAULT 0,
                sheet_count INTEGER DEFAULT 1,
                file_size_bytes INTEGER DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                upload_date TEXT NOT NULL,
                last_query_date TEXT,
                session_id TEXT,
                column_summary TEXT NOT NULL DEFAULT '{}',
                schema_warnings TEXT NOT NULL DEFAULT '[]',
                user_id TEXT,
                workspace_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT NOT NULL,
                steps TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                user_id TEXT,
                workspace_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS error_logs (
                id TEXT PRIMARY KEY,
                request_id TEXT,
                endpoint TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                traceback TEXT,
                dataset_id TEXT,
                session_id TEXT,
                user_id TEXT,
                workspace_id TEXT,
                timestamp TEXT NOT NULL
            );
            """
        )

        # Run dynamic migrations to add user_id / workspace_id to any pre-existing tables
        tables = ["sessions", "messages", "saved_analyses"]
        for table in tables:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row["name"] for row in cursor.fetchall()]
            if "user_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT;")
                logger_msg = f"Migrated {table}: added user_id column"
                print(logger_msg)
            if "workspace_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT;")
                logger_msg = f"Migrated {table}: added workspace_id column"
                print(logger_msg)

        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_session ON saved_analyses(session_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_file ON saved_analyses(file_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_starred ON saved_analyses(starred);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_session ON reports(session_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_starred ON reports(starred);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dataset_archived ON dataset_registry(archived);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp);")

        conn.commit()
    finally:
        conn.close()

# Initialize the database on import
init_db()

