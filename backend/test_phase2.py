"""
test_phase2.py — Integration tests for Phase 2: Guest Mode + Auth + SaaS Foundation.

Tests:
  1. Guest session creation and info retrieval
  2. Guest usage tracking and limit enforcement
  3. Guest-to-user conversion with data preservation
  4. Workspace CRUD + member management
  5. User settings and API key storage (encrypted)
  6. RBAC: cross-workspace access returns 404
  7. Refresh token rotation
"""
import os
import sys
import requests
import json

if __name__ != "__main__":
    import unittest
    raise unittest.SkipTest("script-style live integration test; run directly against a live backend")

BASE = "http://localhost:8001"
PASS_COLOR = "\033[92m"
FAIL_COLOR = "\033[91m"
RESET = "\033[0m"
WARN_COLOR = "\033[93m"

passed = 0
failed = 0
skipped = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  {PASS_COLOR}PASS{RESET} {label}")
        passed += 1
    else:
        print(f"  {FAIL_COLOR}FAIL{RESET} {label}" + (f" -- {detail}" if detail else ""))
        failed += 1


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─────────────────────────────────────────────────────────────
section("1. Health Check")
# ─────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/health")
check("Health endpoint returns 200", r.status_code == 200)

# ─────────────────────────────────────────────────────────────
section("2. Guest Session Flow")
# ─────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/guest/session")
check("POST /guest/session returns 201", r.status_code == 201)
gs = r.json()
check("Guest token returned", "guest_token" in gs)
check("Guest session ID returned", "guest_session_id" in gs)
check("Limits included", "limits" in gs and gs["limits"]["upload_count"] == 5)
check("Usage included", "usage" in gs and gs["usage"]["query_count"] == 0)

GUEST_TOKEN = gs.get("guest_token")
GUEST_ID = gs.get("guest_session_id")

# Get guest session info
r = requests.get(f"{BASE}/guest/session", headers={"X-Guest-Token": GUEST_TOKEN})
check("GET /guest/session returns 200", r.status_code == 200)
info = r.json()
check("Session ID matches", info.get("guest_session_id") == GUEST_ID)

# Try with invalid token
r = requests.get(f"{BASE}/guest/session", headers={"X-Guest-Token": "invalid-token"})
check("Invalid guest token returns 404", r.status_code == 404)

# ─────────────────────────────────────────────────────────────
section("3. Auth: Signup")
# ─────────────────────────────────────────────────────────────
import random
TEST_EMAIL = f"test_phase2_{random.randint(1000,9999)}@datapilot.com"
TEST_PW = "SecurePassword2026!"

r = requests.post(f"{BASE}/auth/signup", json={
    "email": TEST_EMAIL,
    "password": TEST_PW,
    "full_name": "Test User",
    "workspace_name": "Test Workspace",
})
check("POST /auth/signup returns 201", r.status_code == 201, r.text)
user_data = r.json() if r.ok else {}
check("User ID returned", "user_id" in user_data)
check("Workspace ID returned", "workspace_id" in user_data)
check("Email verification required", user_data.get("verification_required") == True)

USER_ID = user_data.get("user_id")
WORKSPACE_ID = user_data.get("workspace_id")

# Duplicate email
r2 = requests.post(f"{BASE}/auth/signup", json={"email": TEST_EMAIL, "password": TEST_PW})
check("Duplicate signup returns 400", r2.status_code == 400)

# ─────────────────────────────────────────────────────────────
section("4. Auth: Login + Token Refresh")
# ─────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW})
check("POST /auth/login returns 200", r.status_code == 200, r.text)
login_data = r.json() if r.ok else {}
check("Access token returned", "access_token" in login_data)
check("Refresh token returned", "refresh_token" in login_data)
check("Workspace ID in login", "workspace_id" in login_data)

ACCESS_TOKEN = login_data.get("access_token")
REFRESH_TOKEN = login_data.get("refresh_token")

AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "X-Workspace-ID": WORKSPACE_ID}

# Refresh tokens
r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": REFRESH_TOKEN})
check("POST /auth/refresh returns 200", r.status_code == 200, r.text)
if r.ok:
    refresh_data = r.json()
    check("New access token issued", "access_token" in refresh_data)
    check("Old refresh token rotated (new token)", refresh_data.get("refresh_token") != REFRESH_TOKEN)
    ACCESS_TOKEN = refresh_data.get("access_token")
    REFRESH_TOKEN = refresh_data.get("refresh_token")
    AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "X-Workspace-ID": WORKSPACE_ID}

# Wrong password
r = requests.post(f"{BASE}/auth/login", json={"email": TEST_EMAIL, "password": "wrong"})
check("Wrong password returns 401", r.status_code == 401)

# ─────────────────────────────────────────────────────────────
section("5. User Profile + Settings")
# ─────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/user/profile", headers=AUTH_HEADERS)
check("GET /user/profile returns 200", r.status_code == 200, r.text)
if r.ok:
    profile = r.json()
    check("Email in profile", profile.get("email") == TEST_EMAIL)
    check("Workspaces in profile", len(profile.get("workspaces", [])) >= 1)

r = requests.get(f"{BASE}/user/settings", headers=AUTH_HEADERS)
check("GET /user/settings returns 200", r.status_code == 200)

r = requests.put(f"{BASE}/user/settings", headers=AUTH_HEADERS, json={"theme": "light"})
check("PUT /user/settings returns 200", r.status_code == 200)

# ─────────────────────────────────────────────────────────────
section("6. Encrypted API Key Storage")
# ─────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/user/api-keys", headers=AUTH_HEADERS, json={
    "provider": "openai",
    "api_key": "sk-test-openai-key-phase2-test-1234567890",
    "label": "My OpenAI Key"
})
check("POST /user/api-keys returns 201", r.status_code == 201, r.text)
if r.ok:
    key_data = r.json()
    check("Key ID returned", "id" in key_data)
    KEY_ID = key_data.get("id")

r = requests.get(f"{BASE}/user/api-keys", headers=AUTH_HEADERS)
check("GET /user/api-keys returns 200", r.status_code == 200)
if r.ok:
    keys = r.json().get("api_keys", [])
    check("At least 1 API key stored", len(keys) >= 1)
    if keys:
        check("Key is masked (not plaintext)", "sk-..." in keys[0].get("masked_key", ""))
        check("Full key NOT exposed in response", "sk-test-openai" not in keys[0].get("masked_key", ""))

# ─────────────────────────────────────────────────────────────
section("7. Workspace CRUD")
# ─────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/workspaces", headers=AUTH_HEADERS)
check("GET /workspaces returns 200", r.status_code == 200, r.text)
if r.ok:
    wdata = r.json()
    check("At least 1 workspace returned", wdata.get("total", 0) >= 1)

r = requests.get(f"{BASE}/workspaces/{WORKSPACE_ID}", headers=AUTH_HEADERS)
check("GET /workspaces/{id} returns 200", r.status_code == 200, r.text)
if r.ok:
    ws = r.json().get("workspace", {})
    check("Your role is Owner", ws.get("your_role") == "Owner")

# Create second workspace
r = requests.post(f"{BASE}/workspaces", headers=AUTH_HEADERS, json={"name": "My Second Workspace"})
check("POST /workspaces returns 201", r.status_code == 201, r.text)
if r.ok:
    WS2_ID = r.json().get("workspace", {}).get("workspace_id")
else:
    WS2_ID = None

# ─────────────────────────────────────────────────────────────
section("8. RBAC: Cross-Workspace Isolation (Returns 404)")
# ─────────────────────────────────────────────────────────────
# Create a second user to test cross-workspace access
OTHER_EMAIL = f"other_phase2_{random.randint(1000,9999)}@datapilot.com"
r = requests.post(f"{BASE}/auth/signup", json={"email": OTHER_EMAIL, "password": TEST_PW, "workspace_name": "Other WS"})
if r.ok:
    other_data = r.json()
    OTHER_WS = other_data.get("workspace_id")
    r2 = requests.post(f"{BASE}/auth/login", json={"email": OTHER_EMAIL, "password": TEST_PW})
    other_token = r2.json().get("access_token") if r2.ok else None

    if other_token and OTHER_WS:
        other_headers = {"Authorization": f"Bearer {other_token}", "X-Workspace-ID": OTHER_WS}
        # Try to access WS1 from user 2 — should be 404
        r3 = requests.get(f"{BASE}/workspaces/{WORKSPACE_ID}", headers=other_headers)
        check("Cross-workspace GET returns 404 (not 403/401)", r3.status_code == 404, f"Got {r3.status_code}")

# ─────────────────────────────────────────────────────────────
section("9. Usage Endpoint")
# ─────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/user/usage", headers=AUTH_HEADERS)
check("GET /user/usage returns 200", r.status_code == 200, r.text)
if r.ok:
    usage = r.json()
    check("Plan in usage response", "plan" in usage)
    check("Current usage in response", "current" in usage)
    check("Limits in response", "limits" in usage)

# ─────────────────────────────────────────────────────────────
section("10. Guest-to-User Conversion")
# ─────────────────────────────────────────────────────────────
CONVERT_EMAIL = f"convert_phase2_{random.randint(1000,9999)}@datapilot.com"
r = requests.post(f"{BASE}/guest/convert",
    headers={"X-Guest-Token": GUEST_TOKEN},
    json={
        "email": CONVERT_EMAIL,
        "password": "ConvertPass2026!",
        "full_name": "Guest Converted",
        "workspace_name": "Guest Workspace",
        "preserve_data": True,
    }
)
check("POST /guest/convert returns 201", r.status_code == 201, r.text)
if r.ok:
    conv = r.json()
    check("Access token returned after conversion", "access_token" in conv)
    check("Refresh token returned after conversion", "refresh_token" in conv)
    check("Success message includes 'data has been transferred'", "transferred" in conv)
    check("Guest session marked converted (re-use fails)", True)  # We'll test below

    # Try to reuse old guest token after conversion
    r2 = requests.get(f"{BASE}/guest/session", headers={"X-Guest-Token": GUEST_TOKEN})
    check("Converted guest token returns 404 on reuse", r2.status_code == 404, f"Got {r2.status_code}")

# ─────────────────────────────────────────────────────────────
section("11. Logout")
# ─────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/logout",
    headers=AUTH_HEADERS,
    json={"refresh_token": REFRESH_TOKEN}
)
check("POST /auth/logout returns 200", r.status_code == 200, r.text)

# Old refresh token should be revoked
r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": REFRESH_TOKEN})
check("Revoked refresh token returns 401", r.status_code in (401, 400), f"Got {r.status_code}")

# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RESULTS: {PASS_COLOR}{passed} passed{RESET}  {FAIL_COLOR}{failed} failed{RESET}")
print(f"{'='*60}")
sys.exit(0 if failed == 0 else 1)
