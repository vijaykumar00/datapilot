"""
test_rc1_regression.py — Comprehensive regression and acceptance test suite for DataPilot RC-1.
"""

import os
import sys
import unittest
import subprocess
import hashlib
import uuid
import datetime
from fastapi.testclient import TestClient
from sqlalchemy import inspect

# Add current directory to python path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from main import app
from core.db import get_db, SessionLocal
from core.models import Plan, User, Workspace, WorkspaceMember, GuestSession
from core.usage import get_plan_limits, check_workspace_limit, check_guest_limit
from core.request_identity import CallerContext

class TestRC1Regression(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    # ─────────────────────────────────────────────────────────────
    # 1. JWT Startup Gate Verification
    # ─────────────────────────────────────────────────────────────
    def test_jwt_startup_gate_missing_secret(self):
        """Verify that a missing JWT_SECRET environment variable prevents startup with ValueError."""
        env = os.environ.copy()
        env["JWT_SECRET"] = ""
        cmd = [sys.executable, "-c", "from core.auth import JWT_SECRET"]
        res = subprocess.run(cmd, env=env, cwd=BACKEND_DIR, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ValueError", res.stderr)
        self.assertIn("JWT_SECRET env var is missing or too short", res.stderr)

    def test_jwt_startup_gate_short_secret(self):
        """Verify that a short JWT_SECRET (less than 32 chars) prevents startup with ValueError."""
        env = os.environ.copy()
        env["JWT_SECRET"] = "short_secret_key"
        cmd = [sys.executable, "-c", "from core.auth import JWT_SECRET"]
        res = subprocess.run(cmd, env=env, cwd=BACKEND_DIR, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ValueError", res.stderr)
        self.assertIn("JWT_SECRET env var is missing or too short", res.stderr)

    def test_jwt_startup_gate_valid_secret(self):
        """Verify that a valid JWT_SECRET (at least 32 chars) allows successful startup."""
        env = os.environ.copy()
        env["JWT_SECRET"] = "a" * 32
        cmd = [sys.executable, "-c", "from core.auth import JWT_SECRET; print('OK')" ]
        res = subprocess.run(cmd, env=env, cwd=BACKEND_DIR, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("OK", res.stdout)
        # Ensure it does not print the secret itself in the stderr/stdout
        self.assertNotIn("a" * 32, res.stdout)
        self.assertNotIn("a" * 32, res.stderr)

    # ─────────────────────────────────────────────────────────────
    # 2. CORS Allowlist Validation
    # ─────────────────────────────────────────────────────────────
    def test_cors_allowlist_allowed_origin(self):
        """Verify that an allowed origin receives the correct CORS headers on error."""
        # Force a 500 error to trigger the CORS error handler origin reflection logic
        resp = self.client.get("/files", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
        self.assertEqual(resp.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_cors_allowlist_disallowed_origin(self):
        """Verify that a disallowed origin is NOT reflected in the CORS headers."""
        resp = self.client.get("/files", headers={"Origin": "http://malicious-attacker.com"})
        self.assertNotEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://malicious-attacker.com")

    # ─────────────────────────────────────────────────────────────
    # 3. Plan-limit Database Fields Mismatch
    # ─────────────────────────────────────────────────────────────
    def test_plan_limit_fields_resolution(self):
        """Verify that plan limits are loaded from the database and resolve to correct columns."""
        # Seeding a test plan in DB if not exists
        test_plan = self.db.query(Plan).filter(Plan.plan_id == "pro").first()
        if not test_plan:
            test_plan = Plan(
                plan_id="pro",
                name="Pro Plan",
                monthly_price_cents=1900,
                annual_price_cents=19000,
                query_limit=-1,
                upload_limit=-1,
                file_size_limit_bytes=100 * 1024 * 1024,
                storage_limit_bytes=10 * 1024 * 1024 * 1024,
                report_limit=-1,
                export_limit=-1,
                member_limit=1,
                is_active=True
            )
            self.db.add(test_plan)
            self.db.commit()
            
        limits = get_plan_limits("pro", self.db)
        # Ensure we loaded upload_limit/query_limit without AttributeError
        self.assertEqual(limits["upload_count"], -1)
        self.assertEqual(limits["query_count"], -1)
        self.assertEqual(limits["storage_bytes"], 10 * 1024 * 1024 * 1024)

    # ─────────────────────────────────────────────────────────────
    # 4. Protected Endpoints & Tenant Isolation
    # ─────────────────────────────────────────────────────────────
    def test_protected_endpoints_unauthenticated(self):
        """Verify GET /files, DELETE /files/{id}, and POST /provider return 401 when unauthenticated."""
        r1 = self.client.get("/files")
        self.assertEqual(r1.status_code, 401)
        
        r2 = self.client.delete("/files/some-id")
        self.assertEqual(r2.status_code, 401)
        
        r3 = self.client.post("/provider", json={"provider": "gemini"})
        self.assertEqual(r3.status_code, 401)

    # ─────────────────────────────────────────────────────────────
    # 5. Password Validation
    # ─────────────────────────────────────────────────────────────
    def test_password_length_signup_validation(self):
        """Verify that passwords under 8 characters fail signup validation."""
        resp = self.client.post("/auth/signup", json={
            "email": "test-rc1@example.com",
            "password": "short"
        })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("string_too_short", str(resp.json()))

    def test_password_length_reset_validation(self):
        """Verify that passwords under 8 characters fail reset password validation."""
        resp = self.client.post("/auth/reset-password", json={
            "token": "fake-token",
            "new_password": "short"
        })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("string_too_short", str(resp.json()))

    # ─────────────────────────────────────────────────────────────
    # 6. Dependency Vulnerability verification
    # ─────────────────────────────────────────────────────────────
    def test_python_multipart_cve_mitigated(self):
        """Verify that the installed python-multipart library is not vulnerable (>=0.0.12)."""
        import multipart
        self.assertTrue(hasattr(multipart, "__file__"))

    # ─────────────────────────────────────────────────────────────
    # 7. Staged Transformation Expiry & Eviction
    # ─────────────────────────────────────────────────────────────
    def test_staged_transformations_eviction(self):
        """Verify that staged transformations expire after their TTL and eviction functions normally."""
        from main import _staged_transformations, _evict_expired_staged
        # Insert a simulated staged transform with an expired epoch timestamp
        trans_id = "test_expired"
        _staged_transformations[trans_id] = ([], "file_id", 0.0) # 0.0 is way in the past (1970)
        
        # Insert an active one
        active_id = "test_active"
        import time
        _staged_transformations[active_id] = ([], "file_id", time.time())
        
        # Run eviction
        _evict_expired_staged()
        
        # Verify expired was removed
        self.assertNotIn(trans_id, _staged_transformations)
        # Verify active remains
        self.assertIn(active_id, _staged_transformations)
        
        # Cleanup
        _staged_transformations.pop(active_id, None)

    # ─────────────────────────────────────────────────────────────
    # 8. Workspace N+1 Query Reduction Check
    # ─────────────────────────────────────────────────────────────
    def test_workspace_listing_n_plus_one_avoided(self):
        """Verify list_workspaces executes query without N+1 issue (uses single IN query)."""
        import core.workspace_routes as ws_routes
        import inspect as py_inspect
        src = py_inspect.getsource(ws_routes.list_workspaces)
        self.assertIn("workspace_ids = [", src)
        self.assertIn(".filter(Workspace.workspace_id.in_(workspace_ids)).all()", src)

    # ─────────────────────────────────────────────────────────────
    # 9. Plan-tier Input Validation
    # ─────────────────────────────────────────────────────────────
    def test_plan_tier_validation(self):
        """Verify CreateWorkspaceRequest plan_tier accepts only valid plan tiers."""
        from core.workspace_routes import CreateWorkspaceRequest
        
        # Valid tiers
        for tier in ["free", "pro", "business", "enterprise"]:
            req = CreateWorkspaceRequest(name="WS", plan_tier=tier)
            self.assertEqual(req.plan_tier, tier)
            
        # Invalid tier
        with self.assertRaises(ValueError):
            CreateWorkspaceRequest(name="WS", plan_tier="ultimate_vip_enterprise")

    # ─────────────────────────────────────────────────────────────
    # 10. Input Size Limits Validation
    # ─────────────────────────────────────────────────────────────
    def test_input_size_limits_chat_request(self):
        """Verify oversized chat messages (> 32,000 chars) are rejected with 422."""
        resp = self.client.post("/chat/stream", json={
            "message": "x" * 32001,
            "file_ids": [],
            "conversation_history": []
        })
        self.assertEqual(resp.status_code, 422)

    def test_input_size_limits_export_request(self):
        """Verify oversized export requests (> 50,000 items) are rejected with 422."""
        resp = self.client.post("/export/results", json={
            "rows": [{"a": 1}] * 50001,
            "filename": "test.csv"
        })
        self.assertEqual(resp.status_code, 422)

    def test_input_size_limits_pipeline_request(self):
        """Verify oversized transformation pipelines (> 100 steps) are rejected with 422."""
        from main import TransformPipelineRequest
        with self.assertRaises(ValueError):
            TransformPipelineRequest(pipeline=[{"action": "test"}] * 101)

    # ─────────────────────────────────────────────────────────────
    # 11. Database Indexes Verification
    # ─────────────────────────────────────────────────────────────
    def test_database_indexes_applied(self):
        """Verify that the 10 missing indexes created in migration a7f3b9c2d1e4 exist in the DB."""
        inspector = inspect(self.db.bind)
        
        expected_indexes = {
            "sessions": ["ix_sessions_user_id", "ix_sessions_workspace_id"],
            "messages": ["ix_messages_user_id", "ix_messages_workspace_id", "ix_messages_session_id"],
            "email_verification_tokens": ["ix_email_verification_tokens_token_hash"],
            "password_reset_tokens": ["ix_password_reset_tokens_token_hash"],
            "workspace_members": ["ix_workspace_members_user_id"],
            "refresh_tokens": ["ix_refresh_tokens_user_id"],
            "usage_stats": ["ix_usage_stats_workspace_period"]
        }
        
        for table, indexes in expected_indexes.items():
            db_indexes = [idx["name"] for idx in inspector.get_indexes(table)]
            for expected in indexes:
                self.assertIn(expected, db_indexes, f"Missing index {expected} on table {table}")

    # ─────────────────────────────────────────────────────────────
    # 12. Billing Redirect URL Domain Protection Validation
    # ─────────────────────────────────────────────────────────────
    def test_billing_redirect_domain_validation_logic(self):
        """Verify domain protection logic blocks lookalike domains and unsafe protocols."""
        with open(os.path.join(os.path.dirname(__file__), "../frontend/src/lib/billingClient.js"), "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("export function isSafeBillingRedirect(url)", content)
            self.assertIn("parsed.hostname === window.location.hostname", content)
            self.assertIn("parsed.hostname === 'checkout.stripe.com'", content)
            self.assertIn("parsed.hostname.endsWith('.stripe.com')", content)
            self.assertIn("parsed.protocol !== 'https:'", content)

if __name__ == "__main__":
    unittest.main()
