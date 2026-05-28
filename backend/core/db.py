"""
db.py — SQLite database helper for persistent chat sessions and messages.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_DIR = Path(__file__).parent.parent / "uploads"
DB_PATH = DB_DIR / "datapilot.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection and enable foreign keys."""
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initialize the SQLite tables."""
    conn = get_connection()
    try:
        # Create sessions table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Create messages table
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
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )
        # Add index for session message retrieval speed
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);")
        conn.commit()
    finally:
        conn.close()


# Trigger initialization on import
init_db()
