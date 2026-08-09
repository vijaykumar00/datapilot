import os
import unittest

from fastapi.testclient import TestClient

from main import app
from scripts.validate_env import validate


class TestRC2Readiness(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_liveness_probe_is_lightweight(self):
        response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})

    def test_readiness_probe_reports_required_checks(self):
        previous = os.environ.get("JWT_SECRET")
        os.environ["JWT_SECRET"] = "a" * 64
        try:
            response = self.client.get("/ready")
        finally:
            if previous is None:
                os.environ.pop("JWT_SECRET", None)
            else:
                os.environ["JWT_SECRET"] = previous

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["checks"]["database"])
        self.assertTrue(body["checks"]["uploads_writable"])
        self.assertTrue(body["checks"]["jwt_secret"])
        self.assertTrue(body["checks"]["rate_limiter"])
        self.assertTrue(body["checks"]["storage"])
        self.assertIn("rate_limiter", body["details"])
        self.assertIn("storage", body["details"])

    def test_production_env_validator_rejects_localhost(self):
        errors = validate({
            "APP_ENV": "production",
            "JWT_SECRET": "a" * 64,
            "DATABASE_URL": "postgresql+psycopg2://user:pass@localhost:5432/datapilot",
            "ALLOWED_ORIGINS": "http://localhost:5173",
            "AI_PROVIDER": "gemini",
            "GEMINI_API_KEY": "placeholder",
        })

        self.assertTrue(any("DATABASE_URL must not point at localhost" in error for error in errors))
        self.assertTrue(any("ALLOWED_ORIGINS entry must be HTTPS" in error for error in errors))

    def test_production_env_validator_requires_redis_and_nonlocal_storage(self):
        errors = validate({
            "APP_ENV": "production",
            "JWT_SECRET": "a" * 64,
            "DATABASE_URL": "postgresql+psycopg2://user:pass@postgres:5432/datapilot",
            "ALLOWED_ORIGINS": "https://app.datapilot.test",
            "AI_PROVIDER": "gemini",
            "GEMINI_API_KEY": "placeholder",
            "STRIPE_BILLING_ENABLED": "false",
            "RATE_LIMITER_BACKEND": "memory",
            "STORAGE_PROVIDER": "local",
        })

        self.assertTrue(any("REDIS_URL is required" in error for error in errors))
        self.assertTrue(any("RATE_LIMITER_BACKEND must be redis" in error for error in errors))
        self.assertTrue(any("STORAGE_PROVIDER=local is not allowed" in error for error in errors))

    def test_production_database_guard_rejects_sqlite(self):
        from core.db import validate_database_url_for_runtime

        with self.assertRaises(RuntimeError):
            validate_database_url_for_runtime("sqlite:///prod.db", app_env="production")


if __name__ == "__main__":
    unittest.main()
