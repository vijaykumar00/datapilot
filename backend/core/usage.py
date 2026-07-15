"""
usage.py — Usage tracking and plan limit enforcement.

Plan limits:
  guest:      5 uploads, 20 queries, 1 report, 3 exports, 10MB storage
  free:       20 uploads, 200 queries, 10 reports, 20 exports, 500MB storage
  pro:        unlimited uploads, unlimited queries, unlimited reports, unlimited exports, 10GB storage
  enterprise: unlimited everything
"""
import datetime
import logging
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from core.models import GuestSession, UsageStats, WorkspaceMember, Workspace

logger = logging.getLogger("datapilot.usage")

# ─────────────────────────────────────────────────────────────
# Plan Limits Configuration
# ─────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "guest": {
        "upload_count": 5,
        "query_count": 20,
        "report_count": 1,
        "export_count": 3,
        "storage_bytes": 10 * 1024 * 1024,       # 10 MB
        "max_file_size_bytes": 5 * 1024 * 1024,  # 5 MB per file
    },
    "free": {
        "upload_count": 20,
        "query_count": 200,
        "report_count": 10,
        "export_count": 20,
        "storage_bytes": 500 * 1024 * 1024,       # 500 MB
        "max_file_size_bytes": 25 * 1024 * 1024,  # 25 MB per file
    },
    "pro": {
        "upload_count": -1,       # -1 = unlimited
        "query_count": -1,
        "report_count": -1,
        "export_count": -1,
        "storage_bytes": 10 * 1024 * 1024 * 1024,         # 10 GB
        "max_file_size_bytes": 100 * 1024 * 1024,          # 100 MB per file
    },
    "enterprise": {
        "upload_count": -1,
        "query_count": -1,
        "report_count": -1,
        "export_count": -1,
        "storage_bytes": -1,
        "max_file_size_bytes": 500 * 1024 * 1024,          # 500 MB per file
    },
}


# ─────────────────────────────────────────────────────────────
# Guest Usage Tracking
# ─────────────────────────────────────────────────────────────

def check_guest_limit(guest: GuestSession, action: str) -> None:
    """Check if guest has exceeded their usage limit for a given action. Raises 429 if exceeded."""
    limits = PLAN_LIMITS["guest"]
    current = getattr(guest, f"{action}_count", 0)
    limit = limits.get(f"{action}_count", 0)
    if limit >= 0 and current >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "GUEST_LIMIT_EXCEEDED",
                "action": action,
                "current": current,
                "limit": limit,
                "message": f"Guest limit reached for {action}. Sign up for free to continue.",
                "upgrade_prompt": True,
            }
        )


def increment_guest_usage(guest: GuestSession, action: str, db: Session) -> None:
    """Increment a guest usage counter in the database."""
    try:
        current = getattr(guest, f"{action}_count", 0)
        setattr(guest, f"{action}_count", current + 1)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to increment guest usage for {action}: {e}")
        db.rollback()


# ─────────────────────────────────────────────────────────────
# Workspace Usage Tracking
# ─────────────────────────────────────────────────────────────

def _get_current_period() -> str:
    """Get the current YYYY-MM period string."""
    return datetime.datetime.utcnow().strftime("%Y-%m")


def _get_or_create_usage_stats(workspace_id: str, db: Session) -> UsageStats:
    """Get or create usage stats for the current period."""
    period = _get_current_period()
    stats = db.query(UsageStats).filter(
        UsageStats.workspace_id == workspace_id,
        UsageStats.period == period,
    ).first()
    if not stats:
        stats = UsageStats(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            period=period,
        )
        db.add(stats)
        db.flush()
    return stats


def get_workspace_plan(workspace_id: str, db: Session) -> str:
    """Get the plan tier for a workspace."""
    workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    return workspace.plan_tier if workspace else "free"


def get_plan_limits(plan_id: str, db: Session) -> dict:
    """
    Get plan limits from the database 'plans' table, falling back to static config.
    """
    try:
        from core.models import Plan as PlanModel
        db_plan = db.query(PlanModel).filter(PlanModel.plan_id == plan_id, PlanModel.is_active == True).first()
        if db_plan:
            return {
                "upload_count": db_plan.upload_limit,
                "query_count": db_plan.query_limit,
                "report_count": db_plan.report_limit,
                "export_count": db_plan.export_limit,
                "storage_bytes": db_plan.storage_limit_bytes,
                "max_file_size_bytes": db_plan.file_size_limit_bytes,
            }
    except Exception as e:
        logger.warning(f"Failed to query Plan limits from DB (using static fallback): {e}")
    return PLAN_LIMITS.get(plan_id, PLAN_LIMITS["free"])


def check_workspace_limit(workspace_id: str, action: str, db: Session) -> None:
    """Check if workspace has exceeded their plan limit for a given action. Raises 429 if exceeded."""
    plan = get_workspace_plan(workspace_id, db)
    limits = get_plan_limits(plan, db)
    limit = limits.get(f"{action}_count", 0)

    if limit == -1:  # Unlimited
        return

    stats = _get_or_create_usage_stats(workspace_id, db)
    current = getattr(stats, f"{action}_count", 0)

    if current >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "PLAN_LIMIT_EXCEEDED",
                "action": action,
                "current": current,
                "limit": limit,
                "plan": plan,
                "message": f"You have reached the {plan} plan limit for {action}. Upgrade for more.",
                "upgrade_prompt": plan != "pro",
            }
        )



def increment_workspace_usage(
    workspace_id: str,
    action: str,
    db: Session,
    increment_by: int = 1,
) -> None:
    """Increment a workspace usage counter."""
    try:
        stats = _get_or_create_usage_stats(workspace_id, db)
        current = getattr(stats, f"{action}_count", 0)
        setattr(stats, f"{action}_count", current + increment_by)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to increment workspace usage for {action}: {e}")
        db.rollback()


def get_usage_summary(workspace_id: str, db: Session) -> dict:
    """Get full usage summary for a workspace including limits."""
    plan = get_workspace_plan(workspace_id, db)
    limits = get_plan_limits(plan, db)
    period = _get_current_period()

    stats = db.query(UsageStats).filter(
        UsageStats.workspace_id == workspace_id,
        UsageStats.period == period,
    ).first()

    def fmt_limit(val):
        return None if val == -1 else val

    current = {
        "upload_count": stats.upload_count if stats else 0,
        "query_count": stats.query_count if stats else 0,
        "report_count": stats.report_count if stats else 0,
        "export_count": stats.export_count if stats else 0,
        "storage_bytes": stats.storage_bytes if stats else 0,
        "ai_tokens_used": stats.ai_tokens_used if stats else 0,
    }

    return {
        "plan": plan,
        "period": period,
        "current": current,
        "limits": {
            "upload_count": fmt_limit(limits.get("upload_count")),
            "query_count": fmt_limit(limits.get("query_count")),
            "report_count": fmt_limit(limits.get("report_count")),
            "export_count": fmt_limit(limits.get("export_count")),
            "storage_bytes": fmt_limit(limits.get("storage_bytes")),
            "max_file_size_bytes": limits.get("max_file_size_bytes"),
        },
    }

