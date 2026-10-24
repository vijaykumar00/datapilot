"""
data_purge.py — permanently delete everything stored for a workspace namespace.

Used when a guest session ends or expires, when a workspace is deleted and when
an account is deleted.  Datasets (registry rows, versions and stored objects),
chats, saved answers, reports, templates, staged edits, jobs and cached queries
are all removed, so "deleted" in the UI means deleted.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("datapilot.purge")

# Tables whose rows are scoped by ``workspace_id`` (guests use their session id).
_NAMESPACE_TABLES = (
    ("messages", "messages"), ("sessions", "sessions"), ("saved_analyses", "analyses"),
    ("reports", "reports"), ("templates", "templates"), ("staged_transforms", None),
    ("question_sql_cache", None),
)


def purge_namespace(workspace_id: str, *, keep_job_id: str | None = None) -> dict:
    from sqlalchemy import text

    from core.db import SessionLocal
    from core.file_manager import get_file_manager
    from core.storage import get_storage_provider

    counts = {"datasets": get_file_manager().delete_workspace_data(workspace_id)}
    try:
        get_storage_provider().delete_prefix(f"workspace/{workspace_id}/")
    except Exception as exc:  # objects of deleted datasets are already gone
        logger.warning("Storage prefix cleanup failed for %s: %s", workspace_id, type(exc).__name__)
    db = SessionLocal()
    try:
        for table, key in _NAMESPACE_TABLES:
            res = db.execute(text(f"DELETE FROM {table} WHERE workspace_id = :ws"), {"ws": workspace_id})
            if key:
                counts[key] = res.rowcount or 0
        # Job payloads can hold questions and SQL; the job doing this purge finishes normally.
        db.execute(text("DELETE FROM jobs WHERE workspace_id = :ws AND id != :keep"),
                   {"ws": workspace_id, "keep": keep_job_id or ""})
        db.commit()
    finally:
        db.close()
    return counts


def purge_user_chats(user_id: str) -> int:
    """Delete a user's own conversation history in every workspace (used on account deletion)."""
    from sqlalchemy import text

    from core.db import SessionLocal

    db = SessionLocal()
    try:
        ids = [r[0] for r in db.execute(text("SELECT session_id FROM sessions WHERE user_id = :u"), {"u": user_id})]
        for sid in ids:
            db.execute(text("DELETE FROM messages WHERE session_id = :s"), {"s": sid})
        db.execute(text("DELETE FROM saved_analyses WHERE user_id = :u"), {"u": user_id})
        res = db.execute(text("DELETE FROM sessions WHERE user_id = :u"), {"u": user_id})
        db.commit()
        return res.rowcount or 0
    finally:
        db.close()
