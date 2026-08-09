import os
import sys
import uuid

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
from core.db import SessionLocal
from core.models import AuditLog, PhoneOtpChallenge, RefreshToken, User, Workspace, WorkspaceMember


def _cleanup_user(user_id: str | None, workspace_id: str | None, phone_number: str | None = None):
    db = SessionLocal()
    try:
        if phone_number:
            db.query(PhoneOtpChallenge).filter(PhoneOtpChallenge.phone_number == phone_number).delete()
        if user_id:
            db.query(RefreshToken).filter(RefreshToken.user_id == user_id).delete()
            db.query(AuditLog).filter(AuditLog.user_id == user_id).delete()
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete()
            db.query(User).filter(User.user_id == user_id).delete()
        if workspace_id:
            db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id).delete()
            db.query(Workspace).filter(Workspace.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def test_phone_otp_dev_flow_issues_standard_tokens(monkeypatch):
    monkeypatch.setenv("PHONE_OTP_ENABLED", "true")
    monkeypatch.setenv("PHONE_OTP_DEV_MODE", "true")
    phone_number = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    user_id = None
    workspace_id = None

    with TestClient(app) as client:
        request = client.post("/auth/otp/request", json={"phone_number": phone_number})
        assert request.status_code == 200
        payload = request.json()
        assert payload["success"] is True
        assert len(payload["dev_otp"]) == 6

        verify = client.post("/auth/otp/verify", json={
            "phone_number": phone_number,
            "code": payload["dev_otp"],
            "workspace_name": "OTP Workspace",
        })
        assert verify.status_code == 200
        tokens = verify.json()
        user_id = tokens["user_id"]
        workspace_id = tokens["workspace_id"]
        assert tokens["access_token"]
        assert tokens["refresh_token"]
        assert tokens["phone_number"] == phone_number
        assert tokens["email"].endswith("@phone.datapilot.local")

    _cleanup_user(user_id, workspace_id, phone_number)


def test_oauth_provider_start_requires_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    with TestClient(app) as client:
        response = client.post("/auth/oauth/google/start", json={
            "redirect_uri": "http://localhost:5173/auth/oauth/google/callback",
        })

    assert response.status_code == 503
    assert "Google sign-in is not configured" in response.json()["detail"]


def test_oauth_provider_start_rejects_untrusted_redirect(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("AUTH_ALLOWED_REDIRECT_ORIGINS", "http://localhost:5173")

    with TestClient(app) as client:
        response = client.post("/auth/oauth/google/start", json={
            "redirect_uri": "https://evil.example/auth/oauth/google/callback",
        })

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_oauth_provider_start_returns_authorization_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("AUTH_ALLOWED_REDIRECT_ORIGINS", "http://localhost:5173")

    with TestClient(app) as client:
        response = client.post("/auth/oauth/google/start", json={
            "redirect_uri": "http://localhost:5173/auth/oauth/google/callback",
        })

    assert response.status_code == 200
    auth_url = response.json()["authorization_url"]
    assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in auth_url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fauth%2Foauth%2Fgoogle%2Fcallback" in auth_url
