"""Subscription foundation API.

Phase 4.1 deliberately exposes no checkout, portal, webhook, invoice, or
payment-provider endpoints. These routes expose the subscription domain that a
future Stripe layer can call into.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import AuditLog, Plan, Workspace, WorkspaceSubscription
from core.rbac import get_workspace_member
from core.request_identity import CallerContext, get_caller
from core.subscriptions import (
    FEATURE_KEYS,
    can_use_feature,
    get_plan_features,
    get_plan_limits,
    grant_subscription,
    list_plans,
    plan_to_dict,
    quota_snapshots,
    seed_subscription_catalog,
    subscription_summary,
)

router = APIRouter(prefix="/billing", tags=["subscription"])


class PlanUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    monthly_price_cents: int = Field(..., ge=0)
    annual_price_cents: int = Field(..., ge=0)
    limits: dict[str, int] = Field(default_factory=dict)
    features: dict[str, bool] = Field(default_factory=dict)
    trial_days: int = Field(14, ge=0)
    is_public: bool = True
    is_active: bool = True
    display_order: int = 0


class GrantSubscriptionRequest(BaseModel):
    workspace_id: str
    plan_id: str
    reason: str = "manual_grant"


def _require_workspace_owner(caller: CallerContext, db: Session) -> None:
    if not caller.is_authenticated or not caller.user or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    get_workspace_member(caller.user, caller.workspace_id, db, required_role="Owner")


def _audit(db: Session, caller: CallerContext, event_type: str, description: str) -> None:
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=caller.user_id if caller.is_authenticated else None,
        workspace_id=caller.workspace_id,
        event_type=event_type,
        description=description,
    ))


@router.get("/current")
def current_subscription(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return subscription_summary(caller.workspace_id, db)


@router.get("/plans")
def available_plans(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    return {"plans": list_plans(db, include_inactive=include_inactive)}


@router.get("/usage")
def current_usage(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    summary = subscription_summary(caller.workspace_id, db)
    return {
        "workspace_id": caller.workspace_id,
        "period": datetime.datetime.utcnow().strftime("%Y-%m"),
        "usage": summary["usage"],
    }


@router.get("/quota")
def remaining_quota(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    snapshots = quota_snapshots(caller.workspace_id, db)
    return {
        "workspace_id": caller.workspace_id,
        "quota": {
            metric: {
                "current": snap.current,
                "limit": None if snap.limit == -1 else snap.limit,
                "remaining": snap.remaining,
            }
            for metric, snap in snapshots.items()
        },
    }


@router.get("/limits")
def workspace_limits(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    summary = subscription_summary(caller.workspace_id, db)
    return {
        "workspace_id": caller.workspace_id,
        "plan_id": summary["subscription"]["plan_id"],
        "limits": summary["limits"],
    }


@router.get("/features")
def feature_availability(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    summary = subscription_summary(caller.workspace_id, db)
    return {
        "workspace_id": caller.workspace_id,
        "features": summary["features"],
    }


@router.get("/features/{feature_key}")
def feature_check(
    feature_key: str,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if feature_key not in FEATURE_KEYS:
        raise HTTPException(status_code=404, detail="Feature not found")
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {
        "feature_key": feature_key,
        "enabled": can_use_feature(caller.workspace_id, feature_key, db),
    }


@router.get("/status")
def subscription_status(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    summary = subscription_summary(caller.workspace_id, db)
    return {
        "workspace_id": caller.workspace_id,
        "subscription": summary["subscription"],
        "trial": summary["trial"],
    }


@router.get("/trial")
def trial_information(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    if not caller.is_authenticated or not caller.workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return subscription_summary(caller.workspace_id, db)["trial"]


@router.post("/admin/plans/seed")
def seed_plans(
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    _require_workspace_owner(caller, db)
    seed_subscription_catalog(db)
    _audit(db, caller, "SUBSCRIPTION_PLANS_SEEDED", "Subscription catalog was reseeded.")
    db.commit()
    return {"success": True, "plans": list_plans(db, include_inactive=True)}


@router.post("/admin/plans/{plan_id}")
def upsert_plan(
    plan_id: str,
    payload: PlanUpsertRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    _require_workspace_owner(caller, db)
    plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
    if not plan:
        plan = Plan(plan_id=plan_id)
        db.add(plan)

    plan.name = payload.name
    plan.description = payload.description
    plan.monthly_price_cents = payload.monthly_price_cents
    plan.annual_price_cents = payload.annual_price_cents
    plan.query_limit = payload.limits.get("query_count", payload.limits.get("ai_prompt_count", 0))
    plan.upload_limit = payload.limits.get("upload_count", 0)
    plan.file_size_limit_bytes = payload.limits.get("max_file_size_bytes", 0)
    plan.storage_limit_bytes = payload.limits.get("storage_bytes", 0)
    plan.report_limit = payload.limits.get("report_count", 0)
    plan.export_limit = payload.limits.get("export_count", 0)
    plan.member_limit = payload.limits.get("member_count", 1)
    plan.dataset_limit = payload.limits.get("dataset_count", 0)
    plan.chart_limit = payload.limits.get("chart_count", 0)
    plan.api_usage_limit = payload.limits.get("api_usage_count", 0)
    plan.workspace_limit = payload.limits.get("workspace_count", 1)
    plan.ai_prompt_limit = payload.limits.get("ai_prompt_count", plan.query_limit)
    plan.trial_days = payload.trial_days
    plan.is_public = payload.is_public
    plan.is_active = payload.is_active
    plan.display_order = payload.display_order
    db.flush()

    from core.models import Feature, PlanFeature, PlanLimit

    for metric, value in payload.limits.items():
        row = db.query(PlanLimit).filter(PlanLimit.plan_id == plan_id, PlanLimit.metric == metric).first()
        if not row:
            row = PlanLimit(id=str(uuid.uuid4()), plan_id=plan_id, metric=metric)
            db.add(row)
        row.limit_value = value
        row.reset_interval = "monthly"

    for feature_key, enabled in payload.features.items():
        if not db.query(Feature).filter(Feature.feature_key == feature_key).first():
            db.add(Feature(feature_key=feature_key, name=feature_key.replace("_", " ").title()))
        row = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id, PlanFeature.feature_key == feature_key).first()
        if not row:
            row = PlanFeature(id=str(uuid.uuid4()), plan_id=plan_id, feature_key=feature_key)
            db.add(row)
        row.enabled = enabled

    _audit(db, caller, "SUBSCRIPTION_PLAN_UPSERTED", f"Plan '{plan_id}' was created or updated.")
    db.commit()
    return {"success": True, "plan": plan_to_dict(plan, get_plan_limits(plan_id, db), get_plan_features(plan_id, db))}


@router.patch("/admin/plans/{plan_id}/disable")
def disable_plan(
    plan_id: str,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    _require_workspace_owner(caller, db)
    plan = db.query(Plan).filter(Plan.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.is_active = False
    _audit(db, caller, "SUBSCRIPTION_PLAN_DISABLED", f"Plan '{plan_id}' was disabled.")
    db.commit()
    return {"success": True}


@router.post("/admin/subscriptions/grant")
def grant_promotional_subscription(
    payload: GrantSubscriptionRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
):
    _require_workspace_owner(caller, db)
    workspace = db.query(Workspace).filter(Workspace.workspace_id == payload.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    sub = grant_subscription(payload.workspace_id, payload.plan_id, db, reason=payload.reason)
    _audit(db, caller, "PROMOTIONAL_SUBSCRIPTION_GRANTED", f"Workspace '{payload.workspace_id}' granted plan '{payload.plan_id}'.")
    db.commit()
    return {"success": True, "subscription_id": sub.id}
