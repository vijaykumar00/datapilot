"""
test_cookie_session.py — browser sessions use HttpOnly cookies + double-submit CSRF.

The access token (15 min) and refresh token (7 days) are delivered only as
HttpOnly, SameSite=Strict cookies for browser sessions; JavaScript never sees
them.  Unsafe cookie-authenticated requests require X-CSRF-Token == dp_csrf.
Bearer-header API clients keep working without CSRF tokens.
"""

import io
import uuid

from fastapi.testclient import TestClient

from main import app

PASSWORD = "SecurePassword123!"
BROWSER = {"X-Session-Mode": "cookie"}
CSV = b"region,revenue\nN,10\nS,20\n"


def _set_cookie_headers(resp) -> dict[str, str]:
    out = {}
    for raw in resp.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0]
        out[name] = raw.lower()
    return out


def _browser_login(client: TestClient, email: str | None = None):
    email = email or f"cookie-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/auth/signup", json={"email": email, "password": PASSWORD}).status_code == 201
    resp = client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=BROWSER)
    assert resp.status_code == 200, resp.text
    return email, resp


def test_browser_login_sets_httponly_cookies_and_hides_tokens():
    client = TestClient(app)
    _, resp = _browser_login(client)
    body = resp.json()
    assert body["access_token"] is None and body["refresh_token"] is None
    assert body["user_id"] and body["workspace_id"]

    cookies = _set_cookie_headers(resp)
    for name in ("dp_access", "dp_refresh"):
        assert "httponly" in cookies[name], cookies[name]
        assert "samesite=strict" in cookies[name]
        assert "path=/" in cookies[name]
    assert "max-age=900" in cookies["dp_access"]  # 15-minute access token
    # The CSRF cookie must be readable by the SPA (double-submit), but is still SameSite=Strict.
    assert "httponly" not in cookies["dp_csrf"] and "samesite=strict" in cookies["dp_csrf"]


def test_api_clients_still_receive_tokens_in_the_body():
    client = TestClient(app)
    email = f"api-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    body = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert body["access_token"] and body["refresh_token"]


def test_cookie_auth_reads_but_unsafe_requests_need_csrf():
    client = TestClient(app)
    _, login = _browser_login(client)
    csrf = client.cookies["dp_csrf"]

    assert client.get("/files").status_code == 200  # safe method: cookie alone is enough

    files = {"file": ("s.csv", io.BytesIO(CSV), "text/csv")}
    blocked = client.post("/upload", files=files)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "CSRF_FAILED"

    wrong = client.post("/upload", files={"file": ("s.csv", io.BytesIO(CSV), "text/csv")},
                        headers={"X-CSRF-Token": "not-the-token"})
    assert wrong.status_code == 403

    ok = client.post("/upload", files={"file": ("s.csv", io.BytesIO(CSV), "text/csv")},
                     headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200, ok.text
    file_id = ok.json()["file_id"]
    assert client.delete(f"/files/{file_id}").status_code == 403
    assert client.delete(f"/files/{file_id}", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_bearer_api_clients_need_no_csrf_token():
    client = TestClient(app)
    email = f"bearer-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    client.cookies.clear()
    resp = client.post("/upload", headers={"Authorization": f"Bearer {token}"},
                       files={"file": ("s.csv", io.BytesIO(CSV), "text/csv")})
    assert resp.status_code == 200, resp.text


def test_cookie_session_keeps_tenant_isolation():
    a, b = TestClient(app), TestClient(app)
    _browser_login(a)
    _browser_login(b)
    up = a.post("/upload", files={"file": ("s.csv", io.BytesIO(CSV), "text/csv")},
                headers={"X-CSRF-Token": a.cookies["dp_csrf"]})
    file_id = up.json()["file_id"]
    assert b.get(f"/files/{file_id}").status_code == 404
    assert b.delete(f"/files/{file_id}", headers={"X-CSRF-Token": b.cookies["dp_csrf"]}).status_code == 404


def test_cookie_refresh_rotates_access_cookie_and_logout_clears_everything():
    client = TestClient(app)
    _browser_login(client)
    old_access = client.cookies["dp_access"]
    old_refresh = client.cookies["dp_refresh"]
    csrf = client.cookies["dp_csrf"]

    resp = client.post("/auth/refresh", json={}, headers={"X-CSRF-Token": csrf, **BROWSER})
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"] is None
    assert client.cookies["dp_refresh"] != old_refresh
    assert client.cookies["dp_access"] and old_access
    assert client.get("/files").status_code == 200

    out = client.post("/auth/logout", json={})
    assert out.status_code == 200
    cleared = _set_cookie_headers(out)
    for name in ("dp_access", "dp_refresh", "dp_csrf"):
        assert 'max-age=0' in cleared[name] or "expires=thu, 01 jan 1970" in cleared[name], cleared[name]
    assert dict(client.cookies) == {}
    assert client.get("/files").status_code == 401
    # The rotated-away refresh cookie is dead.
    client.cookies.clear()
    assert client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code in (401, 409)


def test_expired_access_cookie_is_rejected_not_downgraded_to_guest():
    client = TestClient(app)
    client.cookies.set("dp_access", "expired.or.forged")
    client.cookies.set("dp_csrf", "x" * 43)
    assert client.get("/files").status_code == 401


def test_guest_conversion_starts_a_cookie_session_without_exposing_tokens():
    client = TestClient(app)
    guest = client.post("/guest/session").json()
    up = client.post("/upload", headers={"X-Guest-Token": guest["guest_token"]},
                     files={"file": ("s.csv", io.BytesIO(CSV), "text/csv")})
    assert up.status_code == 200, up.text
    resp = client.post("/guest/convert", headers={"X-Guest-Token": guest["guest_token"], **BROWSER},
                       json={"email": f"g-{uuid.uuid4().hex[:8]}@example.com", "password": PASSWORD,
                             "preserve_data": True})
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["access_token"] is None and resp.json()["refresh_token"] is None
    assert "httponly" in _set_cookie_headers(resp)["dp_access"]
    files = client.get("/files").json()["files"]  # authenticated via the cookie
    assert any(f.get("file_id") == up.json()["file_id"] for f in files)
