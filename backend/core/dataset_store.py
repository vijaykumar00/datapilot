"""
dataset_store.py — SQLite-backed CRUD service for Dataset Registry management.
"""

import json
import logging
from datetime import datetime
from typing import Any, List, Optional
from core.db import get_connection

logger = logging.getLogger("datapilot.dataset_store")

def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("tags", "column_summary", "schema_warnings"):
        raw = d.get(field)
        if raw:
            try:
                d[field] = json.loads(raw)
            except Exception:
                d[field] = [] if field in ("tags", "schema_warnings") else {}
        else:
            d[field] = [] if field in ("tags", "schema_warnings") else {}
    d["archived"] = bool(d.get("archived", 0))
    return d

def update_dataset(
    dataset_id: str,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    archived: Optional[bool] = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    """Update dataset registry details."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        parts = ["updated_at = ?"]
        values = [now]
        
        if display_name is not None:
            parts.append("display_name = ?")
            values.append(display_name)
        if description is not None:
            parts.append("description = ?")
            values.append(description)
        if tags is not None:
            parts.append("tags = ?")
            values.append(json.dumps(tags))
        if archived is not None:
            parts.append("archived = ?")
            values.append(1 if archived else 0)
            
        values.append(dataset_id)
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            values.extend([user_id, workspace_id])
        sql = f"UPDATE dataset_registry SET {', '.join(parts)} WHERE dataset_id = ?{scope_sql};"
        cursor = conn.execute(sql, values)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating dataset registry '{dataset_id}': {e}")
        return False
    finally:
        conn.close()

def archive_dataset(dataset_id: str, user_id: str | None = None, workspace_id: str | None = None) -> bool:
    """Soft-archive a dataset registry record."""
    return update_dataset(dataset_id, archived=True, user_id=user_id, workspace_id=workspace_id)

def restore_dataset(dataset_id: str, user_id: str | None = None, workspace_id: str | None = None) -> bool:
    """Restore a soft-archived dataset registry record."""
    return update_dataset(dataset_id, archived=False, user_id=user_id, workspace_id=workspace_id)

def list_datasets(
    *,
    archived: Optional[bool] = False,
    session_id: Optional[str] = None,
    tag: Optional[str] = None,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
) -> List[dict]:
    """List datasets matching criteria."""
    conn = get_connection()
    try:
        clauses = ["user_id = ?", "workspace_id = ?"]
        params: List[Any] = [user_id, workspace_id]
        
        if archived is not None:
            clauses.append("archived = ?")
            params.append(1 if archived else 0)
        
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
            
        where = f"WHERE {' AND '.join(clauses)}"
        sql = f"""
            SELECT * FROM dataset_registry
            {where}
            ORDER BY created_at DESC;
        """
        cursor = conn.execute(sql, params)
        results = [_row_to_dict(row) for row in cursor.fetchall()]
        
        # In-memory filter for tags if specified (since tags are saved as JSON array text)
        if tag:
            results = [r for r in results if tag in r.get("tags", [])]
            
        return results
    except Exception as e:
        logger.error(f"Error listing dataset registry: {e}")
        return []
    finally:
        conn.close()

def get_dataset(dataset_id: str, user_id: str | None = None, workspace_id: str | None = None) -> Optional[dict]:
    """Retrieve details for a single registered dataset."""
    conn = get_connection()
    try:
        params = [dataset_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(f"SELECT * FROM dataset_registry WHERE dataset_id = ?{scope_sql};", tuple(params))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching dataset '{dataset_id}': {e}")
        return None
    finally:
        conn.close()

def touch_last_query(dataset_id: str) -> None:
    """Update last query timestamp of a dataset."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE dataset_registry SET last_query_date = ?, updated_at = ? WHERE dataset_id = ?;",
            (now, now, dataset_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error touching dataset timestamp: {e}")
    finally:
        conn.close()
