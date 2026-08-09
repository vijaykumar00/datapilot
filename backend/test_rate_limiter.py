"""
test_rate_limiter.py — Unit tests for core/rate_limiter.py

Covers:
  - InMemoryRateLimiter: allow, block, window expiry
  - RedisRateLimiter: allow, block when mocked, fail-open on error
  - Factory: correct backend selected via RATE_LIMITER_BACKEND env var
  - check_rate_limit convenience function
  - No sensitive data in Redis keys
  - Fail-open behaviour (Redis down = allow)
  - reset_rate_limiter() resets singleton
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _fresh_module(env_overrides: dict | None = None):
    """Reimport rate_limiter with fresh singleton and env."""
    for name in list(sys.modules.keys()):
        if "rate_limiter" in name:
            del sys.modules[name]

    old = {}
    for k, v in (env_overrides or {}).items():
        old[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    import core.rate_limiter as rl
    return rl, old


def _restore(old: dict):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestInMemoryRateLimiter(unittest.TestCase):

    def _make(self, window=10, max_req=5):
        from core.rate_limiter import InMemoryRateLimiter
        return InMemoryRateLimiter(window_seconds=window, max_requests=max_req)

    def setUp(self):
        for name in list(sys.modules.keys()):
            if "rate_limiter" in name:
                del sys.modules[name]

    def test_allows_requests_below_limit(self):
        rl = self._make(max_req=5)
        for _ in range(5):
            self.assertTrue(rl.is_allowed("1.2.3.4"))

    def test_blocks_request_at_limit(self):
        rl = self._make(max_req=3)
        for _ in range(3):
            rl.is_allowed("1.2.3.4")
        self.assertFalse(rl.is_allowed("1.2.3.4"), "4th request should be blocked")

    def test_different_ips_independent(self):
        rl = self._make(max_req=2)
        rl.is_allowed("10.0.0.1")
        rl.is_allowed("10.0.0.1")
        # ip1 is now at limit
        self.assertFalse(rl.is_allowed("10.0.0.1"))
        # ip2 is untouched
        self.assertTrue(rl.is_allowed("10.0.0.2"))

    def test_window_expiry_allows_new_requests(self):
        rl = self._make(window=1, max_req=2)
        rl.is_allowed("5.5.5.5")
        rl.is_allowed("5.5.5.5")
        self.assertFalse(rl.is_allowed("5.5.5.5"))

        time.sleep(1.1)  # wait for window to expire
        self.assertTrue(rl.is_allowed("5.5.5.5"), "Should be allowed after window resets")

    def test_backend_name(self):
        rl = self._make()
        self.assertEqual(rl.backend_name, "memory")


class TestRedisRateLimiterMocked(unittest.TestCase):
    """Test RedisRateLimiter with a mocked redis client."""

    def setUp(self):
        for name in list(sys.modules.keys()):
            if "rate_limiter" in name:
                del sys.modules[name]

    def _make_redis_limiter(self, total_count=0):
        """Return a RedisRateLimiter whose Redis client is mocked."""
        from core.rate_limiter import RedisRateLimiter

        mock_pipe = MagicMock()
        # Simulate 'total_count' existing requests in the window
        mock_pipe.execute.return_value = [str(total_count).encode()] + [None] * 59
        mock_pipe2 = MagicMock()
        mock_pipe2.execute.return_value = [1, True]

        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = [mock_pipe, mock_pipe2]
        mock_redis.ping.return_value = True

        rl = RedisRateLimiter(window_seconds=60, max_requests=100)
        rl._redis = mock_redis
        return rl

    def test_allows_when_under_limit(self):
        rl = self._make_redis_limiter(total_count=50)
        self.assertTrue(rl.is_allowed("7.7.7.7"))

    def test_blocks_when_at_limit(self):
        rl = self._make_redis_limiter(total_count=100)
        self.assertFalse(rl.is_allowed("7.7.7.7"))

    def test_backend_name(self):
        from core.rate_limiter import RedisRateLimiter
        rl = RedisRateLimiter()
        self.assertEqual(rl.backend_name, "redis")

    def test_fail_open_on_redis_error(self):
        """When Redis raises an exception, request should be allowed (fail open)."""
        from core.rate_limiter import RedisRateLimiter

        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = Exception("Connection refused")

        rl = RedisRateLimiter(window_seconds=60, max_requests=100)
        rl._redis = mock_redis

        result = rl.is_allowed("8.8.8.8")
        self.assertTrue(result, "Should fail open when Redis is down")

    def test_redis_connection_resets_after_error(self):
        """After an error, self._redis is reset to None for reconnect on next call."""
        from core.rate_limiter import RedisRateLimiter

        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = Exception("Timeout")

        rl = RedisRateLimiter(window_seconds=60, max_requests=100)
        rl._redis = mock_redis

        rl.is_allowed("9.9.9.9")
        self.assertIsNone(rl._redis, "Redis client should be reset after error")


class TestRedisKeyFormat(unittest.TestCase):
    """Verify Redis key format contains no sensitive user data."""

    def setUp(self):
        for name in list(sys.modules.keys()):
            if "rate_limiter" in name:
                del sys.modules[name]

    def test_key_format(self):
        from core.rate_limiter import RedisRateLimiter
        rl = RedisRateLimiter(env_label="test")
        key = rl._key("192.168.1.1", 1_700_000_000)
        self.assertTrue(key.startswith("dp:test:rl:192.168.1.1:"))
        # No user passwords, tokens, or emails
        self.assertNotIn("@", key)
        self.assertNotIn("token", key)
        self.assertNotIn("password", key)

    def test_key_contains_ip(self):
        from core.rate_limiter import RedisRateLimiter
        rl = RedisRateLimiter(env_label="prod")
        key = rl._key("10.0.0.5", 1234567890)
        self.assertIn("10.0.0.5", key)

    def test_key_contains_epoch(self):
        from core.rate_limiter import RedisRateLimiter
        rl = RedisRateLimiter(env_label="prod")
        key = rl._key("10.0.0.5", 9999)
        self.assertIn("9999", key)


class TestFactorySelection(unittest.TestCase):
    """get_rate_limiter() selects the right backend from env."""

    def test_memory_backend_selected(self):
        rl, old = _fresh_module({"RATE_LIMITER_BACKEND": "memory"})
        limiter = rl.get_rate_limiter()
        self.assertEqual(limiter.backend_name, "memory")
        _restore(old)

    def test_redis_backend_selected_by_default(self):
        rl, old = _fresh_module({"RATE_LIMITER_BACKEND": None})
        # We won't actually connect, just check the type
        limiter = rl.get_rate_limiter()
        self.assertEqual(limiter.backend_name, "redis")
        _restore(old)

    def test_singleton_reused(self):
        rl, old = _fresh_module({"RATE_LIMITER_BACKEND": "memory"})
        a = rl.get_rate_limiter()
        b = rl.get_rate_limiter()
        self.assertIs(a, b, "Should return the same singleton instance")
        _restore(old)

    def test_reset_creates_new_instance(self):
        rl, old = _fresh_module({"RATE_LIMITER_BACKEND": "memory"})
        a = rl.get_rate_limiter()
        rl.reset_rate_limiter()
        b = rl.get_rate_limiter()
        self.assertIsNot(a, b, "reset_rate_limiter should create a new instance")
        _restore(old)


class TestCheckRateLimitFunction(unittest.TestCase):
    """check_rate_limit() convenience function."""

    def setUp(self):
        rl, self.old = _fresh_module({"RATE_LIMITER_BACKEND": "memory",
                                       "RATE_LIMIT_MAX_REQUESTS": "3",
                                       "RATE_LIMIT_WINDOW_SECONDS": "60"})
        self.rl = rl

    def tearDown(self):
        _restore(self.old)

    def test_check_rate_limit_allows(self):
        self.assertTrue(self.rl.check_rate_limit("1.1.1.1"))

    def test_check_rate_limit_blocks_after_limit(self):
        for _ in range(3):
            self.rl.check_rate_limit("2.2.2.2")
        self.assertFalse(self.rl.check_rate_limit("2.2.2.2"))


class TestRedisUnavailableFailOpen(unittest.TestCase):
    """RedisRateLimiter fails open when Redis is not reachable."""

    def setUp(self):
        for name in list(sys.modules.keys()):
            if "rate_limiter" in name:
                del sys.modules[name]

    def test_fails_open_when_redis_package_missing(self):
        """Simulate redis package not installed."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("No module named 'redis'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from core.rate_limiter import RedisRateLimiter
            rl = RedisRateLimiter()
            result = rl.is_allowed("3.3.3.3")
            self.assertTrue(result, "Should fail open when redis package is missing")

    def test_fails_open_when_redis_connection_refused(self):
        """Simulate Redis connection failure."""
        from core.rate_limiter import RedisRateLimiter

        mock_redis_module = MagicMock()
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = Exception("Connection refused")
        mock_redis_module.Redis.from_url.return_value = mock_redis_instance

        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            rl = RedisRateLimiter(redis_url="redis://badhost:9999/0")
            result = rl.is_allowed("4.4.4.4")
            self.assertTrue(result, "Should fail open when Redis connection is refused")


if __name__ == "__main__":
    unittest.main()
