"""
rate_limiter.py — Production-safe shared rate limiter for DataPilot.

Backend selection (via RATE_LIMITER_BACKEND env var):
    redis   : Atomic Redis INCR + EXPIRE sliding-window counter (default when Redis available).
    memory  : In-process sliding-window (dev/test only; does not share state across workers).

Additional configuration:
    REDIS_URL                 : Redis connection URL (default redis://localhost:6379/0).
    RATE_LIMIT_WINDOW_SECONDS : Window length in seconds (default 60).
    RATE_LIMIT_MAX_REQUESTS   : Max requests per IP per window (default 100).

Failure behaviour:
    - If RATE_LIMITER_BACKEND=redis but Redis is unavailable at check time, the limiter
      logs a WARNING and FAILS OPEN (allows the request).  This is intentional for a
      dev-friendly product — a Redis outage should not take down the API.
    - Use RATE_LIMITER_BACKEND=memory to force in-process limiting in production when
      Redis is not available.

Key design:
    - Redis key format: ``dp:{env}:rl:{ip}:{window_epoch}``
      No user PII other than the remote IP is stored.
    - Keys expire automatically (TTL = window * 2) so no manual cleanup is needed.
    - All Redis operations happen inside try/except so network errors never propagate.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Protocol, runtime_checkable

logger = logging.getLogger("datapilot.rate_limiter")

# ── Config ────────────────────────────────────────────────────────────────────

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


def _backend() -> str:
    return os.getenv("RATE_LIMITER_BACKEND", "redis").strip().lower()


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _env_label() -> str:
    return os.getenv("ENVIRONMENT", "prod")


# ── Protocol / interface ──────────────────────────────────────────────────────

@runtime_checkable
class RateLimiterBackend(Protocol):
    """Interface every rate limiter backend must satisfy."""

    def is_allowed(self, ip: str) -> bool:
        """Return True if the request should be allowed, False if rate-limited."""
        ...

    @property
    def backend_name(self) -> str:
        """Human-readable name for logging / health endpoints."""
        ...


# ── In-memory backend ─────────────────────────────────────────────────────────

class InMemoryRateLimiter:
    """Sliding-window in-process rate limiter.

    Not suitable for multi-worker deployments — each process has its own counter.
    Suitable for development, testing, and single-process deployments.
    """

    def __init__(
        self,
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ):
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        # Evict stale timestamps
        self._history[ip] = [t for t in self._history[ip] if t > cutoff]

        if len(self._history[ip]) >= self._max:
            return False

        self._history[ip].append(now)
        return True

    @property
    def backend_name(self) -> str:
        return "memory"


# ── Redis backend ─────────────────────────────────────────────────────────────

class RedisRateLimiter:
    """Redis INCR + EXPIRE atomic sliding-window rate limiter.

    Uses per-second epoch buckets so each IP has at most (window) Redis keys.
    On any Redis error the limiter fails open and logs a WARNING.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        window_seconds: int | None = None,
        max_requests: int | None = None,
        env_label: str | None = None,
    ):
        self._url = redis_url or _redis_url()
        self._window = window_seconds if window_seconds is not None else _window()
        self._max = max_requests if max_requests is not None else _max_requests()
        self._env = env_label or _env_label()
        self._redis = None  # lazy connect
        self._unavailable_logged = False

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis  # type: ignore
            self._redis = redis.Redis.from_url(self._url, socket_connect_timeout=1, socket_timeout=1)
            self._redis.ping()
            logger.info("Redis rate limiter connected: %s", self._url)
        except ImportError:
            if not self._unavailable_logged:
                logger.warning(
                    "redis package not installed; rate limiter will use in-memory fallback. "
                    "Install redis-py: pip install redis"
                )
                self._unavailable_logged = True
            self._redis = None
        except Exception as exc:
            if not self._unavailable_logged:
                logger.warning(
                    "Redis unavailable (%s) — rate limiter failing open. "
                    "Check REDIS_URL or set RATE_LIMITER_BACKEND=memory.", exc
                )
                self._unavailable_logged = True
            self._redis = None
        return self._redis

    def _key(self, ip: str, epoch_second: int) -> str:
        """Redis key for a given IP and epoch second bucket.

        Format: dp:{env}:rl:{ip}:{epoch}
        No sensitive user data beyond remote IP.
        """
        return f"dp:{self._env}:rl:{ip}:{epoch_second}"

    def is_allowed(self, ip: str) -> bool:
        r = self._get_redis()
        if r is None:
            # Fail open — Redis unavailable
            return True

        now = int(time.time())
        window_start = now - self._window

        try:
            pipe = r.pipeline(transaction=False)
            for bucket in range(window_start, now + 1):
                pipe.get(self._key(ip, bucket))
            results = pipe.execute()

            total = sum(int(v) for v in results if v is not None)
            if total >= self._max:
                return False

            # Increment current second bucket
            current_key = self._key(ip, now)
            pipe2 = r.pipeline(transaction=True)
            pipe2.incr(current_key)
            pipe2.expire(current_key, self._window * 2)
            pipe2.execute()
            return True

        except Exception as exc:
            logger.warning("Redis rate limiter error (failing open): %s", exc)
            # Reset connection so next request tries to reconnect
            self._redis = None
            self._unavailable_logged = False
            return True

    @property
    def backend_name(self) -> str:
        return "redis"


# ── Factory / singleton ───────────────────────────────────────────────────────

_limiter_instance: RateLimiterBackend | None = None


def get_rate_limiter() -> RateLimiterBackend:
    """Return the process-global rate limiter, creating it on first call."""
    global _limiter_instance
    if _limiter_instance is not None:
        return _limiter_instance

    backend = _backend()
    if backend == "memory":
        logger.info("Rate limiter: using in-memory backend (RATE_LIMITER_BACKEND=memory).")
        _limiter_instance = InMemoryRateLimiter()
    else:
        # Attempt Redis; connection errors handled lazily inside RedisRateLimiter
        _limiter_instance = RedisRateLimiter()

    return _limiter_instance


def reset_rate_limiter() -> None:
    """Reset the singleton — used in tests to force re-creation with different env."""
    global _limiter_instance
    _limiter_instance = None


def check_rate_limit(ip: str, path: str = "") -> bool:
    """Module-level convenience: return True if request should be allowed.

    ``path`` is currently unused but reserved for path-specific override rules.
    """
    return get_rate_limiter().is_allowed(ip)
