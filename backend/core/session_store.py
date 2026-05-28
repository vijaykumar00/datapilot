"""
session_store.py — SQLite-backed session storage for chat and query persistence.
"""

import json
import logging
from datetime import datetime
from typing import Any
from core.db import get_connection

logger = logging.getLogger("datapilot.session")


def _get_or_create_session(conn: Any, session_id: str, name: str = None) -> None:
    """Helper to ensure a session exists in the DB."""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sessions WHERE session_id = ?;", (session_id,))
    if not cursor.fetchone():
        now = datetime.utcnow().isoformat()
        session_name = name or f"Analysis Session {now[:10]}"
        cursor.execute(
            """
            INSERT INTO sessions (session_id, name, pinned, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?);
            """,
            (session_id, session_name, now, now),
        )


def get_all_sessions() -> list[dict]:
    """Retrieve all sessions sorted by pinned DESC, updated_at DESC."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, name, pinned, created_at, updated_at
            FROM sessions
            ORDER BY pinned DESC, updated_at DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        return []
    finally:
        conn.close()


def create_session(session_id: str, name: str = None) -> dict:
    """Create a new session explicitly."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        session_name = name or f"Analysis Session {now[:10]}"
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (session_id, name, pinned, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?);
            """,
            (session_id, session_name, now, now),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "name": session_name,
            "pinned": 0,
            "created_at": now,
            "updated_at": now,
        }
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return {}
    finally:
        conn.close()


def update_session(session_id: str, name: str = None, pinned: bool = None) -> bool:
    """Update session details (rename or pin/unpin)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()

        if name is not None and pinned is not None:
            cursor.execute(
                """
                UPDATE sessions
                SET name = ?, pinned = ?, updated_at = ?
                WHERE session_id = ?;
                """,
                (name, 1 if pinned else 0, now, session_id),
            )
        elif name is not None:
            cursor.execute(
                """
                UPDATE sessions
                SET name = ?, updated_at = ?
                WHERE session_id = ?;
                """,
                (name, now, session_id),
            )
        elif pinned is not None:
            cursor.execute(
                """
                UPDATE sessions
                SET pinned = ?, updated_at = ?
                WHERE session_id = ?;
                """,
                (1 if pinned else 0, now, session_id),
            )
        else:
            return False

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return False
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """Delete a session entirely (cascade deletes all messages)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE session_id = ?;", (session_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return False
    finally:
        conn.close()


def get_history(session_id: str) -> list[dict]:
    """Retrieve all messages for a session, deserializing JSON structures."""
    if not session_id:
        return []
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, role, content, type, chart_data, table_data, metadata, created_at as ts
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC;
            """,
            (session_id,),
        )
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            # Deserialize JSON fields
            msg["chart_data"] = json.loads(msg["chart_data"]) if msg["chart_data"] else None
            msg["table_data"] = json.loads(msg["table_data"]) if msg["table_data"] else None
            msg["metadata"] = json.loads(msg["metadata"]) if msg["metadata"] else {}
            messages.append(msg)
        return messages
    except Exception as e:
        logger.error(f"Error reading session history: {e}")
        return []
    finally:
        conn.close()


def append_message(session_id: str, role: str, content: str, extra: dict | None = None) -> None:
    """Append a message to the database, ensuring the session exists first."""
    if not session_id:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        _get_or_create_session(conn, session_id)

        now = datetime.utcnow().isoformat()
        extra = extra or {}

        # Extract fields from extra or defaults
        msg_id = str(extra.get("id") or int(datetime.utcnow().timestamp() * 1000))
        msg_type = extra.get("type", "text")
        chart_data = json.dumps(extra.get("chart_data")) if extra.get("chart_data") is not None else None
        table_data = json.dumps(extra.get("table_data")) if extra.get("table_data") is not None else None
        metadata = json.dumps(extra.get("metadata", {}))

        cursor.execute(
            """
            INSERT OR REPLACE INTO messages (id, session_id, role, content, type, chart_data, table_data, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (msg_id, session_id, role, content, msg_type, chart_data, table_data, metadata, now),
        )

        # Touch updated_at for the session
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?;",
            (now, session_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error appending message: {e}")
    finally:
        conn.close()


def clear_session(session_id: str) -> bool:
    """Clear all messages inside a session."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))
        # Touch updated_at
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?;",
            (now, session_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error clearing session: {e}")
        return False
    finally:
        conn.close()
