"""
usage.py — Atomic, status-aware usage metering and plan enforcement.

* Limits come from the workspace's *effective* plan: a subscription that is not
  active/trialing/past_due (canceled, expired, incomplete, unpaid) is treated as
  the free plan, so cancelled or never-paid plans no longer keep paid limits.
* Quota consumption is a single conditional UPDATE (``count = count + n WHERE
  count + n <= limit``), so concurrent requests cannot exceed a limit and no
  increment is lost.  Work that fails after reserving quota calls ``release``.
* Per-file size, total storage and dataset-count limits are enforced from the
  durable dataset registry (the source of truth), and plan feature flags
  (forecasting, PDF export, multi-dataset joins, …) are enforced server-side.
* AI token consumption is metered per workspace and capped by the plan's
  ``ai_token_count`` limit when one is configured.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import DatasetRegistry, GuestSession, UsageStats, Workspace
from core.subscriptions import (
    PLAN_BLUEPRINTS,
    UNLIMITED,
    ensure_workspace_subscription,
    get_plan_features,
    get_plan_limits as get_subscription_plan_limits,
    refresh_subscription_status,
    subscription_summary,
)

logger = logging.getLogger("datapilot.usage")

ACTIVE_STATUSES = {"active", "trialing", "past_due"}
COUNTER_COLUMNS = {"upload": "upload_count", "query": "query_count", "report": "report_count", "export": "export_count"}

# Guest sessions have fixed limits (no subscription).
PLAN_LIMITS = {
    "guest": {
        "upload_count": 5,
        "query_count": 20,
        "report_count": 1,
        "export_count": 3,
        "dataset_count": 3,
        "storage_bytes": 10 * 1024 * 1024,
        "max_file_size_bytes": 5 * 1024 * 1024,
        "ai_token_count": 200_000,
    },
    "free": dict(PLAN_BLUEPRINTS["free"]["limits"]),
}


def _period() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m")


def _get_current_period() -> str:  # backwards compatible name
    return _period()


def _limit_error(code: str, action: str, current: int, limit: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": code,
            "action": action,
            "current": current,
            "limit": limit,
            "message": message,
            "upgrade_prompt": True,
        },
    )


# ── Effective plan ────────────────────────────────────────────────────────────

def effective_plan(workspace_id: str, db: Session) -> tuple[str, dict, dict, str]:
    """Return (plan_id, limits, features, status) honouring subscription status."""
    sub = refresh_subscription_status(ensure_workspace_subscription(workspace_id, db), db)
    plan_id = sub.plan_id if sub.status in ACTIVE_STATUSES else "free"
    return plan_id, get_subscription_plan_limits(plan_id, db), get_plan_features(plan_id, db), sub.status


def guest_features() -> dict:
    return dict(PLAN_BLUEPRINTS["free"]["features"])


def get_workspace_plan(workspace_id: str, db: Session) -> str:
    return effective_plan(workspace_id, db)[0]


def get_plan_limits(plan_id: str, db: Session) -> dict:
    try:
        limits = get_subscription_plan_limits(plan_id, db)
        if limits:
            return limits
    except Exception as e:
        logger.warning("Failed to query plan limits from DB (using static fallback): %s", e)
    return PLAN_LIMITS.get(plan_id, PLAN_LIMITS["free"])


# ── Guests ────────────────────────────────────────────────────────────────────

def check_guest_limit(guest: GuestSession, action: str) -> None:
    limit = PLAN_LIMITS["guest"].get(f"{action}_count", 0)
    current = getattr(guest, f"{action}_count", 0) or 0
    if limit >= 0 and current >= limit:
        raise _limit_error("GUEST_LIMIT_EXCEEDED", action, current, limit,
                           f"Guest limit reached for {action}. Sign up for free to continue.")


def consume_guest(guest: GuestSession, action: str, db: Session, amount: int = 1) -> None:
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    limit = PLAN_LIMITS["guest"].get(column, 0)
    res = db.execute(
        text(f"UPDATE guest_sessions SET {column} = COALESCE({column}, 0) + :n "
             f"WHERE guest_session_id = :gid AND COALESCE({column}, 0) + :n <= :limit"),
        {"n": amount, "gid": guest.guest_session_id, "limit": limit},
    )
    db.commit()
    if res.rowcount != 1:
        current = getattr(guest, column, 0) or 0
        raise _limit_error("GUEST_LIMIT_EXCEEDED", action, current, limit,
                           f"Guest limit reached for {action}. Sign up for free to continue.")
    if guest in db:
        db.expire(guest)
    else:
        # Detached identity snapshot (see get_caller): keep the in-memory counter
        # consistent without re-attaching it to the session.
        setattr(guest, column, (getattr(guest, column, 0) or 0) + amount)


def release_guest(guest_session_id: str, action: str, db: Session, amount: int = 1) -> None:
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    db.execute(
        text(f"UPDATE guest_sessions SET {column} = CASE WHEN COALESCE({column},0) >= :n "
             f"THEN {column} - :n ELSE 0 END WHERE guest_session_id = :gid"),
        {"n": amount, "gid": guest_session_id},
    )
    db.commit()


def increment_guest_usage(guest: GuestSession, action: str, db: Session) -> None:
    """Legacy non-enforcing increment (kept for callers that already checked)."""
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    db.execute(text(f"UPDATE guest_sessions SET {column} = COALESCE({column},0) + 1 WHERE guest_session_id = :gid"),
               {"gid": guest.guest_session_id})
    db.commit()


# ── Workspaces ────────────────────────────────────────────────────────────────

def _usage_row_id(workspace_id: str, db: Session) -> str:
    period = _period()
    row = db.query(UsageStats.id).filter(UsageStats.workspace_id == workspace_id, UsageStats.period == period).first()
    if row:
        return row[0]
    new_id = str(uuid.uuid4())
    try:
        db.add(UsageStats(id=new_id, workspace_id=workspace_id, period=period, upload_count=0, query_count=0,
                          report_count=0, export_count=0, storage_bytes=0, ai_tokens_used=0))
        db.commit()
        return new_id
    except IntegrityError:  # created concurrently by another request
        db.rollback()
        return db.query(UsageStats.id).filter(UsageStats.workspace_id == workspace_id, UsageStats.period == period).first()[0]


def _get_or_create_usage_stats(workspace_id: str, db: Session) -> UsageStats:
    row_id = _usage_row_id(workspace_id, db)
    return db.query(UsageStats).filter(UsageStats.id == row_id).first()


def check_workspace_limit(workspace_id: str, action: str, db: Session) -> None:
    """Non-consuming pre-check (used by UI-facing checks)."""
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    _, limits, _, _ = effective_plan(workspace_id, db)
    limit = int(limits.get(column, UNLIMITED))
    if limit == UNLIMITED:
        return
    stats = _get_or_create_usage_stats(workspace_id, db)
    current = int(getattr(stats, column) or 0)
    if current + 1 > limit:
        raise _limit_error("PLAN_LIMIT_EXCEEDED", action, current, limit,
                           f"Your workspace has reached the plan limit for {action}.")


def consume_workspace(workspace_id: str, action: str, db: Session, amount: int = 1) -> None:
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    _, limits, _, _ = effective_plan(workspace_id, db)
    limit = int(limits.get(column, UNLIMITED))
    row_id = _usage_row_id(workspace_id, db)
    if limit == UNLIMITED:
        db.execute(text(f"UPDATE usage_stats SET {column} = {column} + :n WHERE id = :id"), {"n": amount, "id": row_id})
        db.commit()
        return
    res = db.execute(
        text(f"UPDATE usage_stats SET {column} = {column} + :n WHERE id = :id AND {column} + :n <= :limit"),
        {"n": amount, "id": row_id, "limit": limit},
    )
    db.commit()
    if res.rowcount != 1:
        current = db.execute(text(f"SELECT {column} FROM usage_stats WHERE id = :id"), {"id": row_id}).scalar() or 0
        raise _limit_error("PLAN_LIMIT_EXCEEDED", action, int(current), limit,
                           f"Your workspace has reached the plan limit for {action}.")


def release_workspace(workspace_id: str, action: str, db: Session, amount: int = 1) -> None:
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    row_id = _usage_row_id(workspace_id, db)
    db.execute(
        text(f"UPDATE usage_stats SET {column} = CASE WHEN {column} >= :n THEN {column} - :n ELSE 0 END WHERE id = :id"),
        {"n": amount, "id": row_id},
    )
    db.commit()


def increment_workspace_usage(workspace_id: str, action: str, db: Session, increment_by: int = 1) -> None:
    """Legacy non-enforcing increment."""
    column = COUNTER_COLUMNS.get(action)
    if column is None:
        return
    try:
        row_id = _usage_row_id(workspace_id, db)
        db.execute(text(f"UPDATE usage_stats SET {column} = {column} + :n WHERE id = :id"), {"n": increment_by, "id": row_id})
        db.commit()
    except Exception as e:
        logger.error("Failed to increment workspace usage for %s: %s", action, e)
        db.rollback()


# ── Storage / dataset limits (computed from the durable registry) ─────────────

def workspace_storage(workspace_id: str, db: Session) -> tuple[int, int]:
    total, count = db.query(
        func.coalesce(func.sum(DatasetRegistry.storage_bytes), 0), func.count(DatasetRegistry.dataset_id)
    ).filter(DatasetRegistry.workspace_id == workspace_id).one()
    return int(total or 0), int(count or 0)


def upload_limits(limits: dict) -> dict:
    return {
        "max_file_size_bytes": int(limits.get("max_file_size_bytes", UNLIMITED)),
        "storage_bytes": int(limits.get("storage_bytes", UNLIMITED)),
        "dataset_count": int(limits.get("dataset_count", UNLIMITED)),
    }


def check_upload_allowed(namespace_id: str, size: int, limits: dict, db: Session) -> None:
    lim = upload_limits(limits)
    if lim["max_file_size_bytes"] != UNLIMITED and size > lim["max_file_size_bytes"]:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": "FILE_TOO_LARGE", "limit": lim["max_file_size_bytes"], "upgrade_prompt": True,
                    "message": f"This file exceeds your plan's {lim['max_file_size_bytes'] // (1024 * 1024)}MB per-file limit."},
        )
    used, count = workspace_storage(namespace_id, db)
    if lim["storage_bytes"] != UNLIMITED and used + size > lim["storage_bytes"]:
        raise _limit_error("STORAGE_LIMIT_EXCEEDED", "upload", used, lim["storage_bytes"],
                           "Your workspace storage is full. Delete datasets or upgrade your plan.")
    if lim["dataset_count"] != UNLIMITED and count + 1 > lim["dataset_count"]:
        raise _limit_error("DATASET_LIMIT_EXCEEDED", "upload", count, lim["dataset_count"],
                           "Your workspace has reached its dataset limit. Delete a dataset or upgrade your plan.")


def adjust_storage_bytes(workspace_id: str, delta: int) -> None:
    """Storage is derived from dataset_registry; nothing to adjust (kept for API compatibility)."""
    return None


# ── AI token metering ─────────────────────────────────────────────────────────

def record_ai_tokens(workspace_id: str, tokens: int, guest_session_id: str | None = None) -> None:
    from core.db import SessionLocal

    if not tokens:
        return
    db = SessionLocal()
    try:
        if guest_session_id:
            # Guests: metered in the guest namespace usage row (workspace FK not required).
            return
        row_id = _usage_row_id(workspace_id, db)
        db.execute(text("UPDATE usage_stats SET ai_tokens_used = ai_tokens_used + :n WHERE id = :id"),
                   {"n": int(tokens), "id": row_id})
        db.commit()
    except Exception as exc:
        logger.warning("Failed to record AI token usage for %s: %s", workspace_id, exc)
        db.rollback()
    finally:
        db.close()


def check_ai_budget(workspace_id: str, db: Session) -> None:
    _, limits, _, _ = effective_plan(workspace_id, db)
    limit = int(limits.get("ai_token_count", UNLIMITED))
    if limit == UNLIMITED:
        return
    stats = _get_or_create_usage_stats(workspace_id, db)
    used = int(stats.ai_tokens_used or 0)
    if used >= limit:
        raise _limit_error("AI_BUDGET_EXCEEDED", "ai", used, limit,
                           "Your workspace has used its monthly AI allowance. Upgrade or wait for the next period.")


def get_usage_summary(workspace_id: str, db: Session) -> dict:
    summary = subscription_summary(workspace_id, db)
    return {
        "plan": summary["subscription"]["plan_id"],
        "period": _period(),
        "current": summary["usage"],
        "limits": summary["limits"],
        "remaining_quota": summary["remaining_quota"],
        "features": summary["features"],
        "subscription": summary["subscription"],
        "trial": summary["trial"],
    }
