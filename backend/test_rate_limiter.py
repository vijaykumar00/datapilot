"""
test_rate_limiter.py — Rate limiter behaviour.

* In-memory limiter: allow/block/window/scopes.
* Redis limiter: O(1) round trips per check (not one GET per second of window),
  sliding-window-counter decisions, local fallback (not fail-open, not
  fail-closed-for-everyone) when Redis is down.
* Identity keys: authenticated users / guests are limited individually, so
  users behind one proxy/NAT IP do not share a bucket.
* Path rules: listing saved reports is not limited as "report generation".
"""

import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fakeredis

import core.rate_limiter as rl
from core.auth import create_access_token


class TestInMemoryRateLimiter(unittest.TestCase):
    def test_blocks_at_limit_and_scopes_are_independent(self):
        limiter = rl.InMemoryRateLimiter(window_seconds=60, max_requests=3)
        for _ in range(3):
            self.assertTrue(limiter.is_allowed("1.2.3.4"))
        self.assertFalse(limiter.is_allowed("1.2.3.4"))
        self.assertTrue(limiter.is_allowed("1.2.3.5"))
        self.assertTrue(limiter.is_allowed("1.2.3.4", scope="other"))

    def test_window_expiry(self):
        limiter = rl.InMemoryRateLimiter(window_seconds=1, max_requests=1)
        self.assertTrue(limiter.is_allowed("5.5.5.5"))
        self.assertFalse(limiter.is_allowed("5.5.5.5"))
        time.sleep(1.1)
        self.assertTrue(limiter.is_allowed("5.5.5.5"))


class _CountingRedis(fakeredis.FakeRedis):
    commands = 0

    def pipeline(self, *args, **kwargs):
        pipe = super().pipeline(*args, **kwargs)
        original = pipe.execute

        def execute(*a, **k):
            _CountingRedis.commands += len(pipe.command_stack)
            return original(*a, **k)

        pipe.execute = execute
        return pipe


class TestRedisRateLimiter(unittest.TestCase):
    def setUp(self):
        self.limiter = rl.RedisRateLimiter(window_seconds=3600, max_requests=5, env_label="test")
        self.limiter._sync_client = _CountingRedis()

    def test_blocks_when_over_limit(self):
        results = [self.limiter.is_allowed("u:1", scope="upload") for _ in range(7)]
        self.assertEqual(results[:5], [True] * 5)
        self.assertFalse(results[5])

    def test_constant_redis_cost_per_check_for_long_windows(self):
        _CountingRedis.commands = 0
        self.limiter.is_allowed("u:2", scope="upload")
        # Previously 3,601 GETs for a one-hour window; now INCR + EXPIRE + GET.
        self.assertLessEqual(_CountingRedis.commands, 3)

    def test_key_has_scope_identity_and_bucket(self):
        key = self.limiter._key("u:abc", 123, "upload")
        self.assertEqual(key, "dp:test:rl:upload:u:abc:123")

    def test_redis_outage_uses_local_fallback_not_fail_open(self):
        broken = rl.RedisRateLimiter(redis_url="redis://127.0.0.1:1/0", window_seconds=60, max_requests=2,
                                     connect_timeout=0.05, socket_timeout=0.05)
        self.assertTrue(broken.is_allowed("ip:9.9.9.9"))
        self.assertTrue(broken.is_allowed("ip:9.9.9.9"))
        self.assertFalse(broken.is_allowed("ip:9.9.9.9"), "limits must still be enforced during an outage")
        self.assertIsNotNone(broken.last_error)

    def test_async_path(self):
        limiter = rl.RedisRateLimiter(window_seconds=60, max_requests=2, env_label="test")
        limiter._async_client = fakeredis.FakeAsyncRedis()

        async def run():
            return [await limiter.is_allowed_async("u:3") for _ in range(3)]

        self.assertEqual(asyncio.run(run()), [True, True, False])


class TestIdentityAndRules(unittest.TestCase):
    def test_authenticated_users_are_keyed_individually(self):
        token_a = create_access_token("user-a", "a@x.test", "ws")
        token_b = create_access_token("user-b", "b@x.test", "ws")
        self.assertEqual(rl.caller_key(f"Bearer {token_a}", None, "10.0.0.1"), "u:user-a")
        self.assertEqual(rl.caller_key(f"Bearer {token_b}", None, "10.0.0.1"), "u:user-b")
        self.assertTrue(rl.caller_key(None, "guest-token", "10.0.0.1").startswith("g:"))
        self.assertEqual(rl.caller_key("Bearer forged", None, "10.0.0.1"), "ip:10.0.0.1")

    def test_listing_reports_is_not_report_generation(self):
        scope, _, _ = rl.limit_for_path("/reports", "GET")
        self.assertEqual(scope, "global")
        scope, _, _ = rl.limit_for_path("/report/generate", "POST")
        self.assertEqual(scope, "reports")

    def test_auth_endpoints_keyed_by_ip(self):
        _, _, _, ip_only = rl.limit_rule("/auth/login", "POST")
        self.assertTrue(ip_only)

    def test_factory(self):
        old = os.environ.get("RATE_LIMITER_BACKEND")
        try:
            os.environ["RATE_LIMITER_BACKEND"] = "memory"
            rl.reset_rate_limiter()
            self.assertEqual(rl.get_rate_limiter().backend_name, "memory")
            os.environ["RATE_LIMITER_BACKEND"] = "redis"
            rl.reset_rate_limiter()
            self.assertEqual(rl.get_rate_limiter().backend_name, "redis")
        finally:
            if old is None:
                os.environ.pop("RATE_LIMITER_BACKEND", None)
            else:
                os.environ["RATE_LIMITER_BACKEND"] = old
            rl.reset_rate_limiter()

    def test_production_health_reports_redis_down(self):
        old = os.environ.get("APP_ENV")
        try:
            os.environ["APP_ENV"] = "production"
            limiter = rl.RedisRateLimiter(redis_url="redis://127.0.0.1:1/0", connect_timeout=0.05, socket_timeout=0.05)
            rl._limiter_instance = limiter
            health = rl.rate_limiter_health()
            self.assertFalse(health["ok"])
        finally:
            if old is None:
                os.environ.pop("APP_ENV", None)
            else:
                os.environ["APP_ENV"] = old
            rl.reset_rate_limiter()


if __name__ == "__main__":
    unittest.main()
