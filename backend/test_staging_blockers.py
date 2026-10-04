"""
Regression tests for the production blockers found by the staging validation run.

Each section maps to one blocker:
  1. Sentry + routed FastAPI endpoints (recursion after ~960 requests)
  2. Stripe webhooks with real stripe-python SDK objects (StripeObject is not a dict)
  3. DB connections held while waiting on jobs / hashing passwords (pool exhaustion)
  4. Leading-zero identifiers (ZIP codes, IDs) silently converted to numbers
  5. APP_URL configuration for verification / reset links
  6. Object-storage timeouts and 503 mapping
  7. Job recovery (visibility timeout, lease fencing)
  8. Atomic refresh-token rotation
  9. AI quota not consumed when no result is produced
 10. Infrastructure errors -> 502/503 with request id, no internals
"""

import asyncio
import datetime
import hashlib
import hmac
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import stripe
from fastapi.testclient import TestClient

import main
from core import jobs
from core.db import SessionLocal, engine
from core.models import Job, RefreshToken, Subscription, SubscriptionEvent, UsageStats, WebhookEvent
from test_production_hardening import FakeLLM, _make_user, _sse_events

BACKEND = Path(__file__).parent


def _client():
    return TestClient(main.app)


def _upload(client, headers, content: bytes, name="data.csv"):
    resp = client.post("/upload", headers=headers, files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sentry
# ─────────────────────────────────────────────────────────────────────────────

SENTRY_SCRIPT = r"""
import os, sys, json
sys.path.insert(0, os.getcwd())
os.environ["SENTRY_DSN"] = "http://publickey@127.0.0.1:9/1"
os.environ["SENTRY_TRACES_SAMPLE_RATE"] = "1.0"
os.environ["RATE_LIMIT_BILLING_MAX_REQUESTS"] = "1000000"
os.environ["RATE_LIMIT_MAX_REQUESTS"] = "1000000"
import sentry_sdk
from sentry_sdk.transport import Transport

captured = []

class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                captured.append(item.payload.json)

_orig_init = sentry_sdk.init
def _init(*a, **k):
    k["transport"] = Capture
    return _orig_init(*a, **k)
sentry_sdk.init = _init

import conftest  # isolated DB / storage, migrated schema
import main
from fastapi.testclient import TestClient

assert sentry_sdk.get_client().is_active(), "Sentry was not initialised"

@main.app.get("/__sentry_boom")
def boom():
    raise RuntimeError("sentry regression boom")

client = TestClient(main.app, raise_server_exceptions=False)
statuses = {}
# Router-included routes (billing router) are the ones that leaked a wrapper per request.
for i in range(int(os.environ.get("N_REQ", "1300"))):
    for path in ("/billing/plans", "/health"):
        r = client.get(path)
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
r = client.get("/__sentry_boom")
sentry_sdk.flush(5)
errors = [e for e in captured if any("sentry regression boom" in (x.get("value") or "")
          for x in (e.get("exception") or {}).get("values", []))]
print(json.dumps({"statuses": statuses, "boom_status": r.status_code, "boom_events": len(errors),
                  "version": sentry_sdk.VERSION}))
"""


def test_sentry_enabled_router_endpoints_do_not_degrade_and_events_are_sent(tmp_path):
    script = tmp_path / "sentry_regression.py"
    script.write_text(SENTRY_SCRIPT)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}
    env.pop("DATABASE_URL", None) if "sqlite" in env.get("DATABASE_URL", "") else None
    proc = subprocess.run([sys.executable, str(script)], cwd=str(BACKEND), env=env, capture_output=True,
                          text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    # Every one of the 2,600 routed requests succeeded (2.19.2 failed permanently after ~960).
    assert out["statuses"] == {"200": 2600}, out
    assert out["boom_status"] == 500
    assert out["boom_events"] >= 1, out  # unhandled exceptions still reach Sentry


def test_sentry_sdk_pinned_to_verified_version():
    import sentry_sdk

    major, minor = (int(x) for x in sentry_sdk.VERSION.split(".")[:2])
    assert (major, minor) >= (2, 71), sentry_sdk.VERSION
    reqs = (BACKEND / "requirements.txt").read_text()
    assert "sentry-sdk==2.71.0" in reqs
    assert "stripe==16.0.0" in reqs


# ─────────────────────────────────────────────────────────────────────────────
# 2. Stripe webhooks with real SDK objects
# ─────────────────────────────────────────────────────────────────────────────

WHSEC = "whsec_regression_secret"


@pytest.fixture
def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_regression")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_regression")
    yield


def _signed(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(WHSEC.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def _post_event(client, payload: dict):
    body, header = _signed(payload)
    return client.post("/billing/webhook", content=body,
                       headers={"Stripe-Signature": header, "Content-Type": "application/json"})


def _subscription_obj(sub_id, ws, status="active", plan="pro", new_api_shape=True):
    obj = {"id": sub_id, "object": "subscription", "customer": f"cus_{ws[:8]}", "status": status,
           "cancel_at_period_end": False, "metadata": {"workspace_id": ws, "plan_id": plan},
           "items": {"object": "list", "data": [{"id": "si_1", "object": "subscription_item",
                                                 "price": {"id": "price_x", "object": "price"}}]}}
    period = {"current_period_start": 1767225600, "current_period_end": 1769904000}
    if new_api_shape:  # API 2025-03-31+: periods live on the subscription items
        obj["items"]["data"][0].update(period)
    else:
        obj.update(period)
    return obj


def _event(event_type, obj, created, event_id=None):
    return {"id": event_id or f"evt_{uuid.uuid4().hex}", "object": "event", "type": event_type,
            "created": created, "api_version": "2026-09-30.endive", "data": {"object": obj}}


def _plan_of(ws):
    from core.usage import effective_plan

    db = SessionLocal()
    try:
        return effective_plan(ws, db)[0]
    finally:
        db.close()


def test_real_sdk_event_objects_are_parsed_not_skipped(stripe_env):
    """stripe>=13: StripeObject is not a dict — metadata must still be read."""
    from core.stripe_billing import _metadata, handle_webhook_event

    owner = _make_user()
    ws = owner["workspace_id"]
    ev = stripe.Event.construct_from(_event("customer.subscription.created",
                                            _subscription_obj(f"sub_{uuid.uuid4().hex[:10]}", ws), 100), "sk_test")
    assert not isinstance(ev.data.object, dict)  # really the SDK type, not a dict
    assert _metadata(ev.data.object) == {"workspace_id": ws, "plan_id": "pro"}
    db = SessionLocal()
    try:
        out = handle_webhook_event(ev, db)
    finally:
        db.close()
    assert out["result"]["status"] == "processed", out
    assert _plan_of(ws) == "pro"


def test_signed_webhooks_update_subscription_dedupe_and_ignore_stale(stripe_env):
    client = _client()
    owner = _make_user()
    ws = owner["workspace_id"]
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"

    created = _event("customer.subscription.created", _subscription_obj(sub_id, ws), 100)
    r = _post_event(client, created)
    assert r.status_code == 200 and r.json()["result"]["status"] == "processed", r.text
    assert _plan_of(ws) == "pro"

    # Duplicate delivery of the same event: acknowledged, not re-applied.
    r2 = _post_event(client, created)
    assert r2.status_code == 200 and r2.json()["detail"] == "Already processed"
    db = SessionLocal()
    try:
        assert db.query(SubscriptionEvent).filter(SubscriptionEvent.stripe_subscription_id == sub_id).count() == 1
        assert db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == created["id"]).count() == 1
    finally:
        db.close()

    # Out of order: "deleted" (newer) arrives before "updated" (older) -> stays canceled.
    r3 = _post_event(client, _event("customer.subscription.deleted", _subscription_obj(sub_id, ws, "canceled"), 300))
    assert r3.json()["result"]["status"] == "processed", r3.text
    r4 = _post_event(client, _event("customer.subscription.updated", _subscription_obj(sub_id, ws, "active"), 200))
    assert r4.status_code == 200 and r4.json()["result"]["reason"] == "stale_event", r4.text
    db = SessionLocal()
    try:
        assert db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first().status == "canceled"
    finally:
        db.close()

    # Bad signature is rejected.
    body, _ = _signed(created)
    bad = client.post("/billing/webhook", content=body, headers={"Stripe-Signature": "t=1,v1=deadbeef"})
    assert bad.status_code == 400


def test_checkout_completed_with_sdk_retrieve_object_activates_plan(stripe_env):
    client = _client()
    owner = _make_user()
    ws = owner["workspace_id"]
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    retrieved = stripe.Subscription.construct_from(_subscription_obj(sub_id, ws, plan="team"), "sk_test")
    session = {"id": "cs_test_1", "object": "checkout.session", "mode": "subscription",
               "client_reference_id": ws, "customer": f"cus_{ws[:8]}", "subscription": sub_id,
               "metadata": {"workspace_id": ws, "plan_id": "team"}}
    with patch.object(stripe.Subscription, "retrieve", return_value=retrieved) as retrieve:
        r = _post_event(client, _event("checkout.session.completed", session, 400))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["status"] == "processed", r.text
    retrieve.assert_called_once_with(sub_id)
    assert _plan_of(ws) == "team"
    from core.models import BillingCustomer

    db = SessionLocal()
    try:
        assert db.query(BillingCustomer).filter(BillingCustomer.workspace_id == ws).first().stripe_customer_id == f"cus_{ws[:8]}"
        shadow = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
        assert shadow.current_period_end is not None  # read from items (new API shape)
    finally:
        db.close()


def test_invoice_events_resolve_subscription_in_new_api_shape(stripe_env):
    from core.stripe_billing import _invoice_subscription_id

    inv = stripe.Invoice.construct_from({"id": "in_1", "object": "invoice", "customer": "cus_x",
                                         "parent": {"type": "subscription_details",
                                                    "subscription_details": {"subscription": "sub_abc"}}}, "sk")
    from core.stripe_billing import _plain

    assert _invoice_subscription_id(_plain(inv)) == "sub_abc"
    assert _invoice_subscription_id({"subscription": "sub_old"}) == "sub_old"


# ─────────────────────────────────────────────────────────────────────────────
# 3. DB connections are released before waits / CPU-heavy work
# ─────────────────────────────────────────────────────────────────────────────

def _checked_out() -> int:
    return engine.pool.checkedout()


def test_get_caller_releases_its_connection():
    from core.request_identity import get_caller

    owner = _make_user()
    gen = main.get_db()
    db = next(gen)
    try:
        before = _checked_out()
        caller = get_caller(authorization=owner["headers"]["Authorization"], x_guest_token=None,
                            x_workspace_id=owner["workspace_id"], db=db)
        assert not db.in_transaction()
        assert _checked_out() == before
        # Identity stays usable without silently re-checking-out a connection.
        assert caller.user_id == owner["user_id"] and caller.user.email == owner["email"]
        assert not db.in_transaction()
    finally:
        gen.close()


def test_export_and_report_routes_hold_no_connection_while_waiting(monkeypatch):
    client = _client()
    owner = _make_user(plan="pro")
    up = _upload(client, owner["headers"], b"region,revenue\nN,10\nS,20\n")
    seen: list[int] = []

    def fake_submit_and_wait(job_type, payload, **kw):
        seen.append(_checked_out())
        return {"job_id": "j", "status": "queued"}

    monkeypatch.setattr(jobs, "submit_and_wait", fake_submit_and_wait)
    from core.file_manager import FileManager

    table = FileManager().get_record(up["file_id"], owner["workspace_id"]).table_name
    h = owner["headers"]
    assert client.get(f"/export/file/{up['file_id']}?format=csv", headers=h).status_code == 202
    assert client.post("/export/results?format=csv", headers=h,
                       json={"sql": f"SELECT * FROM {table}", "file_ids": [up["file_id"]]}).status_code == 202
    assert client.post("/report/export", headers=h,
                       json={"file_id": up["file_id"], "format": "xlsx", "title": "r", "narrative": "n"}).status_code == 202
    assert len(seen) == 3
    assert seen == [0, 0, 0], f"connections checked out during job wait: {seen}"


def test_upload_holds_no_connection_while_waiting_for_ingest(monkeypatch):
    client = _client()
    owner = _make_user()
    seen: list[int] = []

    async def fake_await(job_id, timeout):
        seen.append(_checked_out())
        return {"job_id": job_id, "status": "queued"}

    monkeypatch.setattr(jobs, "execution_mode", lambda: "worker")
    monkeypatch.setattr(jobs, "await_job", fake_await)
    resp = client.post("/upload", headers=owner["headers"],
                       files={"file": ("a.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert resp.status_code == 202, resp.text
    assert seen == [0], seen


def test_password_hashing_runs_without_a_checked_out_connection(monkeypatch):
    import core.auth_routes as auth_routes
    import core.user_routes as user_routes

    client = _client()
    seen: list[tuple[str, int]] = []
    real_hash, real_verify = auth_routes.hash_password, auth_routes.verify_password

    def spy_hash(pw):
        seen.append(("hash", _checked_out()))
        return real_hash(pw)

    def spy_verify(pw, h):
        seen.append(("verify", _checked_out()))
        return real_verify(pw, h)

    monkeypatch.setattr(auth_routes, "hash_password", spy_hash)
    monkeypatch.setattr(auth_routes, "verify_password", spy_verify)
    monkeypatch.setattr(user_routes, "hash_password", spy_hash)
    monkeypatch.setattr(user_routes, "verify_password", spy_verify)

    email = f"hash-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/auth/signup", json={"email": email, "password": "SecurePassword123!"}).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": "SecurePassword123!"})
    assert login.status_code == 200, login.text
    assert client.post("/auth/login", json={"email": email, "password": "wrong-password-1"}).status_code == 401
    token = login.json()["access_token"]
    r = client.put("/user/password", headers={"Authorization": f"Bearer {token}"},
                   json={"current_password": "SecurePassword123!", "new_password": "AnotherSecure123!"})
    assert r.status_code == 200, r.text
    assert client.post("/auth/login", json={"email": email, "password": "AnotherSecure123!"}).status_code == 200
    assert seen and all(n == 0 for _, n in seen), seen


def test_concurrent_exports_do_not_pin_pool_connections(monkeypatch):
    """40 parallel export requests whose jobs take 1.5 s: before the fix every waiting
    request pinned a connection ("idle in transaction") and the pool ran dry."""
    owner = _make_user(plan="pro")
    up = _upload(_client(), owner["headers"], b"region,revenue\nN,10\nS,20\n")
    peak = {"value": None}
    barrier = threading.Barrier(40, timeout=90)

    def slow_submit_and_wait(job_type, payload, **kw):
        # All 40 requests rendezvous inside the job wait; only then is the pool sampled,
        # so nothing else is running.  If a waiting request still pinned a connection the
        # count is > 0 — and with the default pool (5 + 10) the barrier would never fill.
        if barrier.wait() == 0:
            peak["value"] = _checked_out()
        barrier.wait()
        time.sleep(0.2)
        return {"job_id": "j", "status": "queued"}

    monkeypatch.setattr(jobs, "submit_and_wait", slow_submit_and_wait)
    codes: list[int] = []

    def one():
        c = TestClient(main.app)
        codes.append(c.get(f"/export/file/{up['file_id']}?format=csv", headers=owner["headers"]).status_code)

    threads = [threading.Thread(target=one) for _ in range(40)]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    assert codes.count(202) == 40, codes
    assert peak["value"] == 0, f"connections checked out while 40 requests wait on jobs: {peak['value']}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Leading zeros (ZIP codes, IDs)
# ─────────────────────────────────────────────────────────────────────────────

def test_single_leading_zero_value_keeps_column_text_csv(tmp_path):
    from core.parsing import parse_file

    rows = ["zip,cust_id,amount,ratio"] + [f"{10000 + i},{5000 + i},{i}.25,0.{i % 9}" for i in range(2000)]
    rows.append("02134,0042,7.5,0.5")  # the ONLY leading-zero values, at the very end
    p = tmp_path / "zips.csv"
    p.write_text("\n".join(rows))
    df, meta = parse_file(str(p), ".csv")
    assert df["zip"].dtype == object and df["cust_id"].dtype == object
    assert df["zip"].iloc[-1] == "02134" and df["cust_id"].iloc[-1] == "0042"
    assert df["zip"].iloc[0] == "10000"
    assert str(df["amount"].dtype).startswith("float") and str(df["ratio"].dtype).startswith("float")
    assert not any(c["column"] in {"zip", "cust_id"} for c in meta.get("numeric_conversions", []))


def test_leading_zero_detection_rules():
    from core.parsing import _looks_identifier

    s = pd.Series
    assert _looks_identifier(s(["10001"] * 999 + ["00501"]))
    assert _looks_identifier(s(["007", None, "12"]))
    assert _looks_identifier(s([" 0123 "]))
    assert not _looks_identifier(s(["0", "0.5", "0,75", "10", "-0.2"]))
    assert not _looks_identifier(s(["1", "2", "3"]))


def test_xlsx_text_zip_codes_and_mixed_ids_preserved(tmp_path):
    from core.parsing import parse_file

    p = tmp_path / "zips.xlsx"
    pd.DataFrame({"zip": ["02134", "10001", "00501"], "acct": ["0007", "8", "9"],
                  "amt": [1.5, 2.0, 3.0]}).to_excel(p, index=False)
    df, _ = parse_file(str(p), ".xlsx")
    assert list(df["zip"]) == ["02134", "10001", "00501"]
    assert list(df["acct"].astype(str)) == ["0007", "8", "9"]
    assert str(df["amt"].dtype).startswith("float")


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_zip_codes_survive_upload_analysis_transform_export(fmt):
    from core.file_manager import FileManager

    client = _client()
    owner = _make_user(plan="pro")
    h = owner["headers"]
    body = "zip,store_id,revenue\n" + "\n".join(f"{z},{s},{r}" for z, s, r in [
        ("02134", "0001", 10), ("10001", "0002", 20), ("00501", "0103", 30), ("94105", "2001", 40)])
    up = _upload(client, h, body.encode(), "stores.csv")
    fid = up["file_id"]

    preview = client.get(f"/files/{fid}", headers=h).json()
    rows = json.dumps(preview)
    assert "02134" in rows and "00501" in rows and "0001" in rows

    # Analysis: a DuckDB query over the dataset returns the original text values.
    table = FileManager().get_record(fid, owner["workspace_id"]).table_name
    q = client.post("/export/results?format=csv", headers=h,
                    json={"sql": f"SELECT zip, store_id, revenue FROM {table} ORDER BY revenue", "file_ids": [fid]})
    assert q.status_code == 200, q.text
    assert q.text.splitlines()[1].startswith("02134,0001,")

    # Transform, then export the whole dataset.
    t = client.post(f"/files/{fid}/transform/pipeline", headers=h,
                    json={"pipeline": [{"action": "filter_rows", "column": "revenue", "operator": ">", "value": "5"}]})
    assert t.status_code == 200, t.text
    exp = client.get(f"/export/file/{fid}?format={fmt}", headers=h)
    assert exp.status_code == 200, exp.text
    if fmt == "csv":
        text = exp.content.decode("utf-8-sig")
        assert "02134,0001," in text and "00501,0103," in text
    else:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(exp.content))
        values = [[c.value for c in row] for row in wb.active.iter_rows()]
        zips = [r[0] for r in values[1:]]
        ids = [r[1] for r in values[1:]]
        assert "02134" in zips and "00501" in zips and "0001" in ids


# ─────────────────────────────────────────────────────────────────────────────
# 5. APP_URL
# ─────────────────────────────────────────────────────────────────────────────

_PROD_ENV = {
    "APP_ENV": "production", "JWT_SECRET": "a" * 64,
    "DATABASE_URL": "postgresql+psycopg2://u:p@postgres:5432/datapilot",
    "ALLOWED_ORIGINS": "https://app.datapilot.example", "REDIS_URL": "rediss://redis.internal:6379/0",
    "RATE_LIMITER_BACKEND": "redis", "STORAGE_PROVIDER": "s3", "S3_BUCKET": "dp",
    "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "ENCRYPTION_KEY": "x" * 44,
    "JOB_EXECUTION_MODE": "worker", "STRIPE_BILLING_ENABLED": "false", "SMTP_HOST": "smtp.internal",
    "APP_URL": "https://app.datapilot.example",
}


@pytest.mark.parametrize("value,ok", [
    ("https://app.datapilot.example", True),
    ("https://app.datapilot.example/", True),
    (None, False),
    ("", False),
    ("http://app.datapilot.example", False),
    ("https://localhost:5173", False),
    ("app.datapilot.example", False),
    ("https://app.datapilot.example/?x=1", False),
])
def test_production_requires_valid_app_url(value, ok):
    from scripts.validate_env import validate

    env = dict(_PROD_ENV)
    if value is None:
        env.pop("APP_URL")
    else:
        env["APP_URL"] = value
    errors = [e for e in validate(env) if "APP_URL" in e]
    assert (errors == []) is ok, errors


def test_api_startup_fails_clearly_without_app_url(monkeypatch):
    for k, v in _PROD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("APP_URL")
    with pytest.raises(RuntimeError, match="APP_URL"):
        with TestClient(main.app):
            pass


def test_verification_and_reset_links_use_configured_app_url(monkeypatch):
    import core.email_service as email_service

    sent = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, html, text: sent.append(html + text) or True)
    monkeypatch.setenv("APP_URL", "https://app.datapilot.example/")
    email_service.send_verification_email("a@example.com", None, "VTOKEN")
    email_service.send_password_reset_email("a@example.com", None, "RTOKEN")
    assert "https://app.datapilot.example/verify-email?token=VTOKEN" in sent[0]
    assert "https://app.datapilot.example/reset-password?token=RTOKEN" in sent[1]
    assert "localhost" not in "".join(sent)


def test_deploy_config_declares_app_url():
    compose = (BACKEND.parent / "docker-compose.yml").read_text()
    example = (BACKEND / ".env.example").read_text()
    assert "APP_URL: ${APP_URL:?" in compose
    assert "\nAPP_URL=" in example.replace("\r\n", "\n")
    assert "JOB_VISIBILITY_TIMEOUT_SECONDS: ${JOB_VISIBILITY_TIMEOUT_SECONDS:-90}" in compose


# ─────────────────────────────────────────────────────────────────────────────
# 6. Storage timeouts
# ─────────────────────────────────────────────────────────────────────────────

class _BlackHole:
    """TCP server that accepts connections and never answers (a frozen S3)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.conns = []
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                c, _ = self.sock.accept()
                self.conns.append(c)
            except OSError:
                return

    def close(self):
        self._stop = True
        for c in self.conns:
            c.close()
        self.sock.close()


@pytest.fixture
def frozen_s3(monkeypatch, tmp_path):
    hole = _BlackHole()
    monkeypatch.setenv("S3_BUCKET", "frozen")
    monkeypatch.setenv("S3_ENDPOINT_URL", f"http://127.0.0.1:{hole.port}")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("S3_READ_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("S3_CONNECT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("S3_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("S3_CIRCUIT_SECONDS", "30")
    monkeypatch.setenv("S3_HEALTH_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("S3_HEALTH_CACHE_SECONDS", "0.1")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    from core.storage import S3CompatibleStorageProvider

    provider = S3CompatibleStorageProvider(local_cache_dir=tmp_path)
    provider._bucket_checked = True
    yield provider
    hole.close()


def test_frozen_object_store_fails_fast_with_storage_unavailable(frozen_s3):
    from core.storage import StorageUnavailableError

    t = time.monotonic()
    with pytest.raises(StorageUnavailableError):
        frozen_s3.get_object("workspace/w/datasets/d/x.parquet")
    assert time.monotonic() - t < 8  # was ~120 s (botocore 60 s defaults, retried)
    # Circuit open: further calls (incl. s3transfer uploads/downloads) fail immediately.
    t = time.monotonic()
    with pytest.raises(StorageUnavailableError):
        frozen_s3.put_object("workspace/w/datasets/d/y.bin", b"abc")
    with pytest.raises(StorageUnavailableError):
        frozen_s3.download_object("workspace/w/datasets/d/x.parquet", Path(frozen_s3.local_cache_dir) / "x")
    assert time.monotonic() - t < 1
    t = time.monotonic()
    ok, detail = frozen_s3.health_check()
    assert ok is False and "frozen" not in detail
    assert time.monotonic() - t < 4


def test_readiness_reports_storage_down_quickly(frozen_s3, monkeypatch):
    import core.storage as storage

    monkeypatch.setattr(storage, "_storage_provider", frozen_s3)
    t = time.monotonic()
    r = _client().get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["storage"] is False
    assert time.monotonic() - t < 5


def test_storage_outage_on_api_request_returns_503_with_request_id(frozen_s3, monkeypatch):
    import core.storage as storage
    from core.file_manager import get_file_manager

    owner = _make_user()
    client = _client()
    up = _upload(client, owner["headers"], b"a,b\n1,2\n")
    manager = get_file_manager()
    monkeypatch.setattr(storage, "_storage_provider", frozen_s3)
    with patch.object(type(manager), "get_preview_data", side_effect=storage.StorageUnavailableError("x")):
        r = client.get(f"/files/{up['file_id']}", headers=owner["headers"])
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["code"] == "STORAGE_UNAVAILABLE" and body["request_id"]
    assert r.headers["X-Request-ID"] == body["request_id"] and r.headers.get("Retry-After")
    assert "127.0.0.1" not in r.text and "frozen" not in r.text


# ─────────────────────────────────────────────────────────────────────────────
# 7. Job recovery
# ─────────────────────────────────────────────────────────────────────────────

def _insert_job(status="running", heartbeat_age=0, attempts=1, max_attempts=3, owner="w-old", job_type="noop_test"):
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        jid = str(uuid.uuid4())
        db.add(Job(id=jid, job_type=job_type, status=status, payload_json="{}", attempts=attempts,
                   max_attempts=max_attempts, locked_by=owner, heartbeat_at=now - datetime.timedelta(seconds=heartbeat_age),
                   created_at=now, updated_at=now, run_after=now))
        db.commit()
        return jid
    finally:
        db.close()


def _job(jid):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == jid).first()
    finally:
        db.close()


def test_visibility_timeout_default_is_90s(monkeypatch):
    monkeypatch.delenv("JOB_VISIBILITY_TIMEOUT_SECONDS", raising=False)
    fresh = _insert_job(heartbeat_age=60)
    stale = _insert_job(heartbeat_age=100)
    jobs.requeue_stale()
    assert _job(fresh).status == "running"
    assert _job(stale).status == "queued" and _job(stale).locked_by is None


def test_presumed_dead_worker_cannot_overwrite_newer_attempt():
    calls = []
    release = threading.Event()

    @jobs.register("fence_test")
    def _handler(payload, ctx):
        calls.append(ctx.attempt)
        if ctx.attempt == 1:
            release.wait(10)  # the "frozen" first worker
            return {"who": "old"}
        return {"who": "new"}

    jid = _insert_job(status="queued", attempts=0, owner=None, job_type="fence_test")
    assert jobs._claim_specific(jid, "worker-A")
    out_a = {}
    t = threading.Thread(target=lambda: out_a.update(jobs.run_claimed(jid)))
    t.start()
    time.sleep(0.3)
    # Worker A is presumed dead: its lease expires and worker B re-runs the job.
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.id == jid).update({Job.status: "queued", Job.locked_by: None})
        db.commit()
    finally:
        db.close()
    assert jobs._claim_specific(jid, "worker-B")
    out_b = jobs.run_claimed(jid)
    release.set()
    t.join(15)
    assert out_b["status"] == "succeeded"
    assert out_a["status"] == "lease_lost"
    final = _job(jid)
    assert final.status == "succeeded" and json.loads(final.result_json) == {"who": "new"}
    assert calls == [1, 2]


# ─────────────────────────────────────────────────────────────────────────────
# 8. Refresh-token rotation is atomic
# ─────────────────────────────────────────────────────────────────────────────

def test_simultaneous_refreshes_only_one_succeeds():
    client = _client()
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/signup", json={"email": email, "password": "SecurePassword123!"})
    refresh = client.post("/auth/login", json={"email": email, "password": "SecurePassword123!"}).json()["refresh_token"]
    barrier = threading.Barrier(8)
    codes: list[int] = []
    tokens: list[str] = []

    def go():
        c = TestClient(main.app)
        barrier.wait()
        r = c.post("/auth/refresh", json={"refresh_token": refresh})
        codes.append(r.status_code)
        if r.status_code == 200:
            tokens.append(r.json()["refresh_token"])

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert codes.count(200) == 1, codes
    assert set(codes) <= {200, 409}, codes
    db = SessionLocal()
    try:
        old = db.query(RefreshToken).filter(RefreshToken.token_hash == hashlib.sha256(refresh.encode()).hexdigest()).first()
        if old is not None:
            assert old.revoked
        from core.auth import hash_token

        live = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(tokens[0])).first()
        assert live is not None and not live.revoked
        user_id = live.user_id
        # Exactly one new live token was issued for this login (no duplicate sessions).
        assert db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked == False).count() == 1  # noqa: E712
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# 9. AI quota is not consumed when no result is produced
# ─────────────────────────────────────────────────────────────────────────────

def _query_count(ws):
    from core.usage import _usage_row_id

    db = SessionLocal()
    try:
        row = db.query(UsageStats).filter(UsageStats.id == _usage_row_id(ws, db)).first()
        return row.query_count if row else 0
    finally:
        db.close()


def test_agent_timeout_does_not_consume_query_quota(monkeypatch):
    from agents.base_agent import BaseAgent

    class SlowLLM(FakeLLM):
        async def generate(self, *a, **k):
            await asyncio.sleep(5)
            return await super().generate(*a, **k)

    client = _client()
    owner = _make_user()
    up = _upload(client, owner["headers"], b"region,revenue\nN,10\nS,20\n")
    monkeypatch.setattr(BaseAgent, "timeout_seconds", 0.3)
    before = _query_count(owner["workspace_id"])
    with patch.object(main, "build_client", lambda settings, cb=None: SlowLLM()):
        resp = client.post("/chat/stream", headers=owner["headers"],
                           json={"message": "total revenue by region", "file_ids": [up["file_id"]]})
    finals = [e for e in _sse_events(resp.text) if e.get("is_final")]
    assert len(finals) == 1 and finals[0]["type"] == "error", finals
    assert "no_result" not in finals[0]["metadata"]
    assert _query_count(owner["workspace_id"]) == before

    # A successful answer is still billed exactly once.
    with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
        monkeypatch.setattr(BaseAgent, "timeout_seconds", 30)
        ok = client.post("/chat/stream", headers=owner["headers"],
                         json={"message": "total revenue by region", "file_ids": [up["file_id"]]})
    final = [e for e in _sse_events(ok.text) if e.get("is_final")][0]
    assert final["type"] != "error", final
    assert _query_count(owner["workspace_id"]) == before + 1


def test_heavy_job_that_never_finishes_does_not_bill(monkeypatch):
    client = _client()
    owner = _make_user(plan="pro")
    up = _upload(client, owner["headers"], b"month,revenue\n2024-01,10\n2024-02,20\n2024-03,30\n")
    before = _query_count(owner["workspace_id"])
    monkeypatch.setattr(jobs, "execution_mode", lambda: "worker")
    monkeypatch.setenv("AGENT_JOB_WAIT_SECONDS", "1")
    with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
        resp = client.post("/chat/stream", headers=owner["headers"],
                           json={"message": "forecast revenue for the next 3 months", "file_ids": [up["file_id"]]})
    finals = [e for e in _sse_events(resp.text) if e.get("is_final")]
    assert len(finals) == 1 and finals[0]["type"] == "error", finals
    assert _query_count(owner["workspace_id"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# 10. Infrastructure errors
# ─────────────────────────────────────────────────────────────────────────────

def _route_raising(exc: Exception) -> str:
    path = f"/__raise_{uuid.uuid4().hex[:8]}"

    @main.app.get(path)
    def _boom():
        raise exc

    return path


@pytest.mark.parametrize("exc,status,code", [
    (__import__("sqlalchemy").exc.OperationalError("SELECT 1", {}, Exception("could not connect to pg-internal:5434")),
     503, "DATABASE_UNAVAILABLE"),
    (__import__("sqlalchemy").exc.TimeoutError("QueuePool limit of size 10 overflow 10 reached"), 503, "DATABASE_UNAVAILABLE"),
    (stripe.error.APIConnectionError("Could not connect to api.stripe.com secret sk_live_x"), 502, "BILLING_PROVIDER_UNAVAILABLE"),
])
def test_infrastructure_failures_map_to_502_503_without_internals(exc, status, code):
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get(_route_raising(exc), headers={"X-Request-ID": "req-abc-123"})
    assert r.status_code == status, r.text
    body = r.json()
    assert body["code"] == code and body["request_id"] == "req-abc-123"
    assert r.headers["X-Request-ID"] == "req-abc-123"
    for leak in ("pg-internal", "QueuePool", "sk_live", "api.stripe.com", "Traceback"):
        assert leak not in r.text


def test_unhandled_500_has_request_id_and_no_exception_text(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("APP_ENV", "production")  # DEBUG must never leak details in production
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get(_route_raising(RuntimeError("secret internal detail /etc/passwd")))
    assert r.status_code == 500
    body = r.json()
    assert body["request_id"] and r.headers.get("X-Request-ID") == body["request_id"]
    assert "secret internal detail" not in r.text


def test_storage_health_is_live_and_honours_bucket_auto_create(monkeypatch, tmp_path):
    moto = pytest.importorskip("moto")
    monkeypatch.setenv("S3_BUCKET", "auto-created")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("S3_HEALTH_CACHE_SECONDS", "0.1")
    with moto.mock_aws():
        from core.storage import S3CompatibleStorageProvider

        monkeypatch.setenv("S3_CREATE_BUCKET", "false")
        missing = S3CompatibleStorageProvider(local_cache_dir=tmp_path)
        assert missing.health_check()[0] is False  # bucket missing and no auto-create
        monkeypatch.setenv("S3_CREATE_BUCKET", "true")
        provider = S3CompatibleStorageProvider(local_cache_dir=tmp_path)
        assert provider.health_check() == (True, "s3:auto-created")
        provider.put_object("workspace/w/x.txt", b"ok")
        assert provider.get_object("workspace/w/x.txt") == b"ok"


def test_ai_token_metering_never_blocks_the_event_loop():
    """The metering callback writes to the DB; on the event loop it froze a whole API
    process for DB_POOL_TIMEOUT_SECONDS whenever the pool was busy (250-user staging run)."""
    from core.llm_client import LLMSettings, build_client

    seen = {}

    def slow_cb(provider, tokens):
        seen["thread"] = threading.current_thread()
        time.sleep(0.5)
        seen["tokens"] = tokens

    client = build_client(LLMSettings(provider="gemini", api_key="k"), slow_cb)

    async def run():
        loop_thread = threading.current_thread()
        t = time.monotonic()
        client._record_usage(123)
        blocked = time.monotonic() - t
        await asyncio.sleep(0.8)
        return loop_thread, blocked

    loop_thread, blocked = asyncio.run(run())
    assert blocked < 0.1, blocked
    assert seen["tokens"] == 123 and seen["thread"] is not loop_thread


def test_transform_preview_releases_connection_before_ai_call(monkeypatch):
    import core.transform_engine as te

    client = _client()
    owner = _make_user()
    up = _upload(client, owner["headers"], b"region,revenue\nN,10\nS,20\n")
    seen = []

    async def fake_propose(query, df, table, llm=None):
        seen.append(_checked_out())
        return [{"action": "filter_rows", "column": "revenue", "operator": ">", "value": "5"}]

    monkeypatch.setattr(te, "propose_transformations", fake_propose)
    with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
        r = client.post(f"/files/{up['file_id']}/transform/preview", headers=owner["headers"],
                        json={"query": "keep revenue above 5"})
    assert r.status_code == 200, r.text
    assert seen == [0], seen


def test_async_routes_never_hand_an_open_transaction_back_to_the_event_loop(monkeypatch):
    """Under load every threadpool token can be held by threads blocked on pool
    checkout.  A request that returns to the event loop while still holding a
    connection, and needs another threadpool call to release it, then deadlocks the
    process until DB_POOL_TIMEOUT_SECONDS (observed at 500 users on staging).
    Every threadpool step of the async routes must therefore return with no
    connection checked out."""
    real = main.run_in_threadpool
    after: list[tuple[str, int]] = []

    async def spy(fn, *args, **kwargs):
        try:
            return await real(fn, *args, **kwargs)
        finally:
            after.append((getattr(fn, "__name__", str(fn)), _checked_out()))

    monkeypatch.setattr(main, "run_in_threadpool", spy)
    client = _client()
    owner = _make_user()
    up = _upload(client, owner["headers"], b"region,revenue\nN,10\nS,20\n")
    with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
        chat = client.post("/chat/stream", headers=owner["headers"],
                           json={"message": "total revenue by region", "file_ids": [up["file_id"]]})
        assert chat.status_code == 200
        import core.transform_engine as te

        async def fake_propose(query, df, table, llm=None):
            return [{"action": "filter_rows", "column": "revenue", "operator": ">", "value": "5"}]

        monkeypatch.setattr(te, "propose_transformations", fake_propose)
        tp = client.post(f"/files/{up['file_id']}/transform/preview", headers=owner["headers"],
                         json={"query": "keep revenue above 5"})
        assert tp.status_code == 200, tp.text
    names = {n for n, _ in after}
    assert {"_prepare", "_stage_released", "_audit_and_release", "_llm_released"} <= names, names
    assert all(n == 0 for _, n in after), after


def test_local_env_file_is_loaded_before_config_and_never_overrides(monkeypatch, tmp_path):
    """`python main.py` must read backend/.env (JWT_SECRET is checked at import time);
    real environment variables always win."""
    import core.env_file as env_file

    f = tmp_path / ".env"
    f.write_text("DP_TEST_FROM_FILE=file\r\nDP_TEST_PRESET=file\r\n")
    monkeypatch.setattr(env_file, "ENV_FILE", f)
    monkeypatch.delenv("DP_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("DP_TEST_PRESET", "real")
    assert env_file.load_local_env() is True
    assert os.environ["DP_TEST_FROM_FILE"] == "file"
    assert os.environ["DP_TEST_PRESET"] == "real"
    monkeypatch.delenv("DP_TEST_FROM_FILE")
    src = (BACKEND / "main.py").read_text()
    assert src.index("load_local_env()") < src.index("from core.request_identity")
    assert "load_local_env()" in (BACKEND / "worker.py").read_text()


def test_startup_recovers_from_interrupted_sqlite_batch_migration(monkeypatch, tmp_path):
    """A killed SQLite batch migration leaves `_alembic_tmp_<table>`; every later
    start then failed with "table ... already exists" and the API never came up."""
    from sqlalchemy import create_engine, inspect, text as sa_text

    import core.db as dbmod

    eng = create_engine(f"sqlite:///{tmp_path / 'leftover.db'}")
    with eng.begin() as c:
        c.execute(sa_text("CREATE TABLE dataset_registry (dataset_id TEXT PRIMARY KEY)"))
        c.execute(sa_text("INSERT INTO dataset_registry VALUES ('keep')"))
        c.execute(sa_text("CREATE TABLE _alembic_tmp_dataset_registry (dataset_id TEXT)"))
        c.execute(sa_text("CREATE TABLE _alembic_tmp_orphan (x TEXT)"))
    monkeypatch.setattr(dbmod, "engine", eng)
    monkeypatch.setattr(dbmod, "DATABASE_URL", str(eng.url))
    with pytest.raises(RuntimeError, match="_alembic_tmp_orphan"):
        dbmod._drop_stale_alembic_tmp_tables(inspect(eng).get_table_names())
    with eng.begin() as c:
        c.execute(sa_text("DROP TABLE _alembic_tmp_orphan"))
    dbmod._drop_stale_alembic_tmp_tables(inspect(eng).get_table_names())
    names = inspect(eng).get_table_names()
    assert "_alembic_tmp_dataset_registry" not in names and "dataset_registry" in names
    with eng.connect() as c:
        assert c.execute(sa_text("SELECT dataset_id FROM dataset_registry")).scalar() == "keep"
