"""Pytest bootstrap: isolated database/storage and migrated schema for every run.

CI runs this suite against SQLite AND PostgreSQL (set DATABASE_URL); the schema
is always created with Alembic (never create_all), exactly like production.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="dp_tests_")

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-1234567890-1234567890-abcdef")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(_TMP, 'test.db')}")
os.environ.setdefault("RATE_LIMITER_BACKEND", "memory")
os.environ.setdefault("STORAGE_PROVIDER", "local")
os.environ.setdefault("LOCAL_STORAGE_DIR", os.path.join(_TMP, "storage"))
os.environ.setdefault("STRIPE_BILLING_ENABLED", "false")
os.environ.setdefault("PARSE_IN_SUBPROCESS", "false")
os.environ.setdefault("JOB_EXECUTION_MODE", "inline")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcy0hISE=")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("GEMINI_API_KEY", "test-key-never-sent")
os.environ.setdefault("RATE_LIMIT_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_UPLOAD_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_CHAT_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_GUEST_SESSION_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_EXPORT_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_REPORT_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_AUTH_LOGIN_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_AUTH_SIGNUP_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_AUTH_REFRESH_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_BILLING_MAX_REQUESTS", "100000")
os.environ.setdefault("RATE_LIMIT_WEBHOOK_MAX_REQUESTS", "100000")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.db import run_migrations, seed_plans  # noqa: E402

run_migrations()
seed_plans()
