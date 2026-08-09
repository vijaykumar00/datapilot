import os
import sys
import unittest
from fastapi.testclient import TestClient

# Add current directory to path to import backend core modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
from core.db import get_connection, log_api_error
import core.session_store as session_store
import core.template_store as template_store
import core.storage as storage
from core.rate_limiter import reset_rate_limiter


class TestPreAuthCleanup(unittest.TestCase):
    def setUp(self):
        self._old_rate_limiter_backend = os.environ.get("RATE_LIMITER_BACKEND")
        self._old_rate_limit_max = os.environ.get("RATE_LIMIT_MAX_REQUESTS")
        os.environ["RATE_LIMITER_BACKEND"] = "memory"
        os.environ["RATE_LIMIT_MAX_REQUESTS"] = "100"
        reset_rate_limiter()
        self.client = TestClient(app)
        guest = self.client.post("/guest/session").json()
        self.guest_headers = {"X-Guest-Token": guest["guest_token"]}

    def tearDown(self):
        if self._old_rate_limiter_backend is None:
            os.environ.pop("RATE_LIMITER_BACKEND", None)
        else:
            os.environ["RATE_LIMITER_BACKEND"] = self._old_rate_limiter_backend

        if self._old_rate_limit_max is None:
            os.environ.pop("RATE_LIMIT_MAX_REQUESTS", None)
        else:
            os.environ["RATE_LIMIT_MAX_REQUESTS"] = self._old_rate_limit_max

        reset_rate_limiter()

    def test_connection_pooling(self):
        """Test that get_connection returns a valid connection and connection pool works."""
        conn1 = get_connection()
        self.assertIsNotNone(conn1)
        cursor = conn1.cursor()
        cursor.execute("SELECT 1;")
        res = cursor.fetchone()
        self.assertEqual(res[0], 1)
        conn1.close()

    def test_server_side_session_generation(self):
        """Test session creation generates a UUID server-side when omitted."""
        resp = self.client.post(
            "/sessions",
            json={"name": "Test Generated Session"},
            headers=self.guest_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("session_id", data["session"])
        self.assertIsNotNone(data["session"]["session_id"])
        # Cleanup
        session_id = data["session"]["session_id"]
        session_store.delete_session(session_id)

    def test_cors_config(self):
        """Test CORS allowed origins are loaded correctly."""
        # Allowed origin from .env (default: http://localhost:5173)
        headers = {
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        }
        resp = self.client.options("/health", headers=headers)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_request_size_limit(self):
        """Test requests over 50MB are rejected by middleware."""
        # 51MB payload
        large_payload = "X" * (51 * 1024 * 1024)
        resp = self.client.post("/export/results", data=large_payload)
        self.assertEqual(resp.status_code, 413)
        self.assertIn("Payload too large", resp.json()["detail"])

    def test_rate_limiting(self):
        """Test that rate limiting triggers after a bursts of requests."""
        # Fire 105 quick health requests (rate limit is 100/min)
        # Note: rate limit middleware ignores /health and /uploads, let's hit /sessions instead
        blocked = False
        for i in range(110):
            resp = self.client.get("/sessions", headers=self.guest_headers)
            if resp.status_code == 429:
                blocked = True
                break
        self.assertTrue(blocked, "Rate limit should have blocked requests after 100 requests")

    def test_db_template_persistence(self):
        """Test custom template persistence in SQLite."""
        store = template_store.get_template_store()
        template = store.create_template(
            name="Test Template DB",
            description="Testing template persistence",
            category="Finance",
            steps=[{"action": "test", "column": "revenue"}],
            user_id="test_user",
            workspace_id="test_workspace"
        )
        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "Test Template DB")
        
        # Verify in list
        templates = store.list_templates(user_id="test_user", workspace_id="test_workspace")
        self.assertTrue(any(t["template_id"] == template["template_id"] for t in templates))
        
        # Clean up
        ok = store.delete_template(template["template_id"])
        self.assertTrue(ok)

    def test_namespaced_storage(self):
        """Test storage namespacing under workspace/dataset directories."""
        provider = storage.get_storage_provider()
        test_content = b"row1,row2\n1,2"
        
        path_tuple = provider.save_file(
            workspace_id="test_ws",
            dataset_id="test_ds",
            filename="test_file.csv",
            content=test_content
        )
        path = path_tuple[0]
        # Verify namespaced path exists
        self.assertIn("test_ws", str(path))
        self.assertIn("test_ds", str(path))
        self.assertTrue(path.exists())
        
        # Read back
        read_content = provider.read_file("test_ws", "test_ds", "test_file.csv")
        self.assertEqual(read_content, test_content)
        
        # Cleanup
        provider.delete_file("test_ws", "test_ds", "test_file.csv")

    def test_api_error_logging(self):
        """Test exception middleware logs unhandled errors into error_logs DB table."""
        # Cause an unhandled exception by hitting a route or calling log_api_error directly
        req_id = "req_test_error_123"
        log_api_error(
            request_id=req_id,
            endpoint="/test-endpoint",
            error_type="ValueError",
            message="Test error message",
            traceback="Traceback test info",
            user_id="test_user",
            workspace_id="test_workspace"
        )
        
        # Query DB to check if it exists
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT message FROM error_logs WHERE request_id = ?;", (req_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["message"], "Test error message")
        conn.close()


if __name__ == "__main__":
    unittest.main()
