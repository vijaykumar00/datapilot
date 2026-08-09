"""
analysis_store.py — SQLite-backed CRUD module for saved analyses in DataPilot.

A "saved analysis" is a checkpoint: the original user query, the full AI
response, and any associated chart/table data — persisted for replay or restore.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from core.db import get_connection

logger = logging.getLogger("datapilot.analysis_store")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a Python dict, deserialising JSON fields."""
    d = dict(row)
    for field in ("chart_data", "table_data", "metadata", "tags"):
        raw = d.get(field)
        if raw:
            try:
                d[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[field] = None
        else:
            d[field] = None
    d["starred"] = bool(d.get("starred", 0))
    return d


# ── Write operations ───────────────────────────────────────────────────────────

def save_analysis(
    *,
    session_id: str,
    title: str,
    query: str,
    response: str,
    type: str = "insight",
    chart_data: Any = None,
    table_data: Any = None,
    metadata: dict | None = None,
    file_id: str | None = None,
    filename: str | None = None,
    tags: list[str] | None = None,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
) -> dict:
    """
    Persist a new saved analysis.  Returns the full dict with generated analysis_id.
    """
    analysis_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()

    conn = get_connection()
    try:
        # Ensure the parent session exists (lazy-create if needed)
        conn.execute(
            """
            INSERT OR IGNORE INTO sessions (session_id, name, pinned, user_id, workspace_id, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?);
            """,
            (session_id, f"Session {now[:10]}", user_id, workspace_id, now, now),
        )

        conn.execute(
            """
            INSERT INTO saved_analyses
                (analysis_id, session_id, title, query, response, type,
                 chart_data, table_data, metadata, file_id, filename,
                 tags, starred, user_id, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?);
            """,
            (
                analysis_id,
                session_id,
                title[:200],
                query,
                response,
                type,
                json.dumps(chart_data) if chart_data is not None else None,
                json.dumps(table_data) if table_data is not None else None,
                json.dumps(metadata or {}),
                file_id,
                filename,
                json.dumps(tags or []),
                user_id,
                workspace_id,
                now,
                now,
            ),
        )
        conn.commit()
        logger.info(f"Saved analysis '{analysis_id}' for session '{session_id}'")
        return {
            "analysis_id": analysis_id,
            "session_id": session_id,
            "title": title[:200],
            "query": query,
            "response": response,
            "type": type,
            "chart_data": chart_data,
            "table_data": table_data,
            "metadata": metadata or {},
            "file_id": file_id,
            "filename": filename,
            "tags": tags or [],
            "starred": False,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "created_at": now,
            "updated_at": now,
        }
    except Exception as e:
        logger.error(f"Error saving analysis: {e}")
        raise
    finally:
        conn.close()



def update_analysis(
    analysis_id: str,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    starred: bool | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    """
    Partially update a saved analysis (rename, re-tag, star/unstar).
    Returns True if a row was actually updated.
    """
    if title is None and tags is None and starred is None:
        return False

    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        parts = ["updated_at = ?"]
        values: list[Any] = [now]

        if title is not None:
            parts.append("title = ?")
            values.append(title[:200])
        if tags is not None:
            parts.append("tags = ?")
            values.append(json.dumps(tags))
        if starred is not None:
            parts.append("starred = ?")
            values.append(1 if starred else 0)

        values.append(analysis_id)
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            values.extend([user_id, workspace_id])
        sql = f"UPDATE saved_analyses SET {', '.join(parts)} WHERE analysis_id = ?{scope_sql};"
        cursor = conn.execute(sql, values)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating analysis '{analysis_id}': {e}")
        return False
    finally:
        conn.close()


def delete_analysis(analysis_id: str, user_id: str | None = None, workspace_id: str | None = None) -> bool:
    """Permanently delete a saved analysis. Returns True if found."""
    conn = get_connection()
    try:
        params = [analysis_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(
            f"DELETE FROM saved_analyses WHERE analysis_id = ?{scope_sql};",
            tuple(params),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting analysis '{analysis_id}': {e}")
        return False
    finally:
        conn.close()


# ── Read operations ────────────────────────────────────────────────────────────

def list_analyses(
    *,
    session_id: str | None = None,
    file_id: str | None = None,
    starred_only: bool = False,
    limit: int = 100,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
) -> list[dict]:
    """
    Return saved analyses filtered by session and/or file, newest first.
    Starred items always float to the top regardless of other ordering.
    """
    conn = get_connection()
    try:
        clauses = ["user_id = ?", "workspace_id = ?"]
        params: list[Any] = [user_id, workspace_id]

        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if file_id:
            clauses.append("file_id = ?")
            params.append(file_id)
        if starred_only:
            clauses.append("starred = 1")

        where = f"WHERE {' AND '.join(clauses)}"
        sql = f"""
            SELECT * FROM saved_analyses
            {where}
            ORDER BY starred DESC, created_at DESC
            LIMIT ?;
        """
        params.append(limit)
        cursor = conn.execute(sql, params)
        return [_row_to_dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error listing analyses: {e}")
        return []
    finally:
        conn.close()


def get_analysis(analysis_id: str, user_id: str | None = None, workspace_id: str | None = None) -> dict | None:
    """Fetch a single saved analysis by ID. Returns None if not found."""
    conn = get_connection()
    try:
        params = [analysis_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(
            f"SELECT * FROM saved_analyses WHERE analysis_id = ?{scope_sql};",
            tuple(params),
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching analysis '{analysis_id}': {e}")
        return None
    finally:
        conn.close()
