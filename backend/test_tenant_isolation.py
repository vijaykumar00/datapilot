import os
import sys
import unittest
import uuid
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
import core.dataset_store as dataset_store
import core.session_store as session_store
import core.report_store as report_store
import core.analysis_store as analysis_store
from core.template_store import get_template_store
from core.auth import create_access_token, hash_password
from core.db import SessionLocal
from core.models import AuditLog, User, UserAPIKey, Workspace, WorkspaceMember


class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.guest_a = self.client.post("/guest/session").json()
        self.guest_b = self.client.post("/guest/session").json()
        self.headers_a = {"X-Guest-Token": self.guest_a["guest_token"]}
        self.headers_b = {"X-Guest-Token": self.guest_b["guest_token"]}
        self.cleanup_sessions = []
        self.cleanup_reports = []
        self.cleanup_analyses = []
        self.cleanup_templates = []
        self.cleanup_users = []
        self.cleanup_workspaces = []
        self.cleanup_api_keys = []

    def tearDown(self):
        for sid in self.cleanup_sessions:
            session_store.delete_session(sid)
        for rid in self.cleanup_reports:
            report_store.delete_report(rid)
        for aid in self.cleanup_analyses:
            analysis_store.delete_analysis(aid)
        store = get_template_store()
        for tid in self.cleanup_templates:
            store.delete_template(tid)
        db = SessionLocal()
        try:
            for key_id in self.cleanup_api_keys:
                db.query(UserAPIKey).filter(UserAPIKey.id == key_id).delete()
            for workspace_id in self.cleanup_workspaces:
                db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id).delete()
                db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).delete()
                db.query(Workspace).filter(Workspace.workspace_id == workspace_id).delete()
            for user_id in self.cleanup_users:
                db.query(AuditLog).filter(AuditLog.user_id == user_id).delete()
                db.query(UserAPIKey).filter(UserAPIKey.user_id == user_id).delete()
                db.query(User).filter(User.user_id == user_id).delete()
            db.commit()
        finally:
            db.close()

    def _create_auth_context(self, label: str) -> dict:
        db = SessionLocal()
        try:
            user_id = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())
            email = f"{label}-{user_id}@datapilot.test"
            user = User(
                user_id=user_id,
                email=email,
                password_hash=hash_password("SecurePassword123!"),
                email_verified=True,
            )
            workspace = Workspace(
                workspace_id=workspace_id,
                name=f"{label} Workspace",
                plan_tier="free",
                owner_id=user_id,
            )
            member = WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user_id,
                role="Owner",
            )
            db.add_all([user, workspace, member])
            db.commit()
            token = create_access_token(user_id, email, workspace_id)
            self.cleanup_users.append(user_id)
            self.cleanup_workspaces.append(workspace_id)
            return {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "headers": {
                    "Authorization": f"Bearer {token}",
                    "X-Workspace-ID": workspace_id,
                },
            }
        finally:
            db.close()

    def test_guest_resources_are_not_visible_across_tenants(self):
        session_resp = self.client.post(
            "/sessions",
            json={"name": "Tenant A Session"},
            headers=self.headers_a,
        )
        self.assertEqual(session_resp.status_code, 200)
        session_id = session_resp.json()["session"]["session_id"]
        self.cleanup_sessions.append(session_id)

        chat_resp = self.client.post(
            "/chat/stream",
            json={
                "message": "tenant secret query",
                "file_ids": [],
                "conversation_history": [],
                "session_id": session_id,
            },
            headers=self.headers_a,
        )
        self.assertEqual(chat_resp.status_code, 200)

        a_history = self.client.get("/history/search?q=tenant%20secret", headers=self.headers_a)
        b_history = self.client.get("/history/search?q=tenant%20secret", headers=self.headers_b)
        self.assertEqual(a_history.status_code, 200)
        self.assertEqual(b_history.status_code, 200)
        self.assertGreaterEqual(len(a_history.json()["messages"]), 1)
        self.assertEqual(b_history.json()["messages"], [])

        b_messages = self.client.get(f"/sessions/{session_id}/messages", headers=self.headers_b)
        self.assertEqual(b_messages.status_code, 200)
        self.assertEqual(b_messages.json()["messages"], [])

        report_resp = self.client.post(
            "/reports",
            json={"title": "Tenant A Report", "content": "private report"},
            headers=self.headers_a,
        )
        self.assertEqual(report_resp.status_code, 200)
        report_id = report_resp.json()["report"]["report_id"]
        self.cleanup_reports.append(report_id)
        self.assertEqual(self.client.get(f"/reports/{report_id}", headers=self.headers_b).status_code, 404)
        self.assertEqual(self.client.get("/reports", headers=self.headers_b).json()["reports"], [])

        analysis_resp = self.client.post(
            "/analyses",
            json={
                "session_id": session_id,
                "title": "Tenant A Analysis",
                "query": "private",
                "response": "private response",
            },
            headers=self.headers_a,
        )
        self.assertEqual(analysis_resp.status_code, 200)
        analysis_id = analysis_resp.json()["analysis"]["analysis_id"]
        self.cleanup_analyses.append(analysis_id)
        self.assertEqual(self.client.get(f"/analyses/{analysis_id}", headers=self.headers_b).status_code, 404)

        template_resp = self.client.post(
            "/templates",
            json={
                "name": "Tenant A Template",
                "description": "private template",
                "category": "Finance",
                "steps": [{"action": "fill_nulls", "column": "amount", "strategy": "median"}],
            },
            headers=self.headers_a,
        )
        self.assertEqual(template_resp.status_code, 200)
        template_id = template_resp.json()["template"]["template_id"]
        self.cleanup_templates.append(template_id)
        self.assertEqual(self.client.post(f"/templates/{template_id}/duplicate", headers=self.headers_b).status_code, 404)
        self.assertEqual(self.client.delete(f"/templates/{template_id}", headers=self.headers_b).status_code, 404)

    def test_dataset_registry_reads_and_mutations_are_tenant_scoped(self):
        dataset_id = "tenant_scope_ds"
        conn = dataset_store.get_connection()
        try:
            conn.execute("DELETE FROM dataset_registry WHERE dataset_id = ?;", (dataset_id,))
            conn.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id, filename, display_name, description, tags,
                    row_count, column_count, sheet_count, file_size_bytes, archived,
                    upload_date, user_id, workspace_id, created_at, updated_at
                ) VALUES (?, 'private.csv', 'Private', '', '[]', 1, 1, 1, 10, 0, '2026-08-09T00:00:00', ?, ?, '2026-08-09T00:00:00', '2026-08-09T00:00:00');
                """,
                (dataset_id, self.guest_a["guest_session_id"], self.guest_a["guest_session_id"]),
            )
            conn.commit()
        finally:
            conn.close()

        try:
            self.assertEqual(self.client.get(f"/datasets/{dataset_id}", headers=self.headers_a).status_code, 200)
            self.assertEqual(self.client.get(f"/datasets/{dataset_id}", headers=self.headers_b).status_code, 404)
            self.assertEqual(self.client.patch(f"/datasets/{dataset_id}", json={"display_name": "Stolen"}, headers=self.headers_b).status_code, 404)
            self.assertEqual(self.client.post(f"/datasets/{dataset_id}/archive", headers=self.headers_b).status_code, 404)
        finally:
            conn = dataset_store.get_connection()
            try:
                conn.execute("DELETE FROM dataset_registry WHERE dataset_id = ?;", (dataset_id,))
                conn.commit()
            finally:
                conn.close()

    def test_authenticated_workspace_spoofing_and_direct_resource_guessing_are_blocked(self):
        tenant_a = self._create_auth_context("tenant-a")
        tenant_b = self._create_auth_context("tenant-b")
        spoofed_headers = {
            "Authorization": tenant_a["headers"]["Authorization"],
            "X-Workspace-ID": tenant_b["workspace_id"],
        }

        self.assertEqual(self.client.get("/billing/current", headers=spoofed_headers).status_code, 404)
        self.assertEqual(self.client.get("/billing/usage", headers=spoofed_headers).status_code, 404)
        self.assertEqual(self.client.get("/user/usage", headers=spoofed_headers).status_code, 404)

        api_key_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(UserAPIKey(
                id=api_key_id,
                user_id=tenant_a["user_id"],
                provider="openai",
                label="Tenant A Key",
                encrypted_key="not-decryptable-in-this-test",
            ))
            db.commit()
            self.cleanup_api_keys.append(api_key_id)
        finally:
            db.close()

        b_keys = self.client.get("/user/api-keys", headers=tenant_b["headers"])
        self.assertEqual(b_keys.status_code, 200)
        self.assertNotIn(api_key_id, [item["id"] for item in b_keys.json()["api_keys"]])
        self.assertEqual(self.client.delete(f"/user/api-keys/{api_key_id}", headers=tenant_b["headers"]).status_code, 404)

        track_resp = self.client.post(
            "/user/track",
            headers=tenant_a["headers"],
            json={"event_type": "TENANT_TEST", "description": "blocked", "workspace_id": tenant_b["workspace_id"]},
        )
        self.assertEqual(track_resp.status_code, 404)

        grant_resp = self.client.post(
            "/billing/admin/subscriptions/grant",
            headers=tenant_a["headers"],
            json={"workspace_id": tenant_b["workspace_id"], "plan_id": "team", "reason": "should fail"},
        )
        self.assertEqual(grant_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
