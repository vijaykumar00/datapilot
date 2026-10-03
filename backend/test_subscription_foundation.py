import os
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET", "subscription-foundation-test-secret-1234567890")
TEST_DB_PATH = BACKEND_DIR / "test_subscription_foundation.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"

from fastapi.testclient import TestClient

from main import app
from core.auth import create_access_token, hash_password
from core.db import SessionLocal, init_db
from core.models import PlanLimit, UsageStats, User, Workspace, WorkspaceMember
from core.subscriptions import (
    can_use_feature,
    enforce_quota,
    list_plans,
    seed_subscription_catalog,
    subscription_summary,
)


class TestSubscriptionFoundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except OSError:
                pass
        init_db()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except OSError:
                pass

    def setUp(self):
        self.db = SessionLocal()
        seed_subscription_catalog(self.db)
        self.user_id = str(uuid.uuid4())
        self.workspace_id = str(uuid.uuid4())
        user = User(
            user_id=self.user_id,
            email=f"owner-{self.user_id}@datapilot.test",
            password_hash=hash_password("SecurePassword123!"),
            email_verified=True,
        )
        workspace = Workspace(
            workspace_id=self.workspace_id,
            name="Subscription Test Workspace",
            plan_tier="free",
            owner_id=self.user_id,
        )
        member = WorkspaceMember(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            role="Owner",
        )
        self.db.add_all([user, workspace, member])
        self.db.commit()
        self.token = create_access_token(self.user_id, user.email, self.workspace_id)
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Workspace-ID": self.workspace_id,
        }

    def tearDown(self):
        self.db.close()

    def test_catalog_seeds_plan_limits_and_features(self):
        plans = list_plans(self.db, include_inactive=True)
        plan_ids = {plan["plan_id"] for plan in plans}

        self.assertTrue({"free", "pro", "team", "enterprise"}.issubset(plan_ids))
        team = next(plan for plan in plans if plan["plan_id"] == "team")
        self.assertEqual(team["limits"]["member_count"], 10)
        self.assertTrue(team["features"]["can_invite_members"])

    def test_workspace_subscription_summary_creates_trial_state(self):
        summary = subscription_summary(self.workspace_id, self.db)

        self.assertEqual(summary["subscription"]["plan_id"], "free")
        self.assertEqual(summary["subscription"]["status"], "trialing")
        self.assertTrue(summary["trial"]["active"])
        self.assertIn("upload_count", summary["remaining_quota"])

    def test_feature_checks_are_centralized_by_plan(self):
        self.assertFalse(can_use_feature(self.workspace_id, "can_forecast", self.db))
        grant = {"workspace_id": self.workspace_id, "plan_id": "team", "reason": "test grant"}

        # A workspace Owner (every customer) must NOT be able to grant themselves a plan.
        response = self.client.post("/billing/admin/subscriptions/grant", headers=self.headers, json=grant)
        self.assertEqual(response.status_code, 404, response.text)
        self.assertFalse(can_use_feature(self.workspace_id, "can_forecast", self.db))

        # Only an operator-configured platform admin can.
        previous = os.environ.get("PLATFORM_ADMIN_EMAILS")
        os.environ["PLATFORM_ADMIN_EMAILS"] = f"owner-{self.user_id}@datapilot.test"
        try:
            response = self.client.post("/billing/admin/subscriptions/grant", headers=self.headers, json=grant)
        finally:
            if previous is None:
                os.environ.pop("PLATFORM_ADMIN_EMAILS", None)
            else:
                os.environ["PLATFORM_ADMIN_EMAILS"] = previous
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertTrue(can_use_feature(self.workspace_id, "can_forecast", self.db))

    def test_customers_cannot_edit_plan_catalog(self):
        payload = {"name": "Free", "monthly_price_cents": 0, "annual_price_cents": 0,
                   "limits": {"query_count": -1, "upload_count": -1}, "features": {"can_forecast": True}}
        self.assertEqual(self.client.post("/billing/admin/plans/free", headers=self.headers, json=payload).status_code, 404)
        self.assertEqual(self.client.patch("/billing/admin/plans/pro/disable", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post("/billing/admin/plans/seed", headers=self.headers).status_code, 404)

    def test_client_cannot_choose_paid_plan_tier(self):
        resp = self.client.post("/workspaces", headers=self.headers, json={"name": "Free Enterprise?", "plan_tier": "enterprise"})
        self.assertEqual(resp.status_code, 403, resp.text)
        resp = self.client.put(f"/workspaces/{self.workspace_id}", headers=self.headers, json={"plan_tier": "enterprise"})
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_canceled_paid_subscription_falls_back_to_free_limits(self):
        from core.subscriptions import ensure_workspace_subscription, quota_snapshots
        from core.usage import effective_plan

        sub = ensure_workspace_subscription(self.workspace_id, self.db)
        sub.plan_id = "pro"
        sub.status = "canceled"
        self.db.commit()
        plan_id, limits, features, status = effective_plan(self.workspace_id, self.db)
        self.assertEqual(plan_id, "free")
        self.assertEqual(status, "canceled")
        self.assertFalse(features["can_forecast"])
        self.assertNotEqual(limits["query_count"], -1)
        self.assertEqual(quota_snapshots(self.workspace_id, self.db)["query_count"].limit, limits["query_count"])

    def test_quota_enforcement_blocks_over_limit(self):
        self.db.add(UsageStats(
            id=str(uuid.uuid4()),
            workspace_id=self.workspace_id,
            period="2099-01",
            upload_count=0,
        ))
        self.db.commit()

        # Make the current-period limit tiny and assert the shared layer blocks.
        limit = self.db.query(PlanLimit).filter(
            PlanLimit.plan_id == "free",
            PlanLimit.metric == "upload_count",
        ).first()
        limit.limit_value = 0
        self.db.commit()

        with self.assertRaises(Exception) as ctx:
            enforce_quota(self.workspace_id, "upload", self.db)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 429)

    def test_subscription_api_exposes_state_without_payment_routes(self):
        current = self.client.get("/billing/current", headers=self.headers)
        self.assertEqual(current.status_code, 200, current.text)
        payload = current.json()
        self.assertEqual(payload["workspace_id"], self.workspace_id)
        self.assertIn("features", payload)
        self.assertIn("remaining_quota", payload)

        plans = self.client.get("/billing/plans")
        self.assertEqual(plans.status_code, 200)
        self.assertGreaterEqual(len(plans.json()["plans"]), 4)


if __name__ == "__main__":
    unittest.main()
