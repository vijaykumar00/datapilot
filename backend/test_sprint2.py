import unittest
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Set test environment database to a separate temporary SQLite file
TEST_DB_PATH = Path(__file__).parent / "test_datapilot.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"

from fastapi.testclient import TestClient
from main import app
from core.db import get_db, engine
from core.models import Base, User, RefreshToken, EmailVerificationToken, PasswordResetToken

class TestSprint2Auth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Delete test db if it exists to ensure a clean run
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except Exception:
                pass
        
        # Trigger database migrations manually
        from core.db import init_db
        init_db()
        
        # Trigger startup events (like init_db which runs migrations)
        cls.client = TestClient(app)


    @classmethod
    def tearDownClass(cls):
        # Clean up the test database file
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except Exception:
                pass


    def setUp(self):
        # Clear database between tests
        db = next(get_db())
        db.query(RefreshToken).delete()
        db.query(EmailVerificationToken).delete()
        db.query(PasswordResetToken).delete()
        db.query(User).delete()
        db.commit()
        db.close()

    def test_signup_login_refresh_logout_flow(self):
        db = next(get_db())

        # 1. Signup
        signup_data = {
            "email": "test@datapilot.ai",
            "password": "SecurePassword123!",
            "workspace_name": "My Workspace"
        }
        res = self.client.post("/auth/signup", json=signup_data)
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()["success"])
        user_id = res.json()["user_id"]
        workspace_id = res.json()["workspace_id"]

        # Retrieve the generated email verification token hash from the DB
        verify_token_entry = db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).first()
        self.assertIsNotNone(verify_token_entry)

        # 2. Login fails before email verification? Wait, the requirement says we can log in, but let's test verify-email first.
        # Since we have the verification token hash, we can't easily guess the raw token.
        # But we can look at signup's console print output, or we can mock it.
        # Actually, in auth_routes.py signup(), we generate a raw_verify_token and store its hash.
        # Let's inspect the code: we store the hash.
        # To test verification, we can insert a known raw token hash directly in the test database.
        raw_verify = "test_verify_token_123"
        hashed_verify = hash_token_for_test(raw_verify)
        verify_token_entry.token_hash = hashed_verify
        db.commit()

        # Call verify-email
        res = self.client.post("/auth/verify-email", json={"token": raw_verify})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Check user is verified
        user = db.query(User).filter(User.user_id == user_id).first()
        self.assertTrue(user.email_verified)

        # 3. Login
        login_data = {
            "email": "test@datapilot.ai",
            "password": "SecurePassword123!"
        }
        res = self.client.post("/auth/login", json=login_data)
        self.assertEqual(res.status_code, 200)
        token_data = res.json()
        self.assertIn("access_token", token_data)
        self.assertIn("refresh_token", token_data)
        self.assertEqual(token_data["workspace_id"], workspace_id)

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        # 4. Refresh Token Rotation
        # Call refresh endpoint
        res = self.client.post("/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(res.status_code, 200)
        refresh_data = res.json()
        self.assertIn("access_token", refresh_data)
        self.assertIn("refresh_token", refresh_data)
        
        new_access_token = refresh_data["access_token"]
        new_refresh_token = refresh_data["refresh_token"]

        # Verify old refresh token is now revoked
        old_hashed = hash_token_for_test(refresh_token)
        old_token_entry = db.query(RefreshToken).filter(RefreshToken.token_hash == old_hashed).first()
        self.assertTrue(old_token_entry.revoked)

        # 5. Forgot and Reset Password Flow
        # Request password reset
        res = self.client.post("/auth/forgot-password", json={"email": "test@datapilot.ai"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Retrieve and override hash for test
        reset_entry = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).first()
        self.assertIsNotNone(reset_entry)
        raw_reset = "test_reset_token_456"
        reset_entry.token_hash = hash_token_for_test(raw_reset)
        db.commit()

        # Reset Password
        res = self.client.post("/auth/reset-password", json={
            "token": raw_reset,
            "new_password": "NewSecurePassword456!"
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Try logging in with old password (fails)
        res = self.client.post("/auth/login", json=login_data)
        self.assertEqual(res.status_code, 401)

        # Login with new password (success)
        res = self.client.post("/auth/login", json={
            "email": "test@datapilot.ai",
            "password": "NewSecurePassword456!"
        })
        self.assertEqual(res.status_code, 200)
        new_login_data = res.json()
        new_access_token_device = new_login_data["access_token"]
        new_refresh_token_device = new_login_data["refresh_token"]

        # 6. Logout
        res = self.client.post("/auth/logout", json={"refresh_token": new_refresh_token_device})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Check token is revoked
        device_hashed = hash_token_for_test(new_refresh_token_device)
        device_token_entry = db.query(RefreshToken).filter(RefreshToken.token_hash == device_hashed).first()
        self.assertTrue(device_token_entry.revoked)

        # 7. Logout-all-devices
        # Let's log in again to get active tokens
        res = self.client.post("/auth/login", json={
            "email": "test@datapilot.ai",
            "password": "NewSecurePassword456!"
        })
        login_all_data = res.json()
        current_access = login_all_data["access_token"]
        current_refresh = login_all_data["refresh_token"]

        # Call logout-all
        res = self.client.post(
            "/auth/logout-all",
            headers={"Authorization": f"Bearer {current_access}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Verify all refresh tokens are revoked
        active_tokens = db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False
        ).all()
        self.assertEqual(len(active_tokens), 0)

        db.close()

def hash_token_for_test(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    unittest.main()
