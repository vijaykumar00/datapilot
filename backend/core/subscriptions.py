"""Provider-neutral subscription foundation for DataPilot.

This module owns plan definitions, feature flags, quota checks, usage snapshots,
trial state, and workspace subscription state. Payment providers should plug
into these services later instead of becoming the billing source of truth.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models import (
    Feature,
    Plan,
    PlanFeature,
    PlanLimit,
    Quota,
    Trial,
    UsageRecord,
    UsageStats,
    Workspace,
    WorkspaceMember,
    WorkspaceSubscription,
    SubscriptionHistory,
)


UNLIMITED = -1

FEATURE_KEYS = [
    "can_export_pdf",
    "can_forecast",
    "can_generate_report",
    "can_use_multiple_datasets",
    "can_invite_members",
    "can_use_custom_api_key",
    "can_schedule_reports",
    "can_access_priority_support",
]

PLAN_BLUEPRINTS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "description": "Starter workspace for evaluating DataPilot.",
        "monthly_price_cents": 0,
        "annual_price_cents": 0,
        "display_order": 10,
        "limits": {
            "upload_count": 20,
            "dataset_count": 3,
            "report_count": 10,
            "query_count": 200,
            "ai_prompt_count": 200,
            "storage_bytes": 500 * 1024 * 1024,
            "export_count": 20,
            "workspace_count": 1,
            "member_count": 1,
            "chart_count": 50,
            "api_usage_count": 0,
            "max_file_size_bytes": 25 * 1024 * 1024,
        },
        "features": {
            "can_export_pdf": False,
            "can_forecast": False,
            "can_generate_report": True,
            "can_use_multiple_datasets": False,
            "can_invite_members": False,
            "can_use_custom_api_key": True,
            "can_schedule_reports": False,
            "can_access_priority_support": False,
        },
        "trial_days": 14,
        "is_public": True,
    },
    "pro": {
        "name": "Pro",
        "description": "Solo professional plan with higher limits and exports.",
        "monthly_price_cents": 1900,
        "annual_price_cents": 19000,
        "display_order": 20,
        "limits": {
            "upload_count": UNLIMITED,
            "dataset_count": 100,
            "report_count": UNLIMITED,
            "query_count": UNLIMITED,
            "ai_prompt_count": UNLIMITED,
            "storage_bytes": 10 * 1024 * 1024 * 1024,
            "export_count": UNLIMITED,
            "workspace_count": 3,
            "member_count": 1,
            "chart_count": 1000,
            "api_usage_count": 1000,
            "max_file_size_bytes": 100 * 1024 * 1024,
        },
        "features": {
            "can_export_pdf": True,
            "can_forecast": True,
            "can_generate_report": True,
            "can_use_multiple_datasets": True,
            "can_invite_members": False,
            "can_use_custom_api_key": True,
            "can_schedule_reports": False,
            "can_access_priority_support": False,
        },
        "trial_days": 14,
        "is_public": True,
    },
    "team": {
        "name": "Team",
        "description": "Collaborative workspace plan for small teams.",
        "monthly_price_cents": 4900,
        "annual_price_cents": 49000,
        "display_order": 30,
        "limits": {
            "upload_count": 2000,
            "dataset_count": 500,
            "report_count": 1000,
            "query_count": 25000,
            "ai_prompt_count": 25000,
            "storage_bytes": 50 * 1024 * 1024 * 1024,
            "export_count": 2000,
            "workspace_count": 10,
            "member_count": 10,
            "chart_count": 5000,
            "api_usage_count": 10000,
            "max_file_size_bytes": 500 * 1024 * 1024,
        },
        "features": {key: True for key in FEATURE_KEYS},
        "trial_days": 14,
        "is_public": True,
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "Placeholder for custom enterprise subscriptions.",
        "monthly_price_cents": 0,
        "annual_price_cents": 0,
        "display_order": 40,
        "limits": {
            "upload_count": UNLIMITED,
            "dataset_count": UNLIMITED,
            "report_count": UNLIMITED,
            "query_count": UNLIMITED,
            "ai_prompt_count": UNLIMITED,
            "storage_bytes": UNLIMITED,
            "export_count": UNLIMITED,
            "workspace_count": UNLIMITED,
            "member_count": UNLIMITED,
            "chart_count": UNLIMITED,
            "api_usage_count": UNLIMITED,
            "max_file_size_bytes": 1024 * 1024 * 1024,
        },
        "features": {key: True for key in FEATURE_KEYS},
        "trial_days": 14,
        "is_public": False,
    },
}

ACTION_TO_METRIC = {
    "upload": "upload_count",
    "query": "query_count",
    "report": "report_count",
    "export": "export_count",
    "dataset": "dataset_count",
    "chart": "chart_count",
    "api": "api_usage_count",
    "ai_prompt": "ai_prompt_count",
    "storage": "storage_bytes",
    "member": "member_count",
    "workspace": "workspace_count",
}


@dataclass(frozen=True)
class QuotaSnapshot:
    metric: str
    current: int
    limit: int
    remaining: int | None


def current_period(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.utcnow()).strftime("%Y-%m")


def period_end(now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.utcnow()
    if now.month == 12:
        return datetime.datetime(now.year + 1, 1, 1)
    return datetime.datetime(now.year, now.month + 1, 1)


def metric_for_action(action: str) -> str:
    return ACTION_TO_METRIC.get(action, f"{action}_count")


def fmt_limit(value: int | None) -> int | None:
    return None if value == UNLIMITED else value


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _dump_metadata(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True)


def _dt_from_timestamp(value: Any) -> datetime.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        return None


def seed_subscription_catalog(db: Session) -> None:
    for feature_key in FEATURE_KEYS:
        feature = db.query(Feature).filter(Feature.feature_key == feature_key).first()
        if not feature:
            db.add(Feature(
                feature_key=feature_key,
                name=feature_key.replace("can_", "").replace("_", " ").title(),
                description=f"Controls {feature_key.replace('_', ' ')}.",
            ))

    db.flush()

    for plan_id, blueprint in PLAN_BLUEPRINTS.items():
        limits = blueprint["limits"]
        plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
        if not plan:
            plan = Plan(plan_id=plan_id)
            db.add(plan)
        plan.name = blueprint["name"]
        plan.description = blueprint["description"]
        plan.monthly_price_cents = blueprint["monthly_price_cents"]
        plan.annual_price_cents = blueprint["annual_price_cents"]
        plan.query_limit = limits["query_count"]
        plan.upload_limit = limits["upload_count"]
        plan.file_size_limit_bytes = limits["max_file_size_bytes"]
        plan.storage_limit_bytes = limits["storage_bytes"]
        plan.report_limit = limits["report_count"]
        plan.export_limit = limits["export_count"]
        plan.member_limit = limits["member_count"]
        plan.dataset_limit = limits["dataset_count"]
        plan.chart_limit = limits["chart_count"]
        plan.api_usage_limit = limits["api_usage_count"]
        plan.workspace_limit = limits["workspace_count"]
        plan.ai_prompt_limit = limits["ai_prompt_count"]
        plan.reset_interval = "monthly"
        plan.trial_days = blueprint["trial_days"]
        plan.is_public = blueprint["is_public"]
        plan.is_active = True
        plan.display_order = blueprint["display_order"]

        db.flush()
        for metric, value in limits.items():
            limit = db.query(PlanLimit).filter(
                PlanLimit.plan_id == plan_id,
                PlanLimit.metric == metric,
            ).first()
            if not limit:
                limit = PlanLimit(id=str(uuid.uuid4()), plan_id=plan_id, metric=metric)
                db.add(limit)
            limit.limit_value = value
            limit.reset_interval = "monthly"

        for feature_key, enabled in blueprint["features"].items():
            plan_feature = db.query(PlanFeature).filter(
                PlanFeature.plan_id == plan_id,
                PlanFeature.feature_key == feature_key,
            ).first()
            if not plan_feature:
                plan_feature = PlanFeature(
                    id=str(uuid.uuid4()),
                    plan_id=plan_id,
                    feature_key=feature_key,
                )
                db.add(plan_feature)
            plan_feature.enabled = bool(enabled)

    # Historical alias from the pre-Phase-4.1 billing table.
    business = db.query(Plan).filter(Plan.plan_id == "business").first()
    if business:
        business.is_active = False

    db.commit()


def get_plan_limits(plan_id: str, db: Session) -> dict[str, int]:
    seed_if_missing(db)
    limits = {
        row.metric: int(row.limit_value)
        for row in db.query(PlanLimit).filter(PlanLimit.plan_id == plan_id).all()
    }
    if not limits and plan_id in PLAN_BLUEPRINTS:
        limits = dict(PLAN_BLUEPRINTS[plan_id]["limits"])
    if not limits:
        limits = dict(PLAN_BLUEPRINTS["free"]["limits"])
    return limits


def get_plan_features(plan_id: str, db: Session) -> dict[str, bool]:
    seed_if_missing(db)
    result = {key: False for key in FEATURE_KEYS}
    rows = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).all()
    for row in rows:
        result[row.feature_key] = bool(row.enabled)
    if not rows and plan_id in PLAN_BLUEPRINTS:
        result.update(PLAN_BLUEPRINTS[plan_id]["features"])
    return result


def seed_if_missing(db: Session) -> None:
    if not db.query(Plan).filter(Plan.plan_id == "free").first():
        seed_subscription_catalog(db)


def ensure_workspace_subscription(workspace_id: str, db: Session) -> WorkspaceSubscription:
    seed_if_missing(db)
    workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    sub = db.query(WorkspaceSubscription).filter(
        WorkspaceSubscription.workspace_id == workspace_id
    ).first()
    if sub:
        return sub

    now = datetime.datetime.utcnow()
    plan_id = workspace.plan_tier if workspace.plan_tier in PLAN_BLUEPRINTS else "free"
    plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
    trial_days = plan.trial_days if plan else 14
    sub = WorkspaceSubscription(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        plan_id=plan_id,
        status="trialing",
        trial_started_at=now,
        trial_ends_at=now + datetime.timedelta(days=trial_days),
        current_period_start=now,
        current_period_end=period_end(now),
        renews_at=period_end(now),
    )
    db.add(sub)
    db.add(Trial(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        plan_id=plan_id,
        status="active",
        started_at=sub.trial_started_at,
        ends_at=sub.trial_ends_at,
    ))
    db.flush()
    db.add(SubscriptionHistory(
        id=str(uuid.uuid4()),
        workspace_subscription_id=sub.id,
        workspace_id=workspace_id,
        to_plan_id=plan_id,
        to_status=sub.status,
        event_type="subscription_created",
        reason="Default Phase 4.1 workspace subscription created.",
    ))
    db.commit()
    db.refresh(sub)
    return sub


def refresh_subscription_status(sub: WorkspaceSubscription, db: Session) -> WorkspaceSubscription:
    now = datetime.datetime.utcnow()
    previous_status = sub.status
    if sub.status == "trialing" and sub.trial_ends_at and now > sub.trial_ends_at:
        sub.status = "expired"
    if sub.cancel_at_period_end and sub.current_period_end and now > sub.current_period_end:
        sub.status = "canceled"
        sub.canceled_at = sub.canceled_at or now
    if sub.status != previous_status:
        db.add(SubscriptionHistory(
            id=str(uuid.uuid4()),
            workspace_subscription_id=sub.id,
            workspace_id=sub.workspace_id,
            from_plan_id=sub.plan_id,
            to_plan_id=sub.plan_id,
            from_status=previous_status,
            to_status=sub.status,
            event_type="status_changed",
            reason="Subscription status refreshed from date rules.",
        ))
        db.commit()
    return sub


def sync_provider_subscription(
    workspace_id: str,
    plan_id: str,
    status: str,
    db: Session,
    *,
    provider: str,
    provider_subscription_id: str | None = None,
    provider_customer_id: str | None = None,
    payment_status: str | None = None,
    current_period_start: datetime.datetime | int | None = None,
    current_period_end: datetime.datetime | int | None = None,
    trial_start: datetime.datetime | int | None = None,
    trial_end: datetime.datetime | int | None = None,
    cancel_at_period_end: bool = False,
    canceled_at: datetime.datetime | int | None = None,
    reason: str = "provider_sync",
) -> WorkspaceSubscription:
    """Synchronize provider state into the provider-neutral subscription domain."""
    plan = db.query(Plan).filter(Plan.plan_id == plan_id, Plan.is_active == True).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    sub = ensure_workspace_subscription(workspace_id, db)
    old_plan = sub.plan_id
    old_status = sub.status
    now = datetime.datetime.utcnow()
    period_start = _dt_from_timestamp(current_period_start) or sub.current_period_start or now
    period_end_value = _dt_from_timestamp(current_period_end) or sub.current_period_end or period_end(now)
    trial_started = _dt_from_timestamp(trial_start) or sub.trial_started_at
    trial_ends = _dt_from_timestamp(trial_end) or sub.trial_ends_at
    canceled = _dt_from_timestamp(canceled_at)

    sub.previous_plan_id = old_plan if old_plan != plan_id else sub.previous_plan_id
    sub.plan_id = plan_id
    sub.status = status
    sub.current_period_start = period_start
    sub.current_period_end = period_end_value
    sub.renews_at = None if status in {"canceled", "incomplete_expired"} else period_end_value
    sub.trial_started_at = trial_started
    sub.trial_ends_at = trial_ends
    sub.cancel_at_period_end = bool(cancel_at_period_end)
    sub.canceled_at = canceled or (now if status == "canceled" else sub.canceled_at)
    sub.updated_at = now

    metadata = _load_metadata(sub.metadata_json)
    metadata.update({
        "payment_provider": provider,
        "payment_status": payment_status or metadata.get("payment_status") or status,
        "provider_subscription_id": provider_subscription_id or metadata.get("provider_subscription_id"),
        "provider_customer_id": provider_customer_id or metadata.get("provider_customer_id"),
        "last_provider_sync_at": now.isoformat(),
    })
    sub.metadata_json = _dump_metadata(metadata)

    workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if workspace:
        workspace.plan_tier = plan_id

    trial = db.query(Trial).filter(
        Trial.workspace_id == workspace_id,
        Trial.plan_id == plan_id,
    ).order_by(Trial.created_at.desc()).first()
    if trial_ends:
        if not trial:
            trial = Trial(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                plan_id=plan_id,
                started_at=trial_started or now,
                ends_at=trial_ends,
            )
            db.add(trial)
        trial.status = "active" if status == "trialing" else ("converted" if status == "active" else status)
        trial.converted_at = now if status == "active" and not trial.converted_at else trial.converted_at
        trial.updated_at = now

    db.add(SubscriptionHistory(
        id=str(uuid.uuid4()),
        workspace_subscription_id=sub.id,
        workspace_id=workspace_id,
        from_plan_id=old_plan,
        to_plan_id=plan_id,
        from_status=old_status,
        to_status=status,
        event_type=reason,
        reason=f"{provider} subscription synchronization.",
        metadata_json=_dump_metadata({
            "provider": provider,
            "provider_subscription_id": provider_subscription_id,
            "provider_customer_id": provider_customer_id,
            "payment_status": payment_status,
        }),
    ))
    db.commit()
    db.refresh(sub)
    return sub


def update_payment_status(
    workspace_id: str,
    payment_status: str,
    db: Session,
    *,
    provider: str = "stripe",
    reason: str = "payment_status_updated",
) -> WorkspaceSubscription:
    sub = ensure_workspace_subscription(workspace_id, db)
    old_status = _load_metadata(sub.metadata_json).get("payment_status")
    metadata = _load_metadata(sub.metadata_json)
    metadata["payment_provider"] = provider
    metadata["payment_status"] = payment_status
    metadata["last_payment_status_at"] = datetime.datetime.utcnow().isoformat()
    sub.metadata_json = _dump_metadata(metadata)
    db.add(SubscriptionHistory(
        id=str(uuid.uuid4()),
        workspace_subscription_id=sub.id,
        workspace_id=workspace_id,
        from_plan_id=sub.plan_id,
        to_plan_id=sub.plan_id,
        from_status=old_status,
        to_status=payment_status,
        event_type=reason,
        reason=f"{provider} payment status changed.",
        metadata_json=_dump_metadata({"provider": provider, "payment_status": payment_status}),
    ))
    db.commit()
    db.refresh(sub)
    return sub


def can_use_feature(workspace_id: str, feature_key: str, db: Session) -> bool:
    sub = refresh_subscription_status(ensure_workspace_subscription(workspace_id, db), db)
    if sub.status in {"expired", "canceled"}:
        return False
    return get_plan_features(sub.plan_id, db).get(feature_key, False)


def usage_totals(workspace_id: str, db: Session, period: str | None = None) -> dict[str, int]:
    period = period or current_period()
    stats = db.query(UsageStats).filter(
        UsageStats.workspace_id == workspace_id,
        UsageStats.period == period,
    ).first()
    totals = {
        "upload_count": stats.upload_count if stats else 0,
        "query_count": stats.query_count if stats else 0,
        "report_count": stats.report_count if stats else 0,
        "export_count": stats.export_count if stats else 0,
        "storage_bytes": stats.storage_bytes if stats else 0,
        "ai_tokens_used": stats.ai_tokens_used if stats else 0,
    }
    for row in db.query(UsageRecord).filter(
        UsageRecord.workspace_id == workspace_id,
        UsageRecord.period == period,
    ).all():
        if row.metric in {"upload_count", "query_count", "report_count", "export_count", "storage_bytes"}:
            continue
        totals[row.metric] = totals.get(row.metric, 0) + int(row.quantity)

    totals.setdefault("dataset_count", 0)
    totals.setdefault("chart_count", 0)
    totals.setdefault("api_usage_count", 0)
    totals.setdefault("ai_prompt_count", totals.get("query_count", 0))
    totals["member_count"] = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id
    ).count()
    return totals


def quota_snapshots(workspace_id: str, db: Session) -> dict[str, QuotaSnapshot]:
    sub = refresh_subscription_status(ensure_workspace_subscription(workspace_id, db), db)
    limits = get_plan_limits(sub.plan_id, db)
    current = usage_totals(workspace_id, db)
    snapshots = {}
    for metric, limit in limits.items():
        used = current.get(metric, 0)
        remaining = None if limit == UNLIMITED else max(limit - used, 0)
        snapshots[metric] = QuotaSnapshot(metric, used, limit, remaining)
    return snapshots


def enforce_quota(workspace_id: str, action: str, db: Session, increment_by: int = 1) -> None:
    metric = metric_for_action(action)
    snapshot = quota_snapshots(workspace_id, db).get(metric)
    if not snapshot or snapshot.limit == UNLIMITED:
        return
    if snapshot.current + increment_by > snapshot.limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "PLAN_LIMIT_EXCEEDED",
                "action": action,
                "metric": metric,
                "current": snapshot.current,
                "limit": snapshot.limit,
                "remaining": snapshot.remaining,
                "message": f"Your workspace has reached the plan limit for {action}.",
                "upgrade_prompt": True,
            },
        )


def record_usage(workspace_id: str, action: str, db: Session, increment_by: int = 1, source: str | None = None) -> None:
    metric = metric_for_action(action)
    db.add(UsageRecord(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        metric=metric,
        quantity=increment_by,
        period=current_period(),
        source=source,
    ))


def subscription_summary(workspace_id: str, db: Session) -> dict[str, Any]:
    sub = refresh_subscription_status(ensure_workspace_subscription(workspace_id, db), db)
    plan = db.query(Plan).filter(Plan.plan_id == sub.plan_id).first()
    limits = get_plan_limits(sub.plan_id, db)
    features = get_plan_features(sub.plan_id, db)
    quotas = quota_snapshots(workspace_id, db)
    metadata = _load_metadata(sub.metadata_json)

    return {
        "workspace_id": workspace_id,
        "subscription": {
            "id": sub.id,
            "status": sub.status,
            "plan_id": sub.plan_id,
            "previous_plan_id": sub.previous_plan_id,
            "pending_plan_id": sub.pending_plan_id,
            "renews_at": sub.renews_at.isoformat() if sub.renews_at else None,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "canceled_at": sub.canceled_at.isoformat() if sub.canceled_at else None,
        },
        "plan": plan_to_dict(plan, limits, features) if plan else None,
        "trial": {
            "active": sub.status == "trialing",
            "started_at": sub.trial_started_at.isoformat() if sub.trial_started_at else None,
            "ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
            "expired": sub.status == "expired",
            "grace_period_ends_at": sub.grace_period_ends_at.isoformat() if sub.grace_period_ends_at else None,
        },
        "billing": {
            "payment_provider": metadata.get("payment_provider"),
            "payment_status": metadata.get("payment_status", sub.status),
            "portal_available": bool(metadata.get("provider_customer_id")),
            "provider_subscription_id": metadata.get("provider_subscription_id"),
        },
        "usage": usage_totals(workspace_id, db),
        "limits": {metric: fmt_limit(value) for metric, value in limits.items()},
        "remaining_quota": {metric: snapshot.remaining for metric, snapshot in quotas.items()},
        "features": features,
    }


def plan_to_dict(plan: Plan, limits: dict[str, int] | None = None, features: dict[str, bool] | None = None) -> dict[str, Any]:
    limits = limits or {}
    features = features or {}
    return {
        "plan_id": plan.plan_id,
        "name": plan.name,
        "description": plan.description,
        "monthly_price_cents": plan.monthly_price_cents,
        "annual_price_cents": plan.annual_price_cents,
        "is_public": plan.is_public,
        "is_active": plan.is_active,
        "trial_days": plan.trial_days,
        "display_order": plan.display_order,
        "limits": {metric: fmt_limit(value) for metric, value in limits.items()},
        "features": features,
    }


def list_plans(db: Session, include_inactive: bool = False) -> list[dict[str, Any]]:
    seed_if_missing(db)
    query = db.query(Plan)
    if not include_inactive:
        query = query.filter(Plan.is_active == True)
    plans = query.order_by(Plan.display_order.asc(), Plan.plan_id.asc()).all()
    return [
        plan_to_dict(plan, get_plan_limits(plan.plan_id, db), get_plan_features(plan.plan_id, db))
        for plan in plans
    ]


def grant_subscription(workspace_id: str, plan_id: str, db: Session, reason: str = "manual_grant") -> WorkspaceSubscription:
    plan = db.query(Plan).filter(Plan.plan_id == plan_id, Plan.is_active == True).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    sub = ensure_workspace_subscription(workspace_id, db)
    old_plan = sub.plan_id
    old_status = sub.status
    now = datetime.datetime.utcnow()
    sub.previous_plan_id = old_plan if old_plan != plan_id else sub.previous_plan_id
    sub.plan_id = plan_id
    sub.status = "active"
    sub.current_period_start = now
    sub.current_period_end = period_end(now)
    sub.renews_at = period_end(now)
    sub.updated_at = now

    workspace = db.query(Workspace).filter(Workspace.workspace_id == workspace_id).first()
    if workspace:
        workspace.plan_tier = plan_id

    db.add(SubscriptionHistory(
        id=str(uuid.uuid4()),
        workspace_subscription_id=sub.id,
        workspace_id=workspace_id,
        from_plan_id=old_plan,
        to_plan_id=plan_id,
        from_status=old_status,
        to_status=sub.status,
        event_type="promotional_subscription_granted",
        reason=reason,
    ))
    db.commit()
    db.refresh(sub)
    return sub
