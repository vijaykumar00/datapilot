"""
report_store.py — SQLite-backed CRUD service for Saved Reports with versioning.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional
from core.db import get_connection

logger = logging.getLogger("datapilot.report_store")

def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("chart_data", "table_data", "kpis", "metadata", "tags", "export_formats"):
        raw = d.get(field)
        if raw:
            try:
                d[field] = json.loads(raw)
            except Exception:
                d[field] = [] if field in ("tags", "export_formats", "kpis", "table_data") else {}
        else:
            d[field] = [] if field in ("tags", "export_formats", "kpis", "table_data") else {}
    d["starred"] = bool(d.get("starred", 0))
    d["scheduled"] = bool(d.get("scheduled", 0))
    return d

def save_report(
    *,
    session_id: Optional[str] = None,
    title: str,
    description: str = "",
    prompt: str = "",
    content: str,
    report_type: str = "insight",
    chart_data: Any = None,
    table_data: Optional[List[dict]] = None,
    kpis: Optional[List[dict]] = None,
    metadata: Optional[dict] = None,
    file_id: Optional[str] = None,
    filename: Optional[str] = None,
    tags: List[str] = [],
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
) -> dict:
    """Save a new report into the database."""
    report_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    try:
        # Ensure session exists if session_id is provided
        if session_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, name, pinned, user_id, workspace_id, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?, ?);
                """,
                (session_id, f"Session {now[:10]}", user_id, workspace_id, now, now),
            )

        conn.execute(
            """
            INSERT INTO reports (
                report_id, session_id, title, description, version, parent_report_id,
                prompt, content, report_type, chart_data, table_data, kpis, metadata,
                file_id, filename, tags, starred, scheduled, created_at, updated_at,
                user_id, workspace_id
            ) VALUES (?, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?);
            """,
            (
                report_id,
                session_id,
                title,
                description,
                prompt,
                content,
                report_type,
                json.dumps(chart_data) if chart_data is not None else None,
                json.dumps(table_data) if table_data is not None else None,
                json.dumps(kpis) if kpis is not None else None,
                json.dumps(metadata or {}),
                file_id,
                filename,
                json.dumps(tags),
                now,
                now,
                user_id,
                workspace_id
            )
        )
        conn.commit()
        logger.info(f"Saved report '{report_id}'")
        return get_report(report_id)
    except Exception as e:
        logger.error(f"Error saving report: {e}")
        raise
    finally:
        conn.close()

def create_version(
    report_id: str,
    *,
    content: str,
    chart_data: Any = None,
    kpis: Optional[List[dict]] = None,
    metadata: Optional[dict] = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Create a new version of an existing report, incrementing the version counter."""
    conn = get_connection()
    try:
        # Get base report
        base = get_report(report_id, user_id=user_id, workspace_id=workspace_id)
        if not base:
            raise ValueError(f"Report '{report_id}' not found")
            
        # Determine root parent
        parent_id = base["parent_report_id"] or base["report_id"]
        
        # Determine next version number
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(version) FROM reports WHERE report_id = ? OR parent_report_id = ?;",
            (parent_id, parent_id)
        )
        max_ver = cursor.fetchone()[0] or 1
        next_ver = max_ver + 1
        
        new_report_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        
        conn.execute(
            """
            INSERT INTO reports (
                report_id, session_id, title, description, version, parent_report_id,
                prompt, content, report_type, chart_data, table_data, kpis, metadata,
                file_id, filename, tags, starred, scheduled, created_at, updated_at,
                user_id, workspace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                new_report_id,
                base["session_id"],
                base["title"],
                base["description"],
                next_ver,
                parent_id,
                base["prompt"],
                content,
                base["report_type"],
                json.dumps(chart_data) if chart_data is not None else json.dumps(base["chart_data"]),
                json.dumps(base["table_data"]),
                json.dumps(kpis) if kpis is not None else json.dumps(base["kpis"]),
                json.dumps(metadata or base["metadata"]),
                base["file_id"],
                base["filename"],
                json.dumps(base["tags"]),
                1 if base["starred"] else 0,
                1 if base["scheduled"] else 0,
                now,
                now,
                base["user_id"],
                base["workspace_id"]
            )
        )
        conn.commit()
        logger.info(f"Created version {next_ver} for report '{parent_id}' as '{new_report_id}'")
        return get_report(new_report_id)
    except Exception as e:
        logger.error(f"Error creating version: {e}")
        raise
    finally:
        conn.close()

def update_report(
    report_id: str,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    starred: Optional[bool] = None,
    scheduled: Optional[bool] = None,
    schedule_cron: Optional[str] = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    """Update general fields of a report."""
    conn = get_connection()
    try:
        now = datetime.utcnow().isoformat()
        parts = ["updated_at = ?"]
        values = [now]
        
        if title is not None:
            parts.append("title = ?")
            values.append(title)
        if description is not None:
            parts.append("description = ?")
            values.append(description)
        if tags is not None:
            parts.append("tags = ?")
            values.append(json.dumps(tags))
        if starred is not None:
            parts.append("starred = ?")
            values.append(1 if starred else 0)
        if scheduled is not None:
            parts.append("scheduled = ?")
            values.append(1 if scheduled else 0)
        if schedule_cron is not None:
            parts.append("schedule_cron = ?")
            values.append(schedule_cron)
            
        values.append(report_id)
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            values.extend([user_id, workspace_id])
        sql = f"UPDATE reports SET {', '.join(parts)} WHERE report_id = ?{scope_sql};"
        cursor = conn.execute(sql, values)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating report '{report_id}': {e}")
        return False
    finally:
        conn.close()

def delete_report(report_id: str, user_id: str | None = None, workspace_id: str | None = None) -> bool:
    """Delete a report and all of its versions."""
    conn = get_connection()
    try:
        # Find if it is a parent or child
        base = get_report(report_id, user_id=user_id, workspace_id=workspace_id)
        if not base:
            return False
            
        root_id = base["parent_report_id"] or base["report_id"]
        
        # Delete root report and all versions with parent_report_id = root_id
        params = [root_id, root_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(
            f"DELETE FROM reports WHERE (report_id = ? OR parent_report_id = ?){scope_sql};",
            tuple(params)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting report '{report_id}': {e}")
        return False
    finally:
        conn.close()

def list_reports(
    *,
    session_id: Optional[str] = None,
    file_id: Optional[str] = None,
    starred_only: bool = False,
    report_type: Optional[str] = None,
    limit: int = 50,
    user_id: str = "default_user",
    workspace_id: str = "default_workspace",
) -> List[dict]:
    """Retrieve all reports for a user/workspace, grouping versions to only show the latest version of each report."""
    conn = get_connection()
    try:
        clauses = ["user_id = ?", "workspace_id = ?"]
        params = [user_id, workspace_id]
        
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if file_id:
            clauses.append("file_id = ?")
            params.append(file_id)
        if starred_only:
            clauses.append("starred = 1")
        if report_type:
            clauses.append("report_type = ?")
            params.append(report_type)
            
        where = f"WHERE {' AND '.join(clauses)}"
        
        # Select latest version of each report grouping by root parent
        # If parent_report_id is NULL, the root is report_id. Else root is parent_report_id.
        sql = f"""
            SELECT r1.*
            FROM reports r1
            INNER JOIN (
                SELECT COALESCE(parent_report_id, report_id) AS root_id, MAX(version) AS max_ver
                FROM reports
                {where}
                GROUP BY root_id
            ) r2 ON COALESCE(r1.parent_report_id, r1.report_id) = r2.root_id AND r1.version = r2.max_ver
            ORDER BY r1.starred DESC, r1.updated_at DESC
            LIMIT ?;
        """
        params.append(limit)
        cursor = conn.execute(sql, params)
        return [_row_to_dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        return []
    finally:
        conn.close()

def get_report(report_id: str, user_id: str | None = None, workspace_id: str | None = None) -> Optional[dict]:
    """Get a single report version details."""
    conn = get_connection()
    try:
        params = [report_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(f"SELECT * FROM reports WHERE report_id = ?{scope_sql};", tuple(params))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching report '{report_id}': {e}")
        return None
    finally:
        conn.close()

def get_report_versions(report_id: str, user_id: str | None = None, workspace_id: str | None = None) -> List[dict]:
    """Get all versions of a report sorted by version ASC."""
    base = get_report(report_id, user_id=user_id, workspace_id=workspace_id)
    if not base:
        return []
        
    root_id = base["parent_report_id"] or base["report_id"]
    conn = get_connection()
    try:
        params = [root_id, root_id]
        scope_sql = ""
        if user_id is not None and workspace_id is not None:
            scope_sql = " AND user_id = ? AND workspace_id = ?"
            params.extend([user_id, workspace_id])
        cursor = conn.execute(
            f"""
            SELECT * FROM reports
            WHERE (report_id = ? OR parent_report_id = ?){scope_sql}
            ORDER BY version ASC;
            """,
            tuple(params)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching versions for report '{root_id}': {e}")
        return []
    finally:
        conn.close()
