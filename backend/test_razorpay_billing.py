"""Razorpay (INR, UPI Autopay) subscriptions: checkout, verification, webhooks, cancellation.

The Razorpay API is replaced by an httpx MockTransport; signatures are computed
exactly as Razorpay documents them, so a forged browser callback or webhook fails.
"""

import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from core import razorpay_billing
from core.db import SessionLocal
from core.models import WorkspaceSubscription
from test_production_hardening import _make_user

KEY_SECRET = "rzp_test_secret_value"
WEBHOOK_SECRET = "whsec_rzp_test"


class FakeRazorpay:
    def __init__(self):
        self.subs = {}
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path.removeprefix("/v1")
        if request.method == "POST" and path == "/subscriptions":
            body = json.loads(request.content)
            sid = f"sub_{uuid.uuid4().hex[:14]}"
            self.subs[sid] = {"id": sid, "plan_id": body["plan_id"], "status": "created", "notes": body["notes"],
                              "customer_id": None, "current_start": None, "current_end": None,
                              "short_url": f"https://rzp.io/i/{sid}"}
            return httpx.Response(200, json=self.subs[sid])
        if request.method == "GET" and path.startswith("/subscriptions/"):
            return httpx.Response(200, json=self.subs[path.split("/")[2]])
        if request.method == "POST" and path.endswith("/cancel"):
            sid = path.split("/")[2]
            body = json.loads(request.content)
            if not body.get("cancel_at_cycle_end"):
                self.subs[sid]["status"] = "cancelled"
            return httpx.Response(200, json=self.subs[sid])
        return httpx.Response(404, json={"error": {"description": "not found"}})

    def pay(self, sid):
        now = int(time.time())
        self.subs[sid].update({"status": "authenticated", "current_start": now, "current_end": now + 30 * 86400,
                               "customer_id": "cust_1"})


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(razorpay_billing, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("RAZORPAY_PLAN_PRO_MONTHLY", "plan_pro_m")
    monkeypatch.setenv("RAZORPAY_PLAN_TEAM_ANNUAL", "plan_team_y")
    return fake


def _sign(payment_id, sub_id, secret=KEY_SECRET):
    return hmac.new(secret.encode(), f"{payment_id}|{sub_id}".encode(), hashlib.sha256).hexdigest()


def _plan(ws):
    db = SessionLocal()
    try:
        sub = db.query(WorkspaceSubscription).filter(WorkspaceSubscription.workspace_id == ws).first()
        return (sub.plan_id, sub.status, sub.cancel_at_period_end) if sub else None
    finally:
        db.close()


def _webhook(client, event, entity, *, secret=WEBHOOK_SECRET, event_id=None, created_at=None):
    body = json.dumps({"event": event, "contains": ["subscription"], "created_at": created_at or int(time.time()),
                       "payload": {"subscription": {"entity": entity}}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/billing/razorpay/webhook", content=body, headers={
        "X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id or f"evt_{time.time_ns()}",
        "Content-Type": "application/json"})


def test_providers_endpoint_reports_razorpay_and_upi(rzp):
    body = TestClient(main.app).get("/billing/providers").json()
    assert body["razorpay"]["configured"] and "upi" in body["razorpay"]["methods"]
    assert {(p["plan_id"], p["interval"]) for p in body["razorpay"]["plans"]} == {("pro", "monthly"), ("team", "annual")}


def test_checkout_verify_activates_plan(rzp):
    client = TestClient(main.app)
    owner = _make_user()
    start = client.post("/billing/razorpay/subscription", headers=owner["headers"],
                        json={"plan_id": "pro", "interval": "monthly"})
    assert start.status_code == 200, start.text
    data = start.json()
    assert data["key_id"] == "rzp_test_key" and data["subscription_id"].startswith("sub_")
    sid = data["subscription_id"]
    assert rzp.subs[sid]["notes"]["workspace_id"] == owner["workspace_id"]
    assert (_plan(owner["workspace_id"]) or ("free",))[0] != "pro"  # nothing changes before payment

    # A forged callback (wrong signature) is rejected.
    bad = client.post("/billing/razorpay/verify", headers=owner["headers"], json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid, "razorpay_signature": "0" * 64})
    assert bad.status_code == 400

    rzp.pay(sid)
    ok = client.post("/billing/razorpay/verify", headers=owner["headers"], json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid, "razorpay_signature": _sign("pay_1", sid)})
    assert ok.status_code == 200, ok.text
    assert _plan(owner["workspace_id"])[:2] == ("pro", "active")
    limits = client.get("/billing/limits", headers=owner["headers"]).json()
    assert json.dumps(limits).count("1000") >= 1  # Pro AI-question allowance applies

    # A second paid subscription is refused (no double charge).
    again = client.post("/billing/razorpay/subscription", headers=owner["headers"], json={"plan_id": "team", "interval": "annual"})
    assert again.status_code == 409

    # Another workspace can't verify (or hijack) this subscription.
    other = _make_user()
    steal = client.post("/billing/razorpay/verify", headers=other["headers"], json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid, "razorpay_signature": _sign("pay_1", sid)})
    assert steal.status_code == 404


def test_only_admins_can_buy(rzp):
    client = TestClient(main.app)
    owner = _make_user()
    member = _make_user(role="Member", workspace_id=owner["workspace_id"])
    r = client.post("/billing/razorpay/subscription", headers=member["headers"], json={"plan_id": "pro"})
    assert r.status_code in (403, 404)


def test_webhooks_renew_fail_and_cancel(rzp):
    client = TestClient(main.app)
    owner = _make_user()
    sid = client.post("/billing/razorpay/subscription", headers=owner["headers"],
                      json={"plan_id": "team", "interval": "annual"}).json()["subscription_id"]
    now = int(time.time())
    entity = {**rzp.subs[sid], "status": "active", "current_start": now, "current_end": now + 365 * 86400}

    assert _webhook(client, "subscription.activated", entity, secret="wrong").status_code == 400
    r = _webhook(client, "subscription.activated", entity, event_id="evt_a")
    assert r.status_code == 200, r.text
    assert _plan(owner["workspace_id"])[:2] == ("team", "active")
    # Duplicate delivery is a no-op.
    assert _webhook(client, "subscription.activated", entity, event_id="evt_a").json()["detail"] == "Already processed"

    _webhook(client, "subscription.pending", {**entity, "status": "pending"}, created_at=now + 10)
    assert _plan(owner["workspace_id"])[:2] == ("team", "past_due")  # still usable while Razorpay retries
    _webhook(client, "subscription.halted", {**entity, "status": "halted"}, created_at=now + 20)
    assert _plan(owner["workspace_id"])[1] == "unpaid"
    # An older event arriving late never overrides a newer one.
    _webhook(client, "subscription.charged", {**entity, "status": "active"}, created_at=now + 5)
    assert _plan(owner["workspace_id"])[1] == "unpaid"
    _webhook(client, "subscription.charged", {**entity, "status": "active"}, created_at=now + 30)
    assert _plan(owner["workspace_id"])[:2] == ("team", "active")

    # Cancel at the end of the paid cycle: stays active, flagged to end.
    r = client.post("/billing/razorpay/cancel", headers=owner["headers"], json={"at_cycle_end": True})
    assert r.status_code == 200 and r.json()["status"] == "cancel_scheduled"
    assert _plan(owner["workspace_id"]) == ("team", "active", True)
    _webhook(client, "subscription.cancelled", {**entity, "status": "cancelled", "ended_at": now + 40},
             created_at=now + 40)
    assert _plan(owner["workspace_id"])[1] == "canceled"


def test_unconfigured_server_says_so(monkeypatch):
    for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        monkeypatch.delenv(key, raising=False)
    owner = _make_user()
    r = TestClient(main.app).post("/billing/razorpay/subscription", headers=owner["headers"], json={"plan_id": "pro"})
    assert r.status_code == 503 and "not set up" in r.json()["error"]
