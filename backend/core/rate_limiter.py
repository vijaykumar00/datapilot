"""Shared rate limiter for DataPilot.

Algorithm: sliding-window *counter* (current + weighted previous fixed window).
Each check is ONE Redis round trip of three cheap commands (INCR, EXPIRE, GET)
regardless of the window length — the previous implementation issued one GET
per second of the window (3,601 commands for hourly scopes).

Identity: requests are limited per authenticated user, per guest session or,
for anonymous/auth endpoints, per client IP (the real client IP forwarded by
the trusted reverse proxy — see uvicorn ``--forwarded-allow-ips``).

Failure policy: if Redis is unreachable the limiter does NOT fail open and does
NOT block every user; it opens a short circuit breaker and enforces the same
limits with a per-process in-memory limiter, logs/metrics the failure and
reports not-ready on ``/ready``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import defaultdict
from typing import Protocol, runtime_checkable

logger = logging.getLogger("datapilot.rate_limiter")

PRODUCTION_ENVS = {"production", "prod"}


def _app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").strip().lower()


def _is_production() -> bool:
    return _app_env() in PRODUCTION_ENVS


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


def _window() -> int:
    return _int_env("RATE_LIMIT_WINDOW_SECONDS", 60)


def _max_requests() -> int:
    return _int_env("RATE_LIMIT_MAX_REQUESTS", 300)


def _backend() -> str:
    return os.getenv("RATE_LIMITER_BACKEND", "redis").strip().lower()


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _env_label() -> str:
    return os.getenv("RATE_LIMITER_ENV_LABEL") or _app_env()


def _timeout(name: str, default: float) -> float:
    try:
        return max(0.05, float(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


@runtime_checkable
class RateLimiterBackend(Protocol):
    def is_allowed(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                   max_requests: int | None = None) -> bool: ...

    async def is_allowed_async(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                               max_requests: int | None = None) -> bool: ...

    @property
    def backend_name(self) -> str: ...


class InMemoryRateLimiter:
    """Sliding-window in-process limiter (development, tests and Redis-outage fallback)."""

    def __init__(self, window_seconds: int | None = None, max_requests: int | None = None):
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def is_allowed(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                   max_requests: int | None = None) -> bool:
        now = time.monotonic()
        window = window_seconds if window_seconds is not None else self._window
        limit = max_requests if max_requests is not None else self._max
        key = f"{scope}:{ip}"
        cutoff = now - window
        with self._lock:
            hist = [t for t in self._history.get(key, []) if t > cutoff]
            allowed = len(hist) < limit
            if allowed:
                hist.append(now)
            self._history[key] = hist
            if now - self._last_sweep > 300:  # bound memory: drop idle keys
                self._last_sweep = now
                for k in [k for k, v in self._history.items() if not v or v[-1] < now - 3600]:
                    self._history.pop(k, None)
        return allowed

    async def is_allowed_async(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                               max_requests: int | None = None) -> bool:
        return self.is_allowed(ip, scope, window_seconds, max_requests)

    @property
    def backend_name(self) -> str:
        return "memory"


class RedisRateLimiter:
    """Redis sliding-window-counter limiter with circuit breaker + local fallback."""

    def __init__(
        self,
        redis_url: str | None = None,
        window_seconds: int | None = None,
        max_requests: int | None = None,
        env_label: str | None = None,
        fail_open: bool | None = None,  # kept for signature compatibility; outages use the local fallback
        connect_timeout: float | None = None,
        socket_timeout: float | None = None,
    ):
        self._url = redis_url or _redis_url()
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._env = env_label or _env_label()
        self._connect_timeout = connect_timeout if connect_timeout is not None else _timeout("REDIS_CONNECT_TIMEOUT", 0.5)
        self._socket_timeout = socket_timeout if socket_timeout is not None else _timeout("REDIS_SOCKET_TIMEOUT", 0.5)
        self._sync_client = None
        self._async_client = None
        self._fallback = InMemoryRateLimiter(self._window, self._max)
        self._circuit_open_until = 0.0
        self._last_error: str | None = None
        self._lock = threading.Lock()

    # ── Keys ──────────────────────────────────────────────────────────────
    def _key(self, ident: str, bucket: int, scope: str = "global") -> str:
        return f"dp:{self._env}:rl:{scope}:{ident}:{bucket}"

    @staticmethod
    def _decide(cur: int, prev: int, limit: int, elapsed_fraction: float) -> bool:
        estimated = prev * (1.0 - elapsed_fraction) + cur
        return estimated <= limit

    def _record_failure(self, exc: Exception) -> None:
        self._last_error = f"Redis rate limiter error: {exc}"
        self._circuit_open_until = time.monotonic() + _int_env("RATE_LIMITER_CIRCUIT_SECONDS", 5)
        logger.warning("%s; using in-process fallback limiter.", self._last_error)
        try:
            from core.observability import RATE_LIMITER_ERRORS
            RATE_LIMITER_ERRORS.inc()
        except Exception:
            pass

    def _circuit_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    # ── Sync API (scripts/tests) ──────────────────────────────────────────
    def _get_sync(self):
        if self._sync_client is None:
            import redis  # type: ignore

            self._sync_client = redis.Redis.from_url(self._url, socket_connect_timeout=self._connect_timeout,
                                                     socket_timeout=self._socket_timeout)
        return self._sync_client

    def is_allowed(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                   max_requests: int | None = None) -> bool:
        window = window_seconds if window_seconds is not None else self._window
        limit = max_requests if max_requests is not None else self._max
        if self._circuit_open():
            return self._fallback.is_allowed(ip, scope, window, limit)
        now = time.time()
        bucket = int(now // window)
        try:
            pipe = self._get_sync().pipeline(transaction=False)
            pipe.incr(self._key(ip, bucket, scope))
            pipe.expire(self._key(ip, bucket, scope), window * 2)
            pipe.get(self._key(ip, bucket - 1, scope))
            cur, _, prev = pipe.execute()
            self._last_error = None
            return self._decide(int(cur), int(prev or 0), limit, (now % window) / window)
        except Exception as exc:
            self._sync_client = None
            self._record_failure(exc)
            return self._fallback.is_allowed(ip, scope, window, limit)

    # ── Async API (request middleware; never blocks the event loop) ───────
    def _get_async(self):
        if self._async_client is None:
            import redis.asyncio as aioredis  # type: ignore

            self._async_client = aioredis.Redis.from_url(self._url, socket_connect_timeout=self._connect_timeout,
                                                         socket_timeout=self._socket_timeout)
        return self._async_client

    async def is_allowed_async(self, ip: str, scope: str = "global", window_seconds: int | None = None,
                               max_requests: int | None = None) -> bool:
        window = window_seconds if window_seconds is not None else self._window
        limit = max_requests if max_requests is not None else self._max
        if self._circuit_open():
            return self._fallback.is_allowed(ip, scope, window, limit)
        now = time.time()
        bucket = int(now // window)
        try:
            pipe = self._get_async().pipeline(transaction=False)
            pipe.incr(self._key(ip, bucket, scope))
            pipe.expire(self._key(ip, bucket, scope), window * 2)
            pipe.get(self._key(ip, bucket - 1, scope))
            cur, _, prev = await pipe.execute()
            self._last_error = None
            return self._decide(int(cur), int(prev or 0), limit, (now % window) / window)
        except Exception as exc:
            self._async_client = None
            self._record_failure(exc)
            return self._fallback.is_allowed(ip, scope, window, limit)

    def ping(self) -> bool:
        try:
            ok = bool(self._get_sync().ping())
            self._last_error = None
            return ok
        except Exception as exc:
            self._sync_client = None
            self._last_error = f"Redis ping failed: {exc}"
            return False

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def fail_open(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "redis"


_limiter_instance: RateLimiterBackend | None = None
_instance_lock = threading.Lock()


def get_rate_limiter() -> RateLimiterBackend:
    global _limiter_instance
    if _limiter_instance is None:
        with _instance_lock:
            if _limiter_instance is None:
                if _backend() == "memory":
                    logger.info("Rate limiter: using in-memory backend.")
                    _limiter_instance = InMemoryRateLimiter()
                else:
                    _limiter_instance = RedisRateLimiter()
    return _limiter_instance


def reset_rate_limiter() -> None:
    global _limiter_instance
    _limiter_instance = None


# (path prefix, scope, max env, default max, window env, default window, keyed_by_ip_only, methods)
PATH_LIMITS = (
    ("/auth/login", "auth_login", "RATE_LIMIT_AUTH_LOGIN_MAX_REQUESTS", 10, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/auth/signup", "auth_signup", "RATE_LIMIT_AUTH_SIGNUP_MAX_REQUESTS", 5, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/auth/oauth", "auth_oauth", "RATE_LIMIT_AUTH_OAUTH_MAX_REQUESTS", 20, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/auth/otp/request", "auth_otp", "RATE_LIMIT_AUTH_OTP_MAX_REQUESTS", 5, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/auth/otp/verify", "auth_otp_verify", "RATE_LIMIT_AUTH_OTP_VERIFY_MAX_REQUESTS", 10, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/auth/forgot-password", "auth_reset", "RATE_LIMIT_PASSWORD_RESET_MAX_REQUESTS", 5, "RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS", 900, True, None),
    ("/auth/reset-password", "auth_reset", "RATE_LIMIT_PASSWORD_RESET_MAX_REQUESTS", 5, "RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS", 900, True, None),
    ("/auth/refresh", "auth_refresh", "RATE_LIMIT_AUTH_REFRESH_MAX_REQUESTS", 30, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300, True, None),
    ("/guest/session", "guest_session", "RATE_LIMIT_GUEST_SESSION_MAX_REQUESTS", 20, "RATE_LIMIT_GUEST_SESSION_WINDOW_SECONDS", 3600, True, ("POST",)),
    ("/upload", "upload", "RATE_LIMIT_UPLOAD_MAX_REQUESTS", 30, "RATE_LIMIT_UPLOAD_WINDOW_SECONDS", 3600, False, None),
    ("/chat/stream", "chat", "RATE_LIMIT_CHAT_MAX_REQUESTS", 30, "RATE_LIMIT_CHAT_WINDOW_SECONDS", 60, False, None),
    ("/report/", "reports", "RATE_LIMIT_REPORT_MAX_REQUESTS", 30, "RATE_LIMIT_REPORT_WINDOW_SECONDS", 3600, False, ("POST",)),
    ("/export", "exports", "RATE_LIMIT_EXPORT_MAX_REQUESTS", 60, "RATE_LIMIT_EXPORT_WINDOW_SECONDS", 3600, False, None),
    ("/billing/webhook", "stripe_webhook", "RATE_LIMIT_WEBHOOK_MAX_REQUESTS", 1000, "RATE_LIMIT_WEBHOOK_WINDOW_SECONDS", 60, True, None),
    ("/billing", "billing", "RATE_LIMIT_BILLING_MAX_REQUESTS", 60, "RATE_LIMIT_BILLING_WINDOW_SECONDS", 60, False, None),
    ("/user/api-keys", "api_keys", "RATE_LIMIT_API_KEY_MAX_REQUESTS", 30, "RATE_LIMIT_API_KEY_WINDOW_SECONDS", 300, False, None),
)


def limit_for_path(path: str = "", method: str | None = None) -> tuple[str, int, int]:
    """Return rate-limit scope, window, and max request count for a route."""
    scope, window, limit, _ = limit_rule(path, method)
    return scope, window, limit


def limit_rule(path: str = "", method: str | None = None) -> tuple[str, int, int, bool]:
    normalized = path or ""
    for prefix, scope, max_env, max_default, window_env, window_default, ip_only, methods in PATH_LIMITS:
        if normalized.startswith(prefix) and (methods is None or method is None or method.upper() in methods):
            return scope, _int_env(window_env, window_default), _int_env(max_env, max_default), ip_only
    return "global", _window(), _max_requests(), False


def caller_key(authorization: str | None, guest_token: str | None, client_ip: str) -> str:
    """Stable per-caller identity for rate limiting (verified JWT subject, guest token hash, or IP)."""
    if authorization and authorization.lower().startswith("bearer "):
        try:
            from core.auth import decode_access_token

            claims = decode_access_token(authorization.split(" ", 1)[1])
            if claims and claims.get("user_id"):
                return f"u:{claims['user_id']}"
        except Exception:
            pass
    if guest_token:
        return "g:" + hashlib.sha256(guest_token.encode()).hexdigest()[:24]
    return f"ip:{client_ip}"


def check_rate_limit(ip: str, path: str = "") -> bool:
    """Synchronous check (tests/scripts)."""
    scope, window, max_requests = limit_for_path(path)
    return get_rate_limiter().is_allowed(ip, scope=scope, window_seconds=window, max_requests=max_requests)


async def check_rate_limit_async(identity: str, client_ip: str, path: str, method: str) -> tuple[bool, str]:
    scope, window, max_requests, ip_only = limit_rule(path, method)
    key = f"ip:{client_ip}" if ip_only else identity
    allowed = await get_rate_limiter().is_allowed_async(key, scope=scope, window_seconds=window, max_requests=max_requests)
    if not allowed:
        try:
            from core.observability import RATE_LIMITED
            RATE_LIMITED.labels(scope).inc()
        except Exception:
            pass
    return allowed, scope


def rate_limiter_health() -> dict[str, object]:
    limiter = get_rate_limiter()
    status: dict[str, object] = {"backend": limiter.backend_name, "required": _is_production(), "ok": True, "detail": "ok"}
    if isinstance(limiter, InMemoryRateLimiter):
        if _is_production():
            status["ok"] = False
            status["detail"] = "in-memory rate limiting is not allowed in production"
        else:
            status["detail"] = "in-memory development limiter"
        return status
    if isinstance(limiter, RedisRateLimiter):
        ok = limiter.ping()
        status["ok"] = ok or not _is_production()
        status["detail"] = "redis connected" if ok else (limiter.last_error or "redis unavailable")
        if not ok:
            status["fallback"] = "in-process limiter active"
        return status
    status["ok"] = False
    status["detail"] = "unknown rate limiter backend"
    return status
