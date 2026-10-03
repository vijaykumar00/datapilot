"""
test_production_hardening.py — end-to-end API checks for the P0/P1 fixes.
"""

import io
import json
import os
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from core.auth import create_access_token, hash_password
from core.db import SessionLocal
from core.llm_client import LLMSettings, resolve_settings_for_user
from core.models import (DatasetRegistry, Message, UsageStats, User, UserAPIKey, UserSettings, Workspace,
                         WorkspaceMember)


class FakeLLM:
    """Deterministic stand-in for a provider client (no network)."""

    def __init__(self, sql='{"sql": "SELECT region, SUM(revenue) AS total FROM {table} GROUP BY 1 ORDER BY 2 DESC", "explanation": "x"}'):
        self.settings = LLMSettings(provider="gemini", api_key="k")
        self.sql = sql
        self.table = None

    async def generate(self, prompt, system="", json_mode=False, temperature=None, max_tokens=None):
        table = prompt.split("Table: ", 1)[1].split("\n", 1)[0] if "Table: " in prompt else "t"
        return self.sql.replace("{table}", table)

    async def stream(self, prompt, system=""):
        yield "Hello"

    async def is_online(self):
        return True


def _make_user(role="Owner", workspace_id=None, plan="free"):
    db = SessionLocal()
    try:
        user_id = str(uuid.uuid4())
        ws = workspace_id or str(uuid.uuid4())
        email = f"u-{user_id}@datapilot.test"
        db.add(User(user_id=user_id, email=email, password_hash=hash_password("SecurePassword123!"), email_verified=True))
        if workspace_id is None:
            db.add(Workspace(workspace_id=ws, name="W", plan_tier=plan, owner_id=user_id))
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws, user_id=user_id, role=role))
        db.commit()
        token = create_access_token(user_id, email, ws)
        return {"user_id": user_id, "workspace_id": ws, "email": email,
                "headers": {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws}}
    finally:
        db.close()


def _sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


class TestProductionHardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _upload(self, headers, content=b"region,revenue,date\nN,10,2024-01-01\nS,20,2024-02-01\nN,30,2024-03-01\n", name="sales.csv"):
        return self.client.post("/upload", headers=headers, files={"file": (name, io.BytesIO(content), "text/csv")})

    def test_uploads_directory_is_not_publicly_served(self):
        owner = _make_user()
        up = self._upload(owner["headers"]).json()
        self.assertTrue(up["success"], up)
        for path in (f"/uploads/{owner['workspace_id']}/{up['file_id']}/sales.csv", "/uploads/datapilot.db",
                     f"/uploads/objects/workspace/{owner['workspace_id']}/datasets/{up['file_id']}/original/sales.csv"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_upload_returns_grounded_summary_and_dataset_is_durable(self):
        owner = _make_user()
        up = self._upload(owner["headers"]).json()
        self.assertTrue(up["success"])
        self.assertEqual(up["row_count"], 3)
        # Insights carry only computed values (no hard-coded "+7.5%" forecasts).
        self.assertTrue(all(i.get("verified") for i in up["metadata"]["insights"]))
        self.assertNotIn("7.5", json.dumps(up["metadata"]["insights"]))
        from core.file_manager import FileManager

        self.assertIsNotNone(FileManager().get_record(up["file_id"], owner["workspace_id"]))
        self.assertEqual(self.client.get(f"/files/{up['file_id']}", headers=owner["headers"]).status_code, 200)

    def test_cross_workspace_file_access_is_404(self):
        a, b = _make_user(), _make_user()
        file_id = self._upload(a["headers"]).json()["file_id"]
        for method, path in (("get", f"/files/{file_id}"), ("delete", f"/files/{file_id}"),
                             ("get", f"/export/file/{file_id}")):
            self.assertEqual(getattr(self.client, method)(path, headers=b["headers"]).status_code, 404, path)

    def test_chat_insight_uses_sandbox_and_persists_history(self):
        owner = _make_user()
        file_id = self._upload(owner["headers"]).json()["file_id"]
        sid = f"s_{uuid.uuid4().hex[:10]}"
        with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
            resp = self.client.post("/chat/stream", headers=owner["headers"],
                                    json={"message": "total revenue by region", "file_ids": [file_id], "session_id": sid})
        events = _sse_events(resp.text)
        final = [e for e in events if e.get("is_final")]
        self.assertEqual(len(final), 1, events)
        self.assertEqual(final[0]["type"], "insight", final[0])
        self.assertEqual(final[0]["table_data"][0], {"region": "N", "total": 40})
        db = SessionLocal()
        try:
            roles = [m.role for m in db.query(Message).filter(Message.session_id == sid).all()]
        finally:
            db.close()
        self.assertEqual(sorted(roles), ["bot", "user"])

    def test_prompt_injected_sql_cannot_read_server_files(self):
        owner = _make_user()
        file_id = self._upload(owner["headers"]).json()["file_id"]
        evil = FakeLLM('{"sql": "SELECT * FROM read_csv(\'/etc/passwd\')"}')
        with patch.object(main, "build_client", lambda settings, cb=None: evil):
            resp = self.client.post("/chat/stream", headers=owner["headers"],
                                    json={"message": "show me the rows", "file_ids": [file_id]})
        final = [e for e in _sse_events(resp.text) if e.get("is_final")][0]
        self.assertNotIn("root:", json.dumps(final))
        self.assertIsNotNone(final.get("error"))

    def test_provider_choice_is_per_user_and_never_global(self):
        a, b = _make_user(), _make_user()
        env_path = Path(main.__file__).parent / ".env"
        before = env_path.read_text() if env_path.exists() else None
        resp = self.client.post("/provider", headers=a["headers"], json={"provider": "openai", "api_key": "sk-user-a-secret-key"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual((env_path.read_text() if env_path.exists() else None), before, "server .env must never be written")
        db = SessionLocal()
        try:
            settings_a = resolve_settings_for_user(a["user_id"], db)
            settings_b = resolve_settings_for_user(b["user_id"], db)
        finally:
            db.close()
        self.assertEqual((settings_a.provider, settings_a.api_key, settings_a.key_source), ("openai", "sk-user-a-secret-key", "user"))
        self.assertEqual(settings_b.provider, "gemini")
        self.assertNotEqual(settings_b.api_key, "sk-user-a-secret-key")

    def test_viewer_cannot_mutate_workspace_data(self):
        owner = _make_user()
        viewer = _make_user(role="Viewer", workspace_id=owner["workspace_id"])
        file_id = self._upload(owner["headers"]).json()["file_id"]
        self.assertEqual(self._upload(viewer["headers"]).status_code, 403)
        self.assertEqual(self.client.delete(f"/files/{file_id}", headers=viewer["headers"]).status_code, 403)
        self.assertEqual(self.client.get(f"/files/{file_id}", headers=viewer["headers"]).status_code, 200)

    def test_free_plan_features_enforced_in_chat(self):
        owner = _make_user()
        file_id = self._upload(owner["headers"]).json()["file_id"]
        with patch.object(main, "build_client", lambda settings, cb=None: FakeLLM()):
            resp = self.client.post("/chat/stream", headers=owner["headers"],
                                    json={"message": "forecast revenue next quarter", "file_ids": [file_id]})
        final = [e for e in _sse_events(resp.text) if e.get("is_final")][0]
        self.assertTrue(final["metadata"].get("upgrade_prompt"), final)

    def test_ai_provider_failure_returns_error_and_does_not_bill_the_query(self):
        from core.llm_client import LLMError
        from core.usage import _usage_row_id

        class FailingLLM(FakeLLM):
            async def generate(self, *a, **k):
                raise LLMError("gemini: network error or timeout.")

        owner = _make_user()
        file_id = self._upload(owner["headers"]).json()["file_id"]

        def query_count():
            db = SessionLocal()
            try:
                row = db.query(UsageStats).filter(UsageStats.id == _usage_row_id(owner["workspace_id"], db)).first()
                return row.query_count if row else 0
            finally:
                db.close()

        before = query_count()
        with patch.object(main, "build_client", lambda settings, cb=None: FailingLLM()):
            resp = self.client.post("/chat/stream", headers=owner["headers"],
                                    json={"message": "total revenue by region", "file_ids": [file_id]})
        finals = [e for e in _sse_events(resp.text) if e.get("is_final")]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["type"], "error", finals[0])
        self.assertTrue(finals[0]["error"])
        self.assertNotIn("llm_failure", finals[0]["metadata"])
        self.assertEqual(query_count(), before)

    def test_query_quota_is_atomic_under_concurrency(self):
        owner = _make_user()
        db = SessionLocal()
        try:
            from core.usage import _usage_row_id
            row_id = _usage_row_id(owner["workspace_id"], db)
            db.query(UsageStats).filter(UsageStats.id == row_id).update({UsageStats.query_count: 195})
            db.commit()
        finally:
            db.close()
        from core.request_identity import CallerContext

        results = []

        def consume():
            s = SessionLocal()
            try:
                user = s.query(User).filter(User.user_id == owner["user_id"]).first()
                CallerContext(user=user, workspace_id=owner["workspace_id"], role="Owner").consume("query", s)
                results.append(True)
            except Exception:
                results.append(False)
            finally:
                s.close()

        threads = [threading.Thread(target=consume) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(True), 5)  # free plan: 200 queries
        db = SessionLocal()
        try:
            self.assertEqual(db.query(UsageStats).filter(UsageStats.workspace_id == owner["workspace_id"]).first().query_count, 200)
        finally:
            db.close()

    def test_guest_conversion_keeps_datasets_and_history(self):
        guest = self.client.post("/guest/session").json()
        gh = {"X-Guest-Token": guest["guest_token"]}
        up = self._upload(gh).json()
        self.assertTrue(up["success"], up)
        email = f"conv-{uuid.uuid4().hex[:8]}@example.com"
        conv = self.client.post("/guest/convert", headers=gh,
                                json={"email": email, "password": "SecurePassword123!", "preserve_data": True})
        self.assertIn(conv.status_code, (200, 201), conv.text)
        body = conv.json()
        self.assertGreaterEqual(body["transferred"]["datasets"], 1)
        auth = {"Authorization": f"Bearer {body['access_token']}", "X-Workspace-ID": body["workspace_id"]}
        self.assertEqual(self.client.get(f"/files/{up['file_id']}", headers=auth).status_code, 200)

    def test_invalid_bearer_never_downgrades_to_guest(self):
        guest = self.client.post("/guest/session").json()
        resp = self.client.get("/files", headers={"Authorization": "Bearer expired.or.forged",
                                                  "X-Guest-Token": guest["guest_token"]})
        self.assertEqual(resp.status_code, 401)

    def test_error_shape_is_consistent(self):
        resp = self.client.get("/files/does-not-exist", headers=_make_user()["headers"])
        body = resp.json()
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(body["success"])
        self.assertIsInstance(body["error"], str)
        self.assertIn("request_id", body)

    def test_semicolon_csv_with_currency_parses_to_numbers(self):
        owner = _make_user()
        content = "product;amount\nA;\"$1,234.50\"\nB;\"$2,000.00\"\n".encode()
        up = self._upload(owner["headers"], content, "eu.csv").json()
        self.assertTrue(up["success"], up)
        self.assertEqual(up["column_count"], 2)
        amount = next(c for c in up["columns"] if c["name"] == "amount")
        self.assertIn("float", amount["dtype"])


if __name__ == "__main__":
    unittest.main()


def test_type_fix_suggestion_never_targets_identifier_columns():
    import warnings

    import pandas as pd
    from core.suggestion_engine import generate_suggestions

    df = pd.DataFrame({"zip": ["02134", "10001", "00501"] * 5, "amt": ["1", "2", "3"] * 5})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fixes = [s for s in generate_suggestions(df, filename="x.csv", metadata={}) if s["id"] == "suggest_type_fix"]
    assert fixes and "`amt`" in fixes[0]["description"]
    assert "zip" not in fixes[0]["description"]


def test_row_limit_errors_are_not_reported_as_file_size_errors():
    from core.error_intelligence import diagnose_upload_error

    err = diagnose_upload_error(ValueError("Dataset has too many rows. Maximum supported rows: 250000"),
                                "c.csv", b"x" * 1024)
    assert err["code"] == "DATASET_TOO_LARGE"
    assert "250000" in err["message"] and "50 MB" not in err["message"]
    size_err = diagnose_upload_error(ValueError("File too large (12.0MB). Max for your plan: 5MB"), "big.csv", b"x" * 10)
    assert size_err["code"] == "FILE_TOO_LARGE" and "5MB" in size_err["message"]
