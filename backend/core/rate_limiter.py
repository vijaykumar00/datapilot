"""Shared rate limiter for DataPilot.

Redis is the production backend. Development and tests may use the in-process
memory backend, but production Redis failures fail closed and are exposed by
the readiness probe.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Protocol, runtime_checkable

logger = logging.getLogger("datapilot.rate_limiter")

PRODUCTION_ENVS = {"production", "prod"}
TRUTHY = {"1", "true", "yes", "on"}


def _app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").strip().lower()


def _is_production() -> bool:
    return _app_env() in PRODUCTION_ENVS


def _window() -> int:
    try:
        return max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
    except (ValueError, TypeError):
        return 60


def _max_requests() -> int:
    try:
        return max(1, int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100")))
    except (ValueError, TypeError):
        return 100


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


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


def _redis_connect_timeout() -> float:
    return _timeout("REDIS_CONNECT_TIMEOUT", 1.0)


def _redis_socket_timeout() -> float:
    return _timeout("REDIS_SOCKET_TIMEOUT", 1.0)


def _fail_open_enabled() -> bool:
    if _is_production():
        return False
    return os.getenv("RATE_LIMITER_FAIL_OPEN", "true").strip().lower() in TRUTHY


@runtime_checkable
class RateLimiterBackend(Protocol):
    """Interface every rate limiter backend must satisfy."""

    def is_allowed(
        self,
        ip: str,
        scope: str = "global",
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ) -> bool:
        """Return True if the request should be allowed."""
        ...

    @property
    def backend_name(self) -> str:
        """Human-readable backend name."""
        ...


class InMemoryRateLimiter:
    """Sliding-window in-process limiter for development and tests."""

    def __init__(
        self,
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ):
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(
        self,
        ip: str,
        scope: str = "global",
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ) -> bool:
        now = time.monotonic()
        window = window_seconds if window_seconds is not None else self._window
        limit = max_requests if max_requests is not None else self._max
        key = f"{scope}:{ip}"
        cutoff = now - window
        self._history[key] = [t for t in self._history[key] if t > cutoff]

        if len(self._history[key]) >= limit:
            return False

        self._history[key].append(now)
        return True

    @property
    def backend_name(self) -> str:
        return "memory"


class RedisRateLimiter:
    """Redis INCR + EXPIRE sliding-window limiter."""

    def __init__(
        self,
        redis_url: str | None = None,
        window_seconds: int | None = None,
        max_requests: int | None = None,
        env_label: str | None = None,
        fail_open: bool | None = None,
        connect_timeout: float | None = None,
        socket_timeout: float | None = None,
    ):
        self._url = redis_url or _redis_url()
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._env = env_label or _env_label()
        self._fail_open = _fail_open_enabled() if fail_open is None else fail_open
        self._connect_timeout = connect_timeout if connect_timeout is not None else _redis_connect_timeout()
        self._socket_timeout = socket_timeout if socket_timeout is not None else _redis_socket_timeout()
        self._redis = None
        self._unavailable_logged = False
        self._last_error: str | None = None

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis  # type: ignore

            self._redis = redis.Redis.from_url(
                self._url,
                socket_connect_timeout=self._connect_timeout,
                socket_timeout=self._socket_timeout,
            )
            self._redis.ping()
            self._last_error = None
            self._unavailable_logged = False
            logger.info("Redis rate limiter connected.")
        except ImportError as exc:
            self._record_unavailable(f"redis package is not installed: {exc}")
        except Exception as exc:
            self._record_unavailable(f"Redis unavailable: {exc}")
        return self._redis

    def _record_unavailable(self, message: str) -> None:
        self._last_error = message
        if not self._unavailable_logged:
            mode = "failing open" if self._fail_open else "failing closed"
            logger.warning("%s; rate limiter %s.", message, mode)
            self._unavailable_logged = True
        self._redis = None

    def _key(self, ip: str, epoch_second: int, scope: str = "global") -> str:
        if scope == "global":
            return f"dp:{self._env}:rl:{ip}:{epoch_second}"
        return f"dp:{self._env}:rl:{scope}:{ip}:{epoch_second}"

    def is_allowed(
        self,
        ip: str,
        scope: str = "global",
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ) -> bool:
        r = self._get_redis()
        if r is None:
            return self._fail_open

        now = int(time.time())
        window = window_seconds if window_seconds is not None else self._window
        limit = max_requests if max_requests is not None else self._max
        window_start = now - window

        try:
            pipe = r.pipeline(transaction=False)
            for bucket in range(window_start, now + 1):
                pipe.get(self._key(ip, bucket, scope))
            results = pipe.execute()

            total = sum(int(v) for v in results if v is not None)
            if total >= limit:
                return False

            current_key = self._key(ip, now, scope)
            pipe2 = r.pipeline(transaction=True)
            pipe2.incr(current_key)
            pipe2.expire(current_key, window * 2)
            pipe2.execute()
            self._last_error = None
            return True

        except Exception as exc:
            self._record_unavailable(f"Redis rate limiter error: {exc}")
            return self._fail_open

    def ping(self) -> bool:
        r = self._get_redis()
        if r is None:
            return False
        try:
            r.ping()
            self._last_error = None
            return True
        except Exception as exc:
            self._record_unavailable(f"Redis ping failed: {exc}")
            return False

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def fail_open(self) -> bool:
        return self._fail_open

    @property
    def backend_name(self) -> str:
        return "redis"


_limiter_instance: RateLimiterBackend | None = None


def get_rate_limiter() -> RateLimiterBackend:
    """Return the process-global rate limiter."""
    global _limiter_instance
    if _limiter_instance is not None:
        return _limiter_instance

    backend = _backend()
    if backend == "memory":
        logger.info("Rate limiter: using in-memory backend.")
        _limiter_instance = InMemoryRateLimiter()
    else:
        _limiter_instance = RedisRateLimiter()

    return _limiter_instance


def reset_rate_limiter() -> None:
    """Reset the singleton for tests and runtime reconfiguration."""
    global _limiter_instance
    _limiter_instance = None


PATH_LIMITS = (
    ("/auth/login", "auth_login", "RATE_LIMIT_AUTH_LOGIN_MAX_REQUESTS", 10, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300),
    ("/auth/signup", "auth_signup", "RATE_LIMIT_AUTH_SIGNUP_MAX_REQUESTS", 5, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300),
    ("/auth/oauth", "auth_oauth", "RATE_LIMIT_AUTH_OAUTH_MAX_REQUESTS", 20, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300),
    ("/auth/otp/request", "auth_otp", "RATE_LIMIT_AUTH_OTP_MAX_REQUESTS", 5, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300),
    ("/auth/otp/verify", "auth_otp", "RATE_LIMIT_AUTH_OTP_MAX_REQUESTS", 10, "RATE_LIMIT_AUTH_WINDOW_SECONDS", 300),
    ("/auth/forgot-password", "auth_reset", "RATE_LIMIT_PASSWORD_RESET_MAX_REQUESTS", 5, "RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS", 900),
    ("/auth/reset-password", "auth_reset", "RATE_LIMIT_PASSWORD_RESET_MAX_REQUESTS", 5, "RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS", 900),
    ("/guest/session", "guest_session", "RATE_LIMIT_GUEST_SESSION_MAX_REQUESTS", 20, "RATE_LIMIT_GUEST_SESSION_WINDOW_SECONDS", 3600),
    ("/upload", "upload", "RATE_LIMIT_UPLOAD_MAX_REQUESTS", 20, "RATE_LIMIT_UPLOAD_WINDOW_SECONDS", 3600),
    ("/chat/stream", "chat", "RATE_LIMIT_CHAT_MAX_REQUESTS", 60, "RATE_LIMIT_CHAT_WINDOW_SECONDS", 60),
    ("/reports", "reports", "RATE_LIMIT_REPORT_MAX_REQUESTS", 30, "RATE_LIMIT_REPORT_WINDOW_SECONDS", 3600),
    ("/report", "reports", "RATE_LIMIT_REPORT_MAX_REQUESTS", 30, "RATE_LIMIT_REPORT_WINDOW_SECONDS", 3600),
    ("/export", "exports", "RATE_LIMIT_EXPORT_MAX_REQUESTS", 30, "RATE_LIMIT_EXPORT_WINDOW_SECONDS", 3600),
    ("/billing", "billing", "RATE_LIMIT_BILLING_MAX_REQUESTS", 60, "RATE_LIMIT_BILLING_WINDOW_SECONDS", 60),
    ("/user/api-keys", "api_keys", "RATE_LIMIT_API_KEY_MAX_REQUESTS", 30, "RATE_LIMIT_API_KEY_WINDOW_SECONDS", 300),
)


def limit_for_path(path: str = "") -> tuple[str, int, int]:
    """Return rate-limit scope, window, and max request count for a route."""
    normalized = path or ""
    for prefix, scope, max_env, max_default, window_env, window_default in PATH_LIMITS:
        if normalized.startswith(prefix):
            return (
                scope,
                _int_env(window_env, window_default),
                _int_env(max_env, max_default),
            )
    return "global", _window(), _max_requests()


def check_rate_limit(ip: str, path: str = "") -> bool:
    """Return True when the request should be allowed."""
    scope, window, max_requests = limit_for_path(path)
    return get_rate_limiter().is_allowed(
        ip,
        scope=scope,
        window_seconds=window,
        max_requests=max_requests,
    )


def rate_limiter_health() -> dict[str, object]:
    """Return readiness details for the configured rate limiter."""
    limiter = get_rate_limiter()
    status: dict[str, object] = {
        "backend": limiter.backend_name,
        "required": _is_production(),
        "ok": True,
        "detail": "ok",
    }

    if isinstance(limiter, InMemoryRateLimiter):
        if _is_production():
            status["ok"] = False
            status["detail"] = "in-memory rate limiting is not allowed in production"
        else:
            status["detail"] = "in-memory development limiter"
        return status

    if isinstance(limiter, RedisRateLimiter):
        ok = limiter.ping()
        status["ok"] = ok or (not _is_production() and limiter.fail_open)
        status["fail_open"] = limiter.fail_open
        if ok:
            status["detail"] = "redis connected"
        elif limiter.fail_open and not _is_production():
            status["detail"] = f"{limiter.last_error or 'redis unavailable'}; development fail-open"
        else:
            status["detail"] = limiter.last_error or "redis unavailable"
        return status

    status["ok"] = False
    status["detail"] = "unknown rate limiter backend"
    return status
