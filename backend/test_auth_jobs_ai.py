"""
test_auth_jobs_ai.py — session security, durable jobs, AI correctness helpers.
"""

import datetime
import os
import uuid

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from main import app
from core.auth import hash_password
from core.db import SessionLocal
from core.models import Job, OAuthIdentity, PasswordResetToken, RefreshToken, User
from core.auth import hash_token


def _register(client, email=None, password="SecurePassword123!"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return email, r.json()


# ── OAuth account linking ─────────────────────────────────────────────────────

def test_microsoft_oauth_cannot_take_over_existing_password_account():
    from core.auth_routes import _social_user_from_profile
    from fastapi import HTTPException

    client = TestClient(app)
    email, _ = _register(client)
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            _social_user_from_profile("microsoft", {"sub": "attacker-oid", "preferred_username": email}, db)
        assert exc.value.status_code == 409
        db.rollback()
        # Google with a verified email may link, and is then linked by subject id.
        user = _social_user_from_profile("google", {"sub": "g-1-" + email, "email": email, "email_verified": True}, db)
        db.commit()
        assert user.email == email
        assert db.query(OAuthIdentity).filter(OAuthIdentity.subject == "g-1-" + email).count() == 1
        with pytest.raises(HTTPException):
            _social_user_from_profile("google", {"sub": "g-2", "email": "other@example.com"}, db)  # unverified
    finally:
        db.close()


# ── Refresh tokens / password reset ───────────────────────────────────────────

def test_refresh_cookie_rotation_workspace_preservation_and_reuse_detection():
    client = TestClient(app)
    email, signup = _register(client)
    login = client.post("/auth/login", json={"email": email, "password": "SecurePassword123!"})
    assert login.status_code == 200
    assert "dp_refresh" in login.cookies
    cookie = login.cookies["dp_refresh"]
    second_ws = client.post("/workspaces", json={"name": "Second"},
                            headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    # Free plan allows one owned workspace: creation is blocked by the plan limit.
    assert second_ws.status_code == 429

    refreshed = client.post("/auth/refresh", json={"workspace_id": signup["workspace_id"]})  # cookie-based
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["workspace_id"] == signup["workspace_id"]

    # An immediate replay (two tabs refreshing at once) is a benign race: 409, no revocation.
    client.cookies.clear()
    race = client.post("/auth/refresh", json={"refresh_token": cookie})
    assert race.status_code == 409, race.text
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert db.query(RefreshToken).filter(RefreshToken.user_id == user.user_id, RefreshToken.revoked == False).count() > 0  # noqa: E712
        entry = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(cookie)).first()
        entry.rotated_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    # Replaying the already-rotated token after the grace window revokes every session of that user.
    replay = client.post("/auth/refresh", json={"refresh_token": cookie})
    assert replay.status_code == 401
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert db.query(RefreshToken).filter(RefreshToken.user_id == user.user_id, RefreshToken.revoked == False).count() == 0  # noqa: E712
    finally:
        db.close()


def test_password_reset_revokes_sessions():
    client = TestClient(app)
    email, _ = _register(client)
    login = client.post("/auth/login", json={"email": email, "password": "SecurePassword123!"}).json()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        raw = uuid.uuid4().hex
        db.add(PasswordResetToken(id=str(uuid.uuid4()), user_id=user.user_id, token_hash=hash_token(raw),
                                  expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1)))
        db.commit()
    finally:
        db.close()
    assert client.post("/auth/reset-password", json={"token": raw, "new_password": "AnotherPassword456!"}).status_code == 200
    client.cookies.clear()
    assert client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401
    assert client.post("/auth/reset-password", json={"token": raw, "new_password": "ThirdPassword789!"}).status_code == 400


def test_inactive_user_cannot_log_in():
    client = TestClient(app)
    email, _ = _register(client)
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == email).update({User.is_active: False})
        db.commit()
    finally:
        db.close()
    assert client.post("/auth/login", json={"email": email, "password": "SecurePassword123!"}).status_code == 401


# ── Durable jobs ──────────────────────────────────────────────────────────────

def test_jobs_claim_once_and_recover_from_dead_workers():
    from core import jobs

    db = SessionLocal()
    try:  # isolate from queued jobs left by other tests
        db.query(Job).filter(Job.job_type == "workspace_cleanup", Job.status == "queued").delete()
        db.commit()
    finally:
        db.close()
    job_id = jobs.enqueue("workspace_cleanup", {"workspace_id": f"none-{uuid.uuid4().hex}"}, workspace_id="wsx",
                          user_id=None, max_attempts=2)
    claimed = jobs.claim_next("worker-a", ["workspace_cleanup"])
    assert claimed == job_id
    assert jobs.claim_next("worker-b", ["workspace_cleanup"]) is None  # never double-claimed

    # Simulate a crashed worker: stale heartbeat → job is re-queued and can be re-claimed.
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.id == job_id).update({Job.heartbeat_at: datetime.datetime.utcnow() - datetime.timedelta(hours=1)})
        db.commit()
    finally:
        db.close()
    assert jobs.requeue_stale(60) >= 1
    assert jobs.claim_next("worker-b", ["workspace_cleanup"]) == job_id
    out = jobs.run_claimed(job_id)
    assert out["status"] == "succeeded"
    assert jobs.get_job(job_id)["status"] == "succeeded"


def test_job_status_is_workspace_scoped():
    from core import jobs

    job_id = jobs.enqueue("workspace_cleanup", {"workspace_id": "x"}, workspace_id="ws-owner", user_id=None)
    assert jobs.get_job(job_id, "ws-owner") is not None
    assert jobs.get_job(job_id, "ws-other") is None


# ── AI correctness helpers ────────────────────────────────────────────────────

@pytest.mark.parametrize("message,intent", [
    ("show the table of top products", "insight"),          # "table" must not match "tab"
    ("what is our budget by region", "insight"),            # "budget" must not match "get"
    ("list withdrawals by month", "insight"),               # "withdrawal" must not match "draw"
    ("plot revenue trend", "visualize"),
    ("forecast revenue for next quarter", "forecast"),
    ("how many sheets does this workbook have", "summary"),
    ("remove duplicates", "clean"),
])
def test_intent_routing_uses_word_boundaries(message, intent):
    from core.router import _keyword_match

    assert _keyword_match(message) == intent


def test_forecast_requires_explicit_target_and_parses_horizon():
    from agents.forecast_agent import horizon_in_periods, parse_horizon, run_forecast

    dates = pd.date_range("2021-01-01", "2024-06-15", freq="D")
    df = pd.DataFrame({"customer_id": range(len(dates)), "zip_code": np.random.randint(10000, 99999, len(dates)),
                       "date": dates.astype(str), "revenue": np.random.rand(len(dates)) * 100,
                       "units": np.random.randint(1, 9, len(dates))})
    assert "Which column" in run_forecast(df, "forecast next quarter", None, "f", "s")["error"]
    out = run_forecast(df, "forecast revenue for the next 2 years", None, "f", "s")
    assert out["metadata"]["value_column"] == "revenue"
    assert out["metadata"]["n_periods"] == 24
    assert "incomplete" in out["content"]
    assert parse_horizon("next year") == (1, "year") and horizon_in_periods(1, "year", "M") == 12
    no_date = run_forecast(pd.DataFrame({"revenue": range(30)}), "forecast revenue", None, "f", "s")
    assert "date" in no_date["error"]


def test_parsing_encoding_delimiter_header_and_identifier_columns(tmp_path):
    from core.parsing import parse_file

    p = tmp_path / "w.csv"
    p.write_bytes("name\tzip\tprice\nCaf\xe9\t01234\t€1.234,50\nB\t02345\t€10,00\n".encode("cp1252"))
    df, meta = parse_file(p, ".csv")
    assert meta["delimiter"] == "\t" and meta["encoding"] == "cp1252"
    assert df["name"][0] == "Café"
    assert df["zip"].dtype == object and df["zip"][0] == "01234"  # leading zeros preserved
    assert df["price"].tolist() == [1234.5, 10.0]

    x = tmp_path / "t.xlsx"
    with pd.ExcelWriter(x) as w:
        pd.DataFrame([["Quarterly report", None], [None, None], ["region", "sales"], ["N", 5], ["S", 7]]).to_excel(
            w, index=False, header=False, sheet_name="Data")
    df, meta = parse_file(x, ".xlsx")
    assert list(df.columns) == ["region", "sales"] and df["sales"].sum() == 12


def test_transforms_do_not_corrupt_missing_values():
    from core.transform_engine import execute_transform

    df = pd.DataFrame({"n": ["1", None, "x"], "t": [" a", None, "b "]})
    as_int = execute_transform(df, {"action": "convert_type", "column": "n", "target_type": "int"})
    assert as_int["n"].isna().sum() == 2  # not silently 0
    normalized = execute_transform(df, {"action": "normalize_text", "column": "t", "strategy": "strip"})
    assert normalized["t"].isna().sum() == 1 and "nan" not in normalized["t"].astype(str).tolist()


def test_stale_stripe_events_cannot_reactivate_cancelled_subscription():
    from core.stripe_billing import process_subscription_object
    from core.models import Subscription, Workspace

    db = SessionLocal()
    ws = str(uuid.uuid4())
    sub_id = f"sub_{uuid.uuid4().hex[:10]}"
    try:
        db.add(Workspace(workspace_id=ws, name="S", plan_tier="free"))
        db.commit()
        base = {"id": sub_id, "customer": "cus_x", "metadata": {"workspace_id": ws, "plan_id": "pro"},
                "current_period_start": 1700000000, "current_period_end": 1702600000}
        process_subscription_object({**base, "status": "canceled"}, db, "customer.subscription.deleted", event_created=200)
        result = process_subscription_object({**base, "status": "active"}, db, "customer.subscription.updated", event_created=100)
        assert result["reason"] == "stale_event"
        assert db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first().status == "canceled"
    finally:
        db.close()


def test_production_env_validation():
    from scripts.validate_env import validate

    errs = validate({"APP_ENV": "production", "AI_PROVIDER": "gemini", "JOB_EXECUTION_MODE": "inline"})
    joined = " ".join(errs)
    assert "LLM_PROVIDER" in joined and "ENCRYPTION_KEY" in joined and "JOB_EXECUTION_MODE" in joined


def test_complete_production_env_passes_and_email_tokens_never_logged(caplog, monkeypatch):
    from scripts.validate_env import validate

    env = {
        "APP_ENV": "production", "JWT_SECRET": "a" * 64,
        "DATABASE_URL": "postgresql+psycopg2://u:p@postgres:5432/datapilot",
        "ALLOWED_ORIGINS": "https://app.datapilot.test", "REDIS_URL": "rediss://redis.internal:6379/0",
        "RATE_LIMITER_BACKEND": "redis", "STORAGE_PROVIDER": "s3", "S3_BUCKET": "dp",
        "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "ENCRYPTION_KEY": "x" * 44,
        "JOB_EXECUTION_MODE": "worker", "STRIPE_BILLING_ENABLED": "false", "SMTP_HOST": "smtp.internal",
    }
    assert validate(env) == []
    assert any("SMTP_HOST" in e for e in validate({**env, "SMTP_HOST": ""}))

    # Without SMTP in production, a password-reset email is refused rather than logged.
    import core.email_service as email_service

    monkeypatch.setattr(email_service, "EMAIL_DEV_MODE", True)
    monkeypatch.setenv("APP_ENV", "production")
    with caplog.at_level("INFO"):
        assert email_service.send_password_reset_email("x@example.com", "X", "SECRET-RESET-TOKEN") is False
    assert "SECRET-RESET-TOKEN" not in caplog.text
