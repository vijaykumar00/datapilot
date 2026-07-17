"""
session_store.py — SQLite-backed session storage for chat and query persistence, scoped by user and workspace.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from core.db import get_connection

logger = logging.getLogger("datapilot.session")


def _get_or_create_session(conn: Any, session_id: str, name: str = None, user_id: str = "default_user", workspace_id: str = "default_workspace") -> None:
    """Helper to ensure a session exists in the DB with the right context."""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sessions WHERE session_id = ?;", (session_id,))
    if not cursor.fetchone():
        now = datetime.utcnow().isoformat()
        session_name = name or f"Analysis Session {now[:10]}"
        cursor.execute(
            """
            INSERT INTO sessions (session_id, name, pinned, user_id, workspace_id, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?);
            """,
            (session_id, session_name, user_id, workspace_id, now, now),
        )


def get_all_sessions(user_id: str = "default_user", workspace_id: str = "default_workspace") -> list[dict]:
    """Retrieve all sessions for a user/workspace sorted by pinned DESC, updated_at DESC."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, name, pinned, user_id, workspace_id, created_at, updated_at
            FROM sessions
            WHERE user_id = ? AND workspace_id = ?
            ORDER BY pinned DESC, updated_at DESC;
            """,
            (user_id, workspace_id),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        return []
    finally:
        conn.close()


def get_sessions_paginated(
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None
) -> dict:
    """Retrieve paginated sessions, optionally filtered by a search query on the name."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        base_where = "WHERE user_id = ? AND workspace_id = ?"
        params = [user_id, workspace_id]
        
        if search:
            base_where += " AND name LIKE ?"
            params.append(f"%{search}%")
            
        cursor.execute(
            f"SELECT COUNT(*) FROM sessions {base_where};",
            tuple(params)
        )
        total = cursor.fetchone()[0]
        
        select_query = f"""
            SELECT session_id, name, pinned, user_id, workspace_id, created_at, updated_at
            FROM sessions
            {base_where}
            ORDER BY pinned DESC, updated_at DESC
        """
        if limit is not None:
            select_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
        cursor.execute(select_query, tuple(params))
        sessions = [dict(row) for row in cursor.fetchall()]
        return {"sessions": sessions, "total": total}
    except Exception as e:
        logger.error(f"Error fetching paginated sessions: {e}")
        return {"sessions": [], "total": 0}
    finally:
        conn.close()



def create_session(session_id: str | None = None, name: str = None, user_id: str = "default_user", workspace_id: str = "default_workspace") -> dict:
    """Create a new session explicitly, generating a server-side UUID if none is provided."""
    if not session_id:
        session_id = uuid.uuid4().hex
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        session_name = name or f"Analysis Session {now[:10]}"
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (session_id, name, pinned, user_id, workspace_id, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?);
            """,
            (session_id, session_name, user_id, workspace_id, now, now),
        )
        conn.commit()
        return {
            "session_id": session_id,
            "name": session_name,
            "pinned": 0,
            "user_id": user_id,
            "workspace_id": workspace_id,
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


def append_message(session_id: str, role: str, content: str, extra: dict | None = None, user_id: str = "default_user", workspace_id: str = "default_workspace") -> None:
    """Append a message to the database, ensuring the session exists first."""
    if not session_id:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        _get_or_create_session(conn, session_id, user_id=user_id, workspace_id=workspace_id)

        now = datetime.utcnow().isoformat()
        extra = extra or {}

        # Extract fields from extra or defaults
        msg_id = str(extra.get("id") or uuid.uuid4().hex)
        msg_type = extra.get("type", "text")
        chart_data = json.dumps(extra.get("chart_data")) if extra.get("chart_data") is not None else None
        table_data = json.dumps(extra.get("table_data")) if extra.get("table_data") is not None else None
        metadata = json.dumps(extra.get("metadata", {}))

        cursor.execute(
            """
            INSERT OR REPLACE INTO messages (id, session_id, role, content, type, chart_data, table_data, metadata, user_id, workspace_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (msg_id, session_id, role, content, msg_type, chart_data, table_data, metadata, user_id, workspace_id, now),
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


# ── Query History endpoints helpers (Feature 2) ──────────────────────────────

def get_history_paginated(
    session_id: str | None = None,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
    limit: int = 50,
    offset: int = 0
) -> dict:
    """Get cross-session paginated history of user queries with corresponding assistant replies."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # We want to select user messages, and query the assistant message that follows (if any)
        # In SQLite, we can get the total count first
        query_count = "SELECT COUNT(*) FROM messages WHERE role = 'user' AND user_id = ? AND workspace_id = ?"
        params_count = [user_id, workspace_id]
        if session_id:
            query_count += " AND session_id = ?"
            params_count.append(session_id)
            
        cursor.execute(query_count, tuple(params_count))
        total = cursor.fetchone()[0]
        
        # Paginated retrieval
        query_select = """
            SELECT m.id, m.session_id, m.content, m.type, m.metadata, m.created_at, s.name as session_name
            FROM messages m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE m.role = 'user' AND m.user_id = ? AND m.workspace_id = ?
        """
        params_select = [user_id, workspace_id]
        if session_id:
            query_select += " AND m.session_id = ?"
            params_select.append(session_id)
            
        query_select += " ORDER BY m.created_at DESC LIMIT ? OFFSET ?"
        params_select.extend([limit, offset])
        
        cursor.execute(query_select, tuple(params_select))
        rows = cursor.fetchall()
        
        messages = []
        for r in rows:
            msg = dict(r)
            msg["metadata"] = json.loads(msg["metadata"]) if msg["metadata"] else {}
            
            # Fetch the subsequent assistant message for context/replay
            cursor.execute(
                """
                SELECT id, role, content, type, chart_data, table_data, metadata, created_at
                FROM messages
                WHERE session_id = ? AND created_at > ? AND role = 'bot'
                ORDER BY created_at ASC LIMIT 1;
                """,
                (msg["session_id"], msg["created_at"])
            )
            bot_row = cursor.fetchone()
            if bot_row:
                bot_msg = dict(bot_row)
                bot_msg["chart_data"] = json.loads(bot_msg["chart_data"]) if bot_msg["chart_data"] else None
                bot_msg["table_data"] = json.loads(bot_msg["table_data"]) if bot_msg["table_data"] else None
                bot_msg["metadata"] = json.loads(bot_msg["metadata"]) if bot_msg["metadata"] else {}
                msg["response"] = bot_msg
            else:
                msg["response"] = None
                
            messages.append(msg)
            
        return {"messages": messages, "total": total}
    except Exception as e:
        logger.error(f"Error reading paginated history: {e}")
        return {"messages": [], "total": 0}
    finally:
        conn.close()


def search_history(
    query_text: str,
    session_id: str | None = None,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
    limit: int = 20
) -> list[dict]:
    """Search cross-session user messages containing substring query_text."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query_select = """
            SELECT m.id, m.session_id, m.content, m.type, m.metadata, m.created_at, s.name as session_name
            FROM messages m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE m.role = 'user' AND m.content LIKE ? AND m.user_id = ? AND m.workspace_id = ?
        """
        params = [f"%{query_text}%", user_id, workspace_id]
        if session_id:
            query_select += " AND m.session_id = ?"
            params.append(session_id)
            
        query_select += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query_select, tuple(params))
        rows = cursor.fetchall()
        
        messages = []
        for r in rows:
            msg = dict(r)
            msg["metadata"] = json.loads(msg["metadata"]) if msg["metadata"] else {}
            messages.append(msg)
        return messages
    except Exception as e:
        logger.error(f"Error searching history: {e}")
        return []
    finally:
        conn.close()


def delete_message(message_id: str) -> bool:
    """Delete a user query and its corresponding assistant response."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Find the message first
        cursor.execute("SELECT session_id, created_at FROM messages WHERE id = ?;", (message_id,))
        row = cursor.fetchone()
        if not row:
            return False
            
        session_id, created_at = row["session_id"], row["created_at"]
        
        # Delete user message
        cursor.execute("DELETE FROM messages WHERE id = ?;", (message_id,))
        
        # Delete the immediate next bot response
        cursor.execute(
            """
            DELETE FROM messages 
            WHERE session_id = ? AND role = 'bot' AND created_at >= ?
            LIMIT 1;
            """,
            (session_id, created_at)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        return False
    finally:
        conn.close()


def pin_message(message_id: str) -> bool:
    """Toggle the 'pinned' status inside a message's metadata JSON."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT metadata FROM messages WHERE id = ?;", (message_id,))
        row = cursor.fetchone()
        if not row:
            return False
            
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        meta["pinned"] = not meta.get("pinned", False)
        
        cursor.execute(
            "UPDATE messages SET metadata = ? WHERE id = ?;",
            (json.dumps(meta), message_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error pinning message: {e}")
        return False
    finally:
        conn.close()
