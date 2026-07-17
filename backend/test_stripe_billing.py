import os
import sys
import unittest
import uuid
import datetime
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET", "stripe-billing-test-secret-1234567890")
os.environ["STRIPE_SECRET_KEY"] = "sk_test_unit"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_unit"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_unit"
os.environ["STRIPE_ENVIRONMENT"] = "test"
os.environ["STRIPE_PRICE_PRO_MONTHLY"] = "price_pro_monthly"
os.environ["STRIPE_PRICE_PRO_ANNUAL"] = "price_pro_annual"
os.environ["STRIPE_PRICE_TEAM_MONTHLY"] = "price_team_monthly"
os.environ["STRIPE_PRICE_TEAM_ANNUAL"] = "price_team_annual"
TEST_DB_PATH = BACKEND_DIR / "test_stripe_billing.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"

from fastapi.testclient import TestClient

from main import app
from core.auth import create_access_token, hash_password
from core.db import SessionLocal, init_db
from core.models import BillingCustomer, Subscription, User, WebhookEvent, Workspace, WorkspaceMember, WorkspaceSubscription
from core.subscriptions import seed_subscription_catalog, subscription_summary


class TestStripeBilling(unittest.TestCase):
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
            email=f"stripe-{self.user_id}@datapilot.test",
            password_hash=hash_password("SecurePassword123!"),
            email_verified=True,
        )
        workspace = Workspace(
            workspace_id=self.workspace_id,
            name="Stripe Test Workspace",
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

    def test_checkout_creation_uses_internal_plan_mapping(self):
        with patch("core.stripe_billing.stripe.Customer.create", return_value={"id": f"cus_{self.workspace_id}"}), \
             patch("core.stripe_billing.stripe.checkout.Session.create", return_value={"id": f"cs_{self.workspace_id}", "url": "https://checkout.stripe.test/session"}) as checkout:
            response = self.client.post(
                "/billing/checkout",
                headers=self.headers,
                json={"plan_id": "pro", "interval": "monthly"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        call_kwargs = checkout.call_args.kwargs
        self.assertEqual(call_kwargs["line_items"][0]["price"], "price_pro_monthly")
        self.assertEqual(call_kwargs["metadata"]["plan_id"], "pro")
        self.assertEqual(call_kwargs["client_reference_id"], self.workspace_id)

    def test_duplicate_subscription_is_rejected(self):
        self.db.add(BillingCustomer(id=str(uuid.uuid4()), workspace_id=self.workspace_id, stripe_customer_id=f"cus_dup_{self.workspace_id}"))
        self.db.add(Subscription(
            id=str(uuid.uuid4()),
            workspace_id=self.workspace_id,
            stripe_subscription_id=f"sub_dup_{self.workspace_id}",
            status="active",
            plan_id="pro",
            current_period_start=datetime.datetime.utcnow(),
            current_period_end=datetime.datetime.utcnow(),
            cancel_at_period_end=False,
        ))
        self.db.commit()

        response = self.client.post(
            "/billing/checkout",
            headers=self.headers,
            json={"plan_id": "pro", "interval": "monthly"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "DUPLICATE_SUBSCRIPTION")

    def test_upgrade_or_downgrade_requires_portal_to_avoid_duplicates(self):
        self.db.add(BillingCustomer(id=str(uuid.uuid4()), workspace_id=self.workspace_id, stripe_customer_id=f"cus_change_{self.workspace_id}"))
        self.db.add(Subscription(
            id=str(uuid.uuid4()),
            workspace_id=self.workspace_id,
            stripe_subscription_id=f"sub_change_{self.workspace_id}",
            status="active",
            plan_id="pro",
            current_period_start=datetime.datetime.utcnow(),
            current_period_end=datetime.datetime.utcnow(),
            cancel_at_period_end=False,
        ))
        self.db.commit()

        response = self.client.post(
            "/billing/checkout",
            headers=self.headers,
            json={"plan_id": "team", "interval": "monthly"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "SUBSCRIPTION_CHANGE_REQUIRES_PORTAL")

    def test_customer_portal_session_creation(self):
        customer_id = f"cus_portal_{self.workspace_id}"
        self.db.add(BillingCustomer(id=str(uuid.uuid4()), workspace_id=self.workspace_id, stripe_customer_id=customer_id))
        self.db.commit()

        with patch("core.stripe_billing.stripe.billing_portal.Session.create", return_value={"id": "bps_unit", "url": "https://billing.stripe.test/session"}) as portal:
            response = self.client.post("/billing/portal", headers=self.headers, json={})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(portal.call_args.kwargs["customer"], customer_id)
        self.assertIn("portal_url", response.json())

    def test_webhook_checkout_completed_syncs_subscription(self):
        event_id = f"evt_checkout_{self.workspace_id}"
        sub_id = f"sub_checkout_{self.workspace_id}"
        customer_id = f"cus_checkout_{self.workspace_id}"
        event = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_unit",
                    "subscription": sub_id,
                    "customer": customer_id,
                    "client_reference_id": self.workspace_id,
                    "metadata": {"workspace_id": self.workspace_id, "plan_id": "pro"},
                }
            },
        }
        subscription = {
            "id": sub_id,
            "customer": customer_id,
            "status": "active",
            "current_period_start": 1893456000,
            "current_period_end": 1896134400,
            "cancel_at_period_end": False,
            "metadata": {"workspace_id": self.workspace_id, "plan_id": "pro"},
        }

        with patch("core.stripe_billing.stripe.Webhook.construct_event", return_value=event), \
             patch("core.stripe_billing.stripe.Subscription.retrieve", return_value=subscription):
            response = self.client.post(
                "/billing/webhook",
                content=b"{}",
                headers={"Stripe-Signature": "sig"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        summary = subscription_summary(self.workspace_id, self.db)
        self.assertEqual(summary["subscription"]["plan_id"], "pro")
        self.assertEqual(summary["billing"]["payment_provider"], "stripe")

    def test_duplicate_webhook_is_idempotent(self):
        event_id = f"evt_duplicate_{self.workspace_id}"
        self.db.add(WebhookEvent(id=str(uuid.uuid4()), stripe_event_id=event_id, processed=True))
        self.db.commit()
        event = {"id": event_id, "type": "invoice.paid", "data": {"object": {}}}

        with patch("core.stripe_billing.stripe.Webhook.construct_event", return_value=event):
            response = self.client.post(
                "/billing/webhook",
                content=b"{}",
                headers={"Stripe-Signature": "sig"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "Already processed")

    def test_invoice_payment_failed_updates_payment_status(self):
        customer_id = f"cus_invoice_{self.workspace_id}"
        sub_id = f"sub_invoice_{self.workspace_id}"
        self.db.add(BillingCustomer(id=str(uuid.uuid4()), workspace_id=self.workspace_id, stripe_customer_id=customer_id))
        self.db.add(Subscription(
            id=str(uuid.uuid4()),
            workspace_id=self.workspace_id,
            stripe_subscription_id=sub_id,
            status="active",
            plan_id="pro",
            current_period_start=datetime.datetime.utcnow(),
            current_period_end=datetime.datetime.utcnow(),
            cancel_at_period_end=False,
        ))
        self.db.commit()
        event = {
            "id": f"evt_payment_failed_{self.workspace_id}",
            "type": "invoice.payment_failed",
            "data": {"object": {"subscription": sub_id, "customer": customer_id}},
        }

        with patch("core.stripe_billing.stripe.Webhook.construct_event", return_value=event):
            response = self.client.post(
                "/billing/webhook",
                content=b"{}",
                headers={"Stripe-Signature": "sig"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        ws_sub = self.db.query(WorkspaceSubscription).filter(WorkspaceSubscription.workspace_id == self.workspace_id).first()
        self.assertIn("payment_failed", ws_sub.metadata_json)


if __name__ == "__main__":
    unittest.main()
