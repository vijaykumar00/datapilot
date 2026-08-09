"""Validate DataPilot backend environment before production startup."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse


REQUIRED_PRODUCTION = {
    "JWT_SECRET": "At least 32 characters; 64 random bytes hex encoded is recommended.",
    "DATABASE_URL": "PostgreSQL connection URL for production.",
    "ALLOWED_ORIGINS": "Comma-separated HTTPS frontend origins.",
    "REDIS_URL": "Redis connection URL for shared rate limiting.",
}

OPTIONAL_SECRETS = {
    "ENCRYPTION_KEY": "Required before storing user API keys in production.",
    "GEMINI_API_KEY": "Required when AI_PROVIDER=gemini.",
    "OPENAI_API_KEY": "Required when AI_PROVIDER=openai.",
    "ANTHROPIC_API_KEY": "Required when AI_PROVIDER=claude.",
    "STRIPE_SECRET_KEY": "Required when Stripe billing is enabled.",
    "STRIPE_PUBLISHABLE_KEY": "Required when Stripe billing is enabled.",
    "STRIPE_WEBHOOK_SECRET": "Required when Stripe webhooks are enabled.",
}


def _has_localhost(value: str) -> bool:
    lowered = value.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered or "0.0.0.0" in lowered or "[::1]" in lowered


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate(env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    app_env = env.get("APP_ENV", "development").lower()
    production = app_env in {"production", "prod"}

    if production:
        for key, reason in REQUIRED_PRODUCTION.items():
            if not env.get(key):
                errors.append(f"{key} is required in production. {reason}")

    jwt_secret = env.get("JWT_SECRET", "")
    if jwt_secret and len(jwt_secret) < 32:
        errors.append("JWT_SECRET must be at least 32 characters.")

    database_url = env.get("DATABASE_URL", "")
    if production and database_url:
        parsed = urlparse(database_url)
        if not parsed.scheme.startswith("postgresql"):
            errors.append("DATABASE_URL must use PostgreSQL in production.")
        if _has_localhost(database_url):
            errors.append("DATABASE_URL must not point at localhost in production.")

    allowed_origins = env.get("ALLOWED_ORIGINS", "")
    if production and allowed_origins:
        for origin in [item.strip() for item in allowed_origins.split(",") if item.strip()]:
            if not origin.startswith("https://"):
                errors.append(f"ALLOWED_ORIGINS entry must be HTTPS in production: {origin}")
            if _has_localhost(origin):
                errors.append(f"ALLOWED_ORIGINS must not contain localhost in production: {origin}")

    if production:
        rate_limiter_backend = env.get("RATE_LIMITER_BACKEND", "redis").lower()
        if rate_limiter_backend != "redis":
            errors.append("RATE_LIMITER_BACKEND must be redis in production.")
        if _truthy(env.get("RATE_LIMITER_FAIL_OPEN")):
            errors.append("RATE_LIMITER_FAIL_OPEN must not be enabled in production.")
        redis_url = env.get("REDIS_URL", "")
        if redis_url:
            parsed = urlparse(redis_url)
            if parsed.scheme not in {"redis", "rediss"}:
                errors.append("REDIS_URL must use redis:// or rediss://.")
            if _has_localhost(redis_url):
                errors.append("REDIS_URL must not point at localhost in production.")

        storage_provider = env.get("STORAGE_PROVIDER", "local").lower()
        if storage_provider not in {"s3", "r2", "minio", "local"}:
            errors.append("STORAGE_PROVIDER must be one of: s3, r2, minio, local.")
        if storage_provider == "local" and not _truthy(env.get("ALLOW_LOCAL_STORAGE_IN_PRODUCTION")):
            errors.append("STORAGE_PROVIDER=local is not allowed in production without ALLOW_LOCAL_STORAGE_IN_PRODUCTION=true.")
        if storage_provider in {"s3", "r2", "minio"} and not env.get("S3_BUCKET"):
            errors.append("S3_BUCKET is required when STORAGE_PROVIDER uses an S3-compatible backend.")

    provider = env.get("AI_PROVIDER", "gemini").lower()
    provider_key = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }.get(provider)
    if production and provider_key and not env.get(provider_key):
        errors.append(f"{provider_key} is required when AI_PROVIDER={provider}.")

    stripe_enabled = env.get("STRIPE_BILLING_ENABLED", "true").lower() in {"1", "true", "yes"}
    if production and stripe_enabled:
        for key in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"):
            if not env.get(key):
                errors.append(f"{key} is required when Stripe billing is enabled in production.")
        stripe_environment = env.get("STRIPE_ENVIRONMENT", "test").lower()
        if stripe_environment not in {"test", "live"}:
            errors.append("STRIPE_ENVIRONMENT must be either test or live.")
        if stripe_environment == "live" and env.get("STRIPE_SECRET_KEY", "").startswith("sk_test_"):
            errors.append("STRIPE_ENVIRONMENT=live cannot use a test secret key.")
        for plan_id in ("PRO", "TEAM"):
            for interval in ("MONTHLY", "ANNUAL"):
                key = f"STRIPE_PRICE_{plan_id}_{interval}"
                if not env.get(key):
                    errors.append(f"{key} is required for Stripe plan mapping.")

    return errors


def main() -> int:
    errors = validate(dict(os.environ))
    if errors:
        print("Environment validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Environment validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
