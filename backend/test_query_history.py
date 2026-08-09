import os
import sys
import unittest
from fastapi.testclient import TestClient

# Add current directory to path to import backend core modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
import core.session_store as session_store

class TestQueryHistory(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_sessions = []
        guest = self.client.post("/guest/session").json()
        self.guest_headers = {"X-Guest-Token": guest["guest_token"]}
        self.guest_id = guest["guest_session_id"]

    def tearDown(self):
        for sid in self.test_sessions:
            session_store.delete_session(sid)

    def test_sessions_pagination_and_search(self):
        """Test that get_sessions_paginated and GET /sessions endpoints correctly paginate and search."""
        names = [
            "Apple Analysis Session",
            "Banana Clean Session",
            "Cherry Insight Session",
            "Date Forecast Session",
            "Elderberry Report Session"
        ]
        
        created_ids = []
        guest_user = self.guest_id
        guest_workspace = self.guest_id

        for name in names:
            sess = session_store.create_session(name=name, user_id=guest_user, workspace_id=guest_workspace)
            self.assertIn("session_id", sess)
            created_ids.append(sess["session_id"])
            self.test_sessions.append(sess["session_id"])

        # Test limit and offset on helper
        res = session_store.get_sessions_paginated(
            user_id=guest_user,
            workspace_id=guest_workspace,
            limit=2,
            offset=0
        )
        self.assertEqual(res["total"], 5)
        self.assertEqual(len(res["sessions"]), 2)

        # Test search on helper
        res_search = session_store.get_sessions_paginated(
            user_id=guest_user,
            workspace_id=guest_workspace,
            search="Insight"
        )
        self.assertEqual(res_search["total"], 1)
        self.assertEqual(res_search["sessions"][0]["name"], "Cherry Insight Session")

        # Test API endpoint GET /sessions with limit & offset
        resp = self.client.get("/sessions?limit=3&offset=1", headers=self.guest_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("sessions", data)
        self.assertIn("total", data)

    def test_message_metadata_persistence(self):
        """Test that agent_used and dataset_refs are persisted correctly in bot messages."""
        sess = session_store.create_session(name="Metadata Test Session", user_id="test_history_user", workspace_id="test_history_ws")
        sid = sess["session_id"]
        self.test_sessions.append(sid)

        # Append user message
        session_store.append_message(sid, "user", "How is the weather?", user_id="test_history_user", workspace_id="test_history_ws")

        # Append bot message with agent and dataset refs in extra metadata
        extra = {
            "type": "text",
            "metadata": {
                "agent_used": "insight",
                "dataset_refs": ["ds_123", "ds_456"]
            }
        }
        session_store.append_message(sid, "bot", "It is sunny.", extra, user_id="test_history_user", workspace_id="test_history_ws")

        # Fetch history and assert
        history = session_store.get_history(sid)
        self.assertEqual(len(history), 2)
        self.assertEqual(len({m["id"] for m in history}), 2)
        
        bot_msg = next(m for m in history if m["role"] == "bot")
        self.assertEqual(bot_msg["content"], "It is sunny.")
        self.assertEqual(bot_msg["metadata"].get("agent_used"), "insight")
        self.assertEqual(bot_msg["metadata"].get("dataset_refs"), ["ds_123", "ds_456"])

if __name__ == "__main__":
    unittest.main()
