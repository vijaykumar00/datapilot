"""
razorpay_billing.py — INR subscriptions through Razorpay (UPI Autopay, cards, eMandate).

Flow
  1. POST /billing/razorpay/subscription creates a Razorpay subscription for the
     workspace (plan + interval → a Razorpay plan id from the environment) and
     returns what Razorpay Checkout needs.  Notes carry workspace_id/plan_id.
  2. The browser opens Razorpay Checkout; the customer pays with UPI Autopay or a card.
  3. POST /billing/razorpay/verify checks the payment signature
     (HMAC-SHA256 of "payment_id|subscription_id" with the key secret) and
     activates the plan right away.
  4. Webhooks (X-Razorpay-Signature = HMAC-SHA256 of the raw body with the webhook
     secret) keep the plan in sync: renewals, failed payments, cancellation.

Razorpay is the source of truth for payments; the plan state is written through the
provider-neutral ``sync_provider_subscription`` exactly like Stripe's.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.models import Plan, Subscription, SubscriptionEvent, WebhookEvent, WorkspaceSubscription
from core.subscriptions import sync_provider_subscription

logger = logging.getLogger("datapilot.razorpay")

API_BASE = "https://api.razorpay.com/v1"


def _api_base() -> str:
    # Overridable only for local end-to-end tests against a stub server.
    return (os.getenv("RAZORPAY_API_BASE") or API_BASE).rstrip("/")
PAID_PLANS = ("pro", "team")
# Prefix for Razorpay ids in the shared shadow tables, so they can never collide with Stripe's.
_ID_PREFIX = "rzp:"
# Billing cycles per subscription before it has to be renewed by the customer.
_TOTAL_COUNT = {"monthly": 120, "annual": 10}

# Razorpay subscription status → plan status used across Tallis.
STATUS_MAP = {
    "created": "incomplete",
    "authenticated": "incomplete",
    "active": "active",
    "pending": "past_due",   # a renewal charge failed; Razorpay is retrying
    "halted": "unpaid",      # retries exhausted
    "paused": "paused",
    "cancelled": "canceled",
    "completed": "canceled",
    "expired": "canceled",
}


@dataclass(frozen=True)
class RazorpaySettings:
    key_id: str
    key_secret: str
    webhook_secret: str
    company_name: str

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.webhook_secret)

    @property
    def mode(self) -> str:
        return "live" if self.key_id.startswith("rzp_live_") else "test"


def get_razorpay_settings() -> RazorpaySettings:
    return RazorpaySettings(
        key_id=os.getenv("RAZORPAY_KEY_ID", "").strip(),
        key_secret=os.getenv("RAZORPAY_KEY_SECRET", "").strip(),
        webhook_secret=os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip(),
        company_name=os.getenv("BILLING_COMPANY_NAME", "Tallis").strip() or "Tallis",
    )


def plan_env_key(plan_id: str, interval: str) -> str:
    return f"RAZORPAY_PLAN_{plan_id.upper()}_{'ANNUAL' if interval == 'annual' else 'MONTHLY'}"


def normalize_interval(interval: str) -> str:
    return "annual" if interval in {"annual", "yearly", "year"} else "monthly"


def razorpay_plan_for(plan_id: str, interval: str) -> str:
    value = os.getenv(plan_env_key(plan_id, interval), "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=(
            f"Paying in INR for this plan isn't set up yet ({plan_env_key(plan_id, interval)} is missing)."))
    return value


def mapping_report() -> list[dict[str, Any]]:
    return [
        {"plan_id": plan_id, "interval": interval, "env": plan_env_key(plan_id, interval),
         "configured": bool(os.getenv(plan_env_key(plan_id, interval), "").strip())}
        for plan_id in PAID_PLANS for interval in ("monthly", "annual")
    ]


def require_razorpay() -> RazorpaySettings:
    settings = get_razorpay_settings()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="INR payments (Razorpay) are not set up on this server yet.")
    return settings


# ── HTTP ─────────────────────────────────────────────────────────────────────

_transport: httpx.BaseTransport | None = None  # tests inject a MockTransport


def _client(settings: RazorpaySettings) -> httpx.Client:
    return httpx.Client(base_url=_api_base(), auth=(settings.key_id, settings.key_secret),
                        timeout=httpx.Timeout(15.0, connect=5.0), transport=_transport)


def _call(method: str, path: str, settings: RazorpaySettings, payload: dict | None = None) -> dict[str, Any]:
    try:
        with _client(settings) as client:
            resp = client.request(method, path, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("Razorpay request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Razorpay could not be reached. Please try again.") from exc
    if resp.status_code >= 400:
        try:
            description = resp.json().get("error", {}).get("description") or ""
        except ValueError:
            description = ""
        logger.warning("Razorpay %s %s -> %s %s", method, path, resp.status_code, description)
        raise HTTPException(status_code=502, detail="Razorpay rejected the request. Please try again or contact support.")
    return resp.json()


# ── Signatures ───────────────────────────────────────────────────────────────

def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def payment_signature_valid(payment_id: str, subscription_id: str, signature: str, secret: str) -> bool:
    expected = _hmac_hex(secret, f"{payment_id}|{subscription_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def webhook_signature_valid(body: bytes, signature: str | None, secret: str) -> bool:
    return bool(signature) and hmac.compare_digest(_hmac_hex(secret, body), signature)


# ── Subscriptions ────────────────────────────────────────────────────────────

def _ts(value: Any) -> datetime.datetime | None:
    try:
        return datetime.datetime.utcfromtimestamp(int(value)) if value else None
    except (TypeError, ValueError, OSError):
        return None


def _notes(entity: dict) -> dict:
    notes = entity.get("notes")
    return notes if isinstance(notes, dict) else {}


def _shadow(rzp_subscription_id: str, db: Session) -> Subscription | None:
    return db.query(Subscription).filter(Subscription.stripe_subscription_id == _ID_PREFIX + rzp_subscription_id).first()


def create_subscription(caller: Any, workspace_id: str, plan_id: str, interval: str, db: Session) -> dict[str, Any]:
    settings = require_razorpay()
    interval = normalize_interval(interval)
    if plan_id not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Choose the Pro or Business plan.")
    if db.query(Plan.plan_id).filter(Plan.plan_id == plan_id, Plan.is_active == True).first() is None:  # noqa: E712
        raise HTTPException(status_code=404, detail="Plan not found")
    current = db.query(WorkspaceSubscription).filter(WorkspaceSubscription.workspace_id == workspace_id).first()
    paying = (current is not None and current.plan_id not in ("free", None)
              and current.status in ("active", "past_due") and not current.cancel_at_period_end
              and json.loads(current.metadata_json or "{}").get("payment_provider") in ("razorpay", "stripe"))
    if paying and current.plan_id == plan_id:
        raise HTTPException(status_code=409, detail="This workspace is already on that plan.")
    if paying:
        # Never run two paid subscriptions at once (double charge).
        raise HTTPException(status_code=409, detail=(
            "This workspace already has a paid plan. Cancel it first — it stays active until the end of the "
            "period you paid for — then choose the new plan."))

    body = {
        "plan_id": razorpay_plan_for(plan_id, interval),
        "total_count": _TOTAL_COUNT[interval],
        "quantity": 1,
        "customer_notify": 1,
        "notes": {"workspace_id": workspace_id, "plan_id": plan_id, "interval": interval,
                  "user_id": getattr(caller, "user_id", "")},
    }
    sub = _call("POST", "/subscriptions", settings, body)
    rzp_id = sub.get("id")
    if not rzp_id:
        raise HTTPException(status_code=502, detail="Razorpay did not return a subscription.")
    now = datetime.datetime.utcnow()
    db.add(Subscription(
        id=str(uuid.uuid4()), workspace_id=workspace_id, stripe_subscription_id=_ID_PREFIX + rzp_id,
        status=sub.get("status", "created"), plan_id=plan_id, current_period_start=now, current_period_end=now,
        cancel_at_period_end=False,
    ))
    db.flush()
    user = getattr(caller, "user", None)
    return {
        "provider": "razorpay",
        "key_id": settings.key_id,
        "subscription_id": rzp_id,
        "short_url": sub.get("short_url"),
        "name": settings.company_name,
        "description": f"{plan_id.title() if plan_id != 'team' else 'Business'} plan · {interval}",
        "prefill": {"email": getattr(user, "email", "") or "", "name": getattr(user, "full_name", "") or ""},
        "mode": settings.mode,
    }


def _apply_entity(entity: dict, db: Session, reason: str, *, workspace_hint: str | None = None,
                  event_at: int | None = None) -> dict[str, Any]:
    rzp_id = entity.get("id")
    if not rzp_id:
        return {"status": "skipped", "reason": "missing_subscription"}
    shadow = _shadow(rzp_id, db)
    if shadow is not None and event_at is not None and shadow.last_event_at and int(event_at) < int(shadow.last_event_at):
        return {"status": "skipped", "reason": "stale_event"}
    notes = _notes(entity)
    workspace_id = notes.get("workspace_id") or (shadow.workspace_id if shadow else None) or workspace_hint
    plan_id = notes.get("plan_id") or (shadow.plan_id if shadow else None)
    if not workspace_id or not plan_id:
        logger.warning("Razorpay subscription %s has no workspace/plan mapping; skipped", rzp_id)
        return {"status": "skipped", "reason": "missing_mapping"}
    if shadow is not None and shadow.workspace_id != workspace_id:
        logger.error("Razorpay subscription %s workspace mismatch; skipped", rzp_id)
        return {"status": "skipped", "reason": "workspace_mismatch"}

    rzp_status = str(entity.get("status") or "active")
    status = STATUS_MAP.get(rzp_status, "incomplete")
    start, end = _ts(entity.get("current_start")), _ts(entity.get("current_end"))
    # Razorpay keeps a subscription "active" until the cycle ends after a scheduled cancel.
    cancel_at_end = bool(shadow.cancel_at_period_end) if shadow is not None and status == "active" else False
    if status in {"incomplete"}:
        # Not paid yet: never change the workspace's plan for a checkout that wasn't completed.
        if shadow is not None:
            shadow.status = rzp_status
        return {"status": "pending_payment", "workspace_id": workspace_id}

    if shadow is None:
        shadow = Subscription(id=str(uuid.uuid4()), workspace_id=workspace_id,
                              stripe_subscription_id=_ID_PREFIX + rzp_id, status=rzp_status, plan_id=plan_id,
                              current_period_start=start or datetime.datetime.utcnow(),
                              current_period_end=end or datetime.datetime.utcnow())
        db.add(shadow)
    shadow.status = rzp_status
    shadow.plan_id = plan_id
    shadow.current_period_start = start or shadow.current_period_start
    shadow.current_period_end = end or shadow.current_period_end
    shadow.cancel_at_period_end = cancel_at_end
    if event_at is not None:
        shadow.last_event_at = int(event_at)
    db.flush()

    # Same rule as Stripe: the plan is kept with its status; canceled/unpaid/paused → Free limits apply.
    sync_provider_subscription(
        workspace_id, plan_id, status, db,
        provider="razorpay", provider_subscription_id=rzp_id, provider_customer_id=entity.get("customer_id"),
        payment_status=rzp_status, current_period_start=start, current_period_end=end,
        cancel_at_period_end=cancel_at_end, canceled_at=_ts(entity.get("ended_at")), reason=reason,
    )
    return {"status": "processed", "workspace_id": workspace_id, "plan_id": plan_id, "plan_status": status,
            "razorpay_status": rzp_status}


def verify_checkout(workspace_id: str, payment_id: str, subscription_id: str, signature: str, db: Session) -> dict:
    """Called by the browser after Checkout succeeds: activates the plan immediately."""
    settings = require_razorpay()
    shadow = _shadow(subscription_id, db)
    if shadow is None or shadow.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Subscription not found for this workspace.")
    if not payment_signature_valid(payment_id, subscription_id, signature, settings.key_secret):
        raise HTTPException(status_code=400, detail="Payment could not be verified.")
    entity = _call("GET", f"/subscriptions/{subscription_id}", settings)
    if entity.get("status") not in {"authenticated", "active"}:
        raise HTTPException(status_code=409, detail="The payment is not complete yet. Refresh in a minute.")
    if entity.get("status") == "authenticated":
        # Mandate approved and first payment made; Razorpay flips it to "active" moments later.
        entity = {**entity, "status": "active"}
    result = _apply_entity(entity, db, "razorpay.checkout_verified",
                           event_at=int(datetime.datetime.utcnow().timestamp()))
    db.commit()
    return result


def cancel_subscription(workspace_id: str, db: Session, *, at_cycle_end: bool = True) -> dict[str, Any]:
    settings = require_razorpay()
    sub = db.query(WorkspaceSubscription).filter(WorkspaceSubscription.workspace_id == workspace_id).first()
    meta = json.loads(sub.metadata_json or "{}") if sub else {}
    rzp_id = meta.get("provider_subscription_id") if meta.get("payment_provider") == "razorpay" else None
    if not rzp_id:
        raise HTTPException(status_code=404, detail="This workspace has no Razorpay subscription.")
    entity = _call("POST", f"/subscriptions/{rzp_id}/cancel", settings, {"cancel_at_cycle_end": 1 if at_cycle_end else 0})
    shadow = _shadow(rzp_id, db)
    if shadow is not None and at_cycle_end:
        shadow.cancel_at_period_end = True
    if at_cycle_end and sub is not None:
        sub.cancel_at_period_end = True
        db.commit()
        return {"status": "cancel_scheduled", "ends_at": sub.current_period_end.isoformat() if sub.current_period_end else None}
    result = _apply_entity(entity, db, "razorpay.cancelled_now", event_at=int(datetime.datetime.utcnow().timestamp()))
    db.commit()
    return result


SUBSCRIPTION_EVENTS = {
    "subscription.authenticated", "subscription.activated", "subscription.charged", "subscription.completed",
    "subscription.updated", "subscription.pending", "subscription.halted", "subscription.cancelled",
    "subscription.paused", "subscription.resumed",
}


def handle_webhook(body: bytes, signature: str | None, event_id: str | None, db: Session) -> dict[str, Any]:
    settings = get_razorpay_settings()
    if not settings.webhook_configured:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret is not configured.")
    if not webhook_signature_valid(body, signature, settings.webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook payload")
    event_type = event.get("event", "")
    key = _ID_PREFIX + (event_id or hashlib.sha256(body).hexdigest())

    existing = db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == key).first()
    if existing and existing.processed:
        return {"status": "ok", "detail": "Already processed"}
    if not existing:
        from sqlalchemy.exc import IntegrityError

        db.add(WebhookEvent(id=str(uuid.uuid4()), stripe_event_id=key, processed=False))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Razorpay event is already being processed")

    try:
        if event_type in SUBSCRIPTION_EVENTS:
            entity = ((event.get("payload") or {}).get("subscription") or {}).get("entity") or {}
            result = _apply_entity(entity, db, event_type, event_at=event.get("created_at"))
        else:
            result = {"status": "ignored", "event_type": event_type}
        row = db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == key).first()
        if row:
            row.processed = True
        db.add(SubscriptionEvent(id=str(uuid.uuid4()), stripe_subscription_id=_ID_PREFIX + str(
            (((event.get("payload") or {}).get("subscription") or {}).get("entity") or {}).get("id") or key),
            event_type=event_type, payload=json.dumps(result, sort_keys=True)))
        db.commit()
        return {"status": "ok", "event_type": event_type, "result": result}
    except Exception:
        logger.exception("Razorpay webhook failed [%s]", event_type)
        db.rollback()
        raise
