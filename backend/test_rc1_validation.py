"""Quick RC-1 validation test suite — runs against live server at 127.0.0.1:8001"""
import sys
import io
import urllib.request
import urllib.error
import json

# Force UTF-8 on stdout to avoid Windows cp1252 issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8001"

def get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, {"error": str(e)}

def post(path, body=None, headers=None):
    data = json.dumps(body or {}).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, {"error": str(e)}

tests = []

def check(name, code, body, expected_code):
    passed = code == expected_code
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}: HTTP {code} (expected {expected_code})")
    if not passed:
        print(f"       Body: {body}")
    tests.append(passed)

print("\n=== DataPilot RC-1 Quick Validation ===\n")

# Health
code, body = get("/health")
check("GET /health", code, body, 200)

# /files without auth should 401
code, body = get("/files")
check("GET /files (unauthenticated) -> 401", code, body, 401)

# /files DELETE without auth should 401
req = urllib.request.Request(BASE + "/files/test123", method="DELETE")
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        check("DELETE /files/{id} (unauthenticated) -> 401", r.status, {}, 401)
except urllib.error.HTTPError as e:
    check("DELETE /files/{id} (unauthenticated) -> 401", e.code, {}, 401)

# /provider POST without auth should 401
code, body = post("/provider", {"provider": "gemini"})
check("POST /provider (unauthenticated) -> 401", code, body, 401)

# Signup with weak password (< 8 chars) should 422
code, body = post("/auth/signup", {"email": "test@example.com", "password": "abc"})
check("POST /auth/signup (weak password) -> 422", code, body, 422)

# Signup with valid password should either 201 or 409 (already exists)
code, body = post("/auth/signup", {"email": "rc1test@datapilot.test", "password": "TestPass123!"})
expected_code = 201 if code == 201 else 409
check("POST /auth/signup (valid password) -> 201 or 409", code, body, expected_code)

# /auth/login with wrong password should 401
code, body = post("/auth/login", {"email": "rc1test@datapilot.test", "password": "wrongpassword"})
check("POST /auth/login (wrong password) -> 401", code, body, 401)

print()
print(f"Results: {sum(tests)}/{len(tests)} tests passed")
if sum(tests) == len(tests):
    print("[OK] All basic RC-1 security gates are working")
else:
    print("[!!] Some tests failed — review output above")
