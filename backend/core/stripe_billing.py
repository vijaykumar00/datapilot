"""Stripe adapter for the provider-neutral subscription domain."""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models import BillingCustomer, Plan, Subscription, SubscriptionEvent, WebhookEvent, Workspace
from core.subscriptions import (
    ensure_workspace_subscription,
    get_plan_limits,
    sync_provider_subscription,
    update_payment_status,
)

logger = logging.getLogger("datapilot.stripe")

SUPPORTED_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.finalized",
}


@dataclass(frozen=True)
class StripeSettings:
    secret_key: str
    publishable_key: str
    webhook_secret: str
    environment: str
    frontend_url: str

    @property
    def configured(self) -> bool:
        return bool(self.secret_key and self.publishable_key)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.secret_key and self.webhook_secret)


def get_stripe_settings() -> StripeSettings:
    return StripeSettings(
        secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
        publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
        environment=os.getenv("STRIPE_ENVIRONMENT", "test").lower(),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
    )


def configure_stripe() -> StripeSettings:
    settings = get_stripe_settings()
    if settings.secret_key:
        stripe.api_key = settings.secret_key
    return settings


def validate_stripe_startup() -> None:
    settings = configure_stripe()
    app_env = os.getenv("APP_ENV", "development").lower()
    production = app_env in {"production", "prod"}
    errors: list[str] = []
    if production:
        if not settings.secret_key:
            errors.append("STRIPE_SECRET_KEY is required in production.")
        if not settings.publishable_key:
            errors.append("STRIPE_PUBLISHABLE_KEY is required in production.")
        if not settings.webhook_secret:
            errors.append("STRIPE_WEBHOOK_SECRET is required in production.")
        if settings.environment not in {"test", "live"}:
            errors.append("STRIPE_ENVIRONMENT must be 'test' or 'live'.")
        if settings.environment == "live" and settings.secret_key.startswith("sk_test_"):
            errors.append("STRIPE_ENVIRONMENT=live cannot use a test secret key.")
    if errors:
        raise RuntimeError("Stripe configuration invalid: " + " ".join(errors))


def require_stripe() -> StripeSettings:
    settings = configure_stripe()
    if not settings.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "STRIPE_NOT_CONFIGURED",
                "message": "Stripe secret and publishable keys are required for billing operations.",
            },
        )
    return settings


def price_env_key(plan_id: str, interval: str) -> str:
    clean_plan = plan_id.upper().replace("-", "_")
    clean_interval = interval.upper()
    return f"STRIPE_PRICE_{clean_plan}_{clean_interval}"


def product_env_key(plan_id: str) -> str:
    clean_plan = plan_id.upper().replace("-", "_")
    return f"STRIPE_PRODUCT_{clean_plan}"


def stripe_price_for_plan(plan_id: str, interval: str = "monthly") -> str:
    interval = "annual" if interval in {"annual", "yearly", "year"} else "monthly"
    price_id = os.getenv(price_env_key(plan_id, interval), "")
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "STRIPE_PRICE_MAPPING_MISSING",
                "plan_id": plan_id,
                "interval": interval,
                "env_var": price_env_key(plan_id, interval),
                "message": "Stripe price mapping is missing for this plan.",
            },
        )
    return price_id


def plan_for_stripe_price(price_id: str) -> str | None:
    for key, value in os.environ.items():
        if key.startswith("STRIPE_PRICE_") and value == price_id:
            parts = key.removeprefix("STRIPE_PRICE_").split("_")
            if len(parts) >= 2:
                return "_".join(parts[:-1]).lower()
    return None


def plan_mapping_report(db: Session) -> list[dict[str, Any]]:
    plans = db.query(Plan).filter(Plan.is_active == True).order_by(Plan.display_order.asc()).all()
    report = []
    for plan in plans:
        report.append({
            "plan_id": plan.plan_id,
            "stripe_product_env": product_env_key(plan.plan_id),
            "stripe_product_id_configured": bool(os.getenv(product_env_key(plan.plan_id), "")),
            "monthly_price_env": price_env_key(plan.plan_id, "monthly"),
            "monthly_price_configured": bool(os.getenv(price_env_key(plan.plan_id, "monthly"), "")),
            "annual_price_env": price_env_key(plan.plan_id, "annual"),
            "annual_price_configured": bool(os.getenv(price_env_key(plan.plan_id, "annual"), "")),
        })
    return report


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _metadata(obj: Any) -> dict[str, Any]:
    raw = _get(obj, "metadata", {}) or {}
    if isinstance(raw, dict):
        return raw
    try:
        return dict(raw)
    except Exception:
        return {}


def _timestamp(value: Any) -> datetime.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        return None


def _workspace_customer(workspace_id: str, db: Session) -> BillingCustomer | None:
    return db.query(BillingCustomer).filter(BillingCustomer.workspace_id == workspace_id).first()


def ensure_stripe_customer(caller: Any, workspace_id: str, db: Session) -> BillingCustomer:
    settings = require_stripe()
    record = _workspace_customer(workspace_id, db)
    if record:
        return record

    customer = stripe.Customer.create(
        email=getattr(caller.user, "email", None),
        metadata={"workspace_id": workspace_id},
    )
    customer_id = _get(customer, "id")
    if not customer_id:
        raise HTTPException(status_code=502, detail="Stripe customer creation returned no id.")
    record = BillingCustomer(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        stripe_customer_id=customer_id,
    )
    db.add(record)
    db.commit()
    return record


def active_provider_subscription(workspace_id: str, db: Session) -> Subscription | None:
    return db.query(Subscription).filter(
        Subscription.workspace_id == workspace_id,
        Subscription.status.in_(["active", "trialing", "past_due", "incomplete"]),
    ).first()


def create_checkout_session(caller: Any, workspace_id: str, payload: Any, db: Session) -> dict[str, Any]:
    settings = require_stripe()
    plan_id = payload.plan_id
    interval = payload.interval
    plan = db.query(Plan).filter(Plan.plan_id == plan_id, Plan.is_active == True).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.monthly_price_cents == 0 and plan.annual_price_cents == 0:
        raise HTTPException(status_code=400, detail="Free or enterprise-placeholder plans do not require checkout.")

    existing = active_provider_subscription(workspace_id, db)
    if existing and existing.plan_id == plan_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DUPLICATE_SUBSCRIPTION",
                "message": "Workspace already has this Stripe subscription plan.",
                "portal_recommended": True,
            },
        )
    if existing and existing.plan_id != plan_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "SUBSCRIPTION_CHANGE_REQUIRES_PORTAL",
                "message": "Use the customer portal to confirm subscription upgrades or downgrades without creating duplicates.",
                "portal_recommended": True,
            },
        )

    price_id = stripe_price_for_plan(plan_id, interval)
    customer = ensure_stripe_customer(caller, workspace_id, db)
    internal_sub = ensure_workspace_subscription(workspace_id, db)
    success_url = payload.success_url or f"{settings.frontend_url}/app/settings/billing?checkout=success"
    cancel_url = payload.cancel_url or f"{settings.frontend_url}/app/settings/billing?checkout=cancelled"

    subscription_data: dict[str, Any] = {
        "metadata": {
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "internal_subscription_id": internal_sub.id,
        },
    }
    if internal_sub.status == "trialing" and internal_sub.trial_ends_at:
        remaining = internal_sub.trial_ends_at - datetime.datetime.utcnow()
        if remaining.days >= 1:
            subscription_data["trial_end"] = int(internal_sub.trial_ends_at.timestamp())

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer.stripe_customer_id,
        client_reference_id=workspace_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "workspace_id": workspace_id,
            "plan_id": plan_id,
            "interval": interval,
            "internal_subscription_id": internal_sub.id,
        },
        subscription_data=subscription_data,
        payment_method_collection="if_required",
    )
    return {
        "checkout_url": _get(session, "url"),
        "checkout_session_id": _get(session, "id"),
        "mode": "subscription",
        "plan_id": plan_id,
        "interval": interval,
    }


def create_portal_session(caller: Any, workspace_id: str, payload: Any, db: Session) -> dict[str, Any]:
    settings = require_stripe()
    customer = _workspace_customer(workspace_id, db)
    if not customer:
        raise HTTPException(status_code=404, detail="No Stripe customer exists for this workspace.")
    return_url = payload.return_url or f"{settings.frontend_url}/app/settings/billing"
    session = stripe.billing_portal.Session.create(
        customer=customer.stripe_customer_id,
        return_url=return_url,
    )
    return {
        "portal_url": _get(session, "url"),
        "portal_session_id": _get(session, "id"),
        "available_actions": [
            "update_payment_method",
            "cancel_subscription",
            "resume_subscription",
            "view_invoices",
            "upgrade",
            "downgrade",
        ],
    }


def _upsert_shadow_subscription(
    workspace_id: str,
    stripe_subscription_id: str,
    plan_id: str,
    stripe_status: str,
    db: Session,
    *,
    current_period_start: datetime.datetime | None,
    current_period_end: datetime.datetime | None,
    cancel_at_period_end: bool,
) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
    if not sub:
        sub = Subscription(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            stripe_subscription_id=stripe_subscription_id,
            status=stripe_status,
            plan_id=plan_id,
            current_period_start=current_period_start or datetime.datetime.utcnow(),
            current_period_end=current_period_end or datetime.datetime.utcnow(),
            cancel_at_period_end=cancel_at_period_end,
        )
        db.add(sub)
    else:
        sub.workspace_id = workspace_id
        sub.status = stripe_status
        sub.plan_id = plan_id
        sub.current_period_start = current_period_start or sub.current_period_start
        sub.current_period_end = current_period_end or sub.current_period_end
        sub.cancel_at_period_end = cancel_at_period_end
        sub.updated_at = datetime.datetime.utcnow()
    db.flush()
    return sub


def _workspace_from_customer(customer_id: str | None, db: Session) -> str | None:
    if not customer_id:
        return None
    record = db.query(BillingCustomer).filter(BillingCustomer.stripe_customer_id == customer_id).first()
    return record.workspace_id if record else None


def _workspace_from_subscription(stripe_subscription_id: str | None, db: Session) -> str | None:
    if not stripe_subscription_id:
        return None
    sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == stripe_subscription_id).first()
    return sub.workspace_id if sub else None


def _plan_from_subscription_object(subscription: Any) -> str | None:
    meta_plan = _metadata(subscription).get("plan_id")
    if meta_plan:
        return meta_plan
    items = _get(subscription, "items")
    data = _get(items, "data", []) if items else []
    if data:
        price = _get(data[0], "price")
        price_id = _get(price, "id")
        if price_id:
            return plan_for_stripe_price(price_id)
    return None


def process_subscription_object(subscription: Any, db: Session, reason: str) -> dict[str, Any]:
    stripe_subscription_id = _get(subscription, "id")
    customer_id = _get(subscription, "customer")
    metadata = _metadata(subscription)
    workspace_id = metadata.get("workspace_id") or _workspace_from_subscription(stripe_subscription_id, db) or _workspace_from_customer(customer_id, db)
    plan_id = _plan_from_subscription_object(subscription)
    if not workspace_id or not plan_id or not stripe_subscription_id:
        logger.warning("Stripe subscription event skipped: workspace/plan/subscription missing")
        return {"status": "skipped", "reason": "missing_mapping"}

    current_start = _timestamp(_get(subscription, "current_period_start"))
    current_end = _timestamp(_get(subscription, "current_period_end"))
    stripe_status = _get(subscription, "status", "active")
    cancel_at_period_end = bool(_get(subscription, "cancel_at_period_end", False))
    _upsert_shadow_subscription(
        workspace_id,
        stripe_subscription_id,
        plan_id,
        stripe_status,
        db,
        current_period_start=current_start,
        current_period_end=current_end,
        cancel_at_period_end=cancel_at_period_end,
    )
    sync_provider_subscription(
        workspace_id,
        plan_id,
        stripe_status,
        db,
        provider="stripe",
        provider_subscription_id=stripe_subscription_id,
        provider_customer_id=customer_id,
        payment_status=stripe_status,
        current_period_start=current_start,
        current_period_end=current_end,
        trial_start=_get(subscription, "trial_start"),
        trial_end=_get(subscription, "trial_end"),
        cancel_at_period_end=cancel_at_period_end,
        canceled_at=_get(subscription, "canceled_at"),
        reason=reason,
    )
    return {"status": "processed", "workspace_id": workspace_id, "plan_id": plan_id}


def process_checkout_completed(session: Any, db: Session) -> dict[str, Any]:
    metadata = _metadata(session)
    workspace_id = metadata.get("workspace_id") or _get(session, "client_reference_id")
    plan_id = metadata.get("plan_id")
    stripe_subscription_id = _get(session, "subscription")
    customer_id = _get(session, "customer")
    if customer_id and workspace_id and not _workspace_customer(workspace_id, db):
        db.add(BillingCustomer(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            stripe_customer_id=customer_id,
        ))
        db.flush()
    if not workspace_id or not plan_id or not stripe_subscription_id:
        return {"status": "skipped", "reason": "missing_checkout_mapping"}
    subscription = stripe.Subscription.retrieve(stripe_subscription_id)
    result = process_subscription_object(subscription, db, "checkout.session.completed")
    if result.get("status") == "skipped":
        sync_provider_subscription(
            workspace_id,
            plan_id,
            "active",
            db,
            provider="stripe",
            provider_subscription_id=stripe_subscription_id,
            provider_customer_id=customer_id,
            payment_status="checkout_completed",
            reason="checkout.session.completed",
        )
        result = {"status": "processed", "workspace_id": workspace_id, "plan_id": plan_id}
    return result


def process_invoice_object(invoice: Any, db: Session, payment_status: str, reason: str) -> dict[str, Any]:
    stripe_subscription_id = _get(invoice, "subscription")
    customer_id = _get(invoice, "customer")
    workspace_id = _workspace_from_subscription(stripe_subscription_id, db) or _workspace_from_customer(customer_id, db)
    if not workspace_id:
        return {"status": "skipped", "reason": "missing_invoice_workspace"}
    update_payment_status(workspace_id, payment_status, db, provider="stripe", reason=reason)
    return {"status": "processed", "workspace_id": workspace_id, "payment_status": payment_status}


def handle_webhook_event(event: Any, db: Session) -> dict[str, Any]:
    event_id = _get(event, "id")
    event_type = _get(event, "type")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Invalid Stripe event")

    existing = db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == event_id).first()
    if existing and existing.processed:
        return {"status": "ok", "detail": "Already processed", "event_id": event_id}
    if not existing:
        db.add(WebhookEvent(id=str(uuid.uuid4()), stripe_event_id=event_id, processed=False))
        db.commit()

    data_object = _get(_get(event, "data"), "object")
    logger.info("Processing Stripe webhook event %s [%s]", event_type, event_id)
    try:
        if event_type == "checkout.session.completed":
            result = process_checkout_completed(data_object, db)
        elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            result = process_subscription_object(data_object, db, event_type)
        elif event_type == "invoice.paid":
            result = process_invoice_object(data_object, db, "paid", event_type)
        elif event_type == "invoice.payment_failed":
            result = process_invoice_object(data_object, db, "payment_failed", event_type)
        elif event_type == "invoice.finalized":
            result = process_invoice_object(data_object, db, "invoice_finalized", event_type)
        else:
            result = {"status": "ignored", "event_type": event_type}

        shadow = db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == event_id).first()
        if shadow:
            shadow.processed = True
        db.add(SubscriptionEvent(
            id=str(uuid.uuid4()),
            stripe_subscription_id=str(_get(data_object, "subscription") or _get(data_object, "id") or event_id),
            event_type=event_type,
            payload=json.dumps(result, sort_keys=True),
        ))
        db.commit()
        return {"status": "ok", "event_id": event_id, "event_type": event_type, "result": result}
    except Exception:
        logger.exception("Stripe webhook event failed [%s]", event_id)
        db.rollback()
        raise


def construct_webhook_event(payload: bytes, signature: str | None) -> Any:
    settings = configure_stripe()
    if not settings.webhook_configured:
        raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured.")
    try:
        return stripe.Webhook.construct_event(payload, signature, settings.webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
