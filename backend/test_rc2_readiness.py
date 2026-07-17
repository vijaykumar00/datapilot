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


if __name__ == "__main__":
    unittest.main()
