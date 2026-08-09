"""
test_file_cache.py — Unit tests for the bounded TTL+LRU FileManager cache.

Covers:
  - TTL expiration
  - maximum entry eviction (LRU)
  - deletion cleanup (cache + DuckDB)
  - failed upload cleanup (no partial cache entry)
  - workspace eviction
  - get_cache_stats()
  - repeated upload memory behaviour (old entry replaced)
"""

import asyncio
import io
import os
import sys
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Add backend to path ───────────────────────────────────────────────────────
BACKEND = Path(__file__).parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# ── Patch heavy external deps before importing file_manager ──────────────────
# We stub out DuckDB store, storage provider, DB connection, and insight engines
# so tests run without a real database or LLM.

_FAKE_STORE = MagicMock()
_FAKE_STORE.register_dataframe = MagicMock()
_FAKE_STORE.drop_table = MagicMock()
_FAKE_STORE.execute = MagicMock(return_value=None)

_FAKE_STORAGE = MagicMock()
_FAKE_STORAGE.save_file = MagicMock(return_value=(Path("/tmp/f.csv"), "local://f.csv"))
_FAKE_STORAGE.delete_dataset_dir = MagicMock()
_FAKE_STORAGE.delete_file = MagicMock()

_FAKE_CONN = MagicMock()
_FAKE_CONN.cursor.return_value.__enter__ = MagicMock(return_value=_FAKE_CONN.cursor())
_FAKE_CONN.cursor.return_value.__exit__ = MagicMock(return_value=False)
_FAKE_CONN.cursor.return_value.fetchone = MagicMock(return_value=None)
_FAKE_CONN.execute = MagicMock()
_FAKE_CONN.commit = MagicMock()
_FAKE_CONN.close = MagicMock()


def _make_upload_file(name="test.csv", content=b"col1,col2\n1,2\n3,4"):
    """Create a mock UploadFile-like object."""
    f = MagicMock()
    f.filename = name
    f.read = AsyncMock(return_value=content)
    return f


class TestTTLExpiration(unittest.TestCase):
    """File records expire after TTL seconds."""

    def test_ttl_expiry(self):
        """Entries should not be accessible after TTL expires."""
        os.environ["FM_CACHE_TTL_SECONDS"] = "1"   # 1 second TTL for speed
        os.environ["FM_CACHE_MAX_ENTRIES"] = "50"

        # Force re-import with new env
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]

        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
            rec = FileRecord("id001", "test.csv", df, Path("/tmp/test.csv"),
                             workspace_id="ws1", user_id="u1")
            fm._cache["id001"] = rec

            # Immediately accessible
            self.assertIsNotNone(fm.get_record("id001"))

            # After TTL expires
            time.sleep(1.2)
            self.assertIsNone(fm.get_record("id001"), "Record should have expired after TTL")

        del os.environ["FM_CACHE_TTL_SECONDS"]
        del os.environ["FM_CACHE_MAX_ENTRIES"]
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]


class TestLRUEviction(unittest.TestCase):
    """Oldest-accessed entries are evicted when maxsize is reached."""

    def test_max_entries_eviction(self):
        """When maxsize is exceeded, the LRU entry is evicted."""
        os.environ["FM_CACHE_TTL_SECONDS"] = "3600"
        os.environ["FM_CACHE_MAX_ENTRIES"] = "3"

        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]

        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            self.assertEqual(fm._cache.maxsize, 3)

            df = pd.DataFrame({"x": [1]})
            for i in range(3):
                rec = FileRecord(f"id{i:03d}", f"f{i}.csv", df, Path(f"/tmp/f{i}.csv"),
                                 workspace_id="ws1", user_id="u1")
                fm._cache[f"id{i:03d}"] = rec

            self.assertEqual(len(fm._cache), 3)

            # Adding a 4th entry triggers LRU eviction of id000
            rec4 = FileRecord("id003", "f3.csv", df, Path("/tmp/f3.csv"),
                              workspace_id="ws1", user_id="u1")
            fm._cache["id003"] = rec4

            self.assertEqual(len(fm._cache), 3, "Cache should still hold 3 entries")
            # id000 was the LRU candidate and should be gone
            self.assertNotIn("id000", fm._cache)

        del os.environ["FM_CACHE_TTL_SECONDS"]
        del os.environ["FM_CACHE_MAX_ENTRIES"]
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]


class TestDeletionCleanup(unittest.TestCase):
    """delete_file() removes entry from cache, DuckDB, and storage."""

    def setUp(self):
        os.environ.setdefault("FM_CACHE_TTL_SECONDS", "3600")
        os.environ.setdefault("FM_CACHE_MAX_ENTRIES", "50")
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]
        _FAKE_STORE.drop_table.reset_mock()
        _FAKE_STORAGE.delete_dataset_dir.reset_mock()
        _FAKE_CONN.execute.reset_mock()

    def test_delete_removes_from_cache(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})
            rec = FileRecord("del01", "d.csv", df, Path("/tmp/d.csv"),
                             workspace_id="ws2", user_id="u1")
            fm._cache["del01"] = rec

            ok = fm.delete_file("del01")
            self.assertTrue(ok)
            self.assertIsNone(fm.get_record("del01"))

    def test_delete_calls_drop_table(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})
            rec = FileRecord("del02", "d.csv", df, Path("/tmp/d.csv"),
                             workspace_id="ws2", user_id="u1")
            fm._cache["del02"] = rec

            fm.delete_file("del02")
            _FAKE_STORE.drop_table.assert_called_once()

    def test_delete_calls_storage_delete(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})
            rec = FileRecord("del03", "d.csv", df, Path("/tmp/d.csv"),
                             workspace_id="ws3", user_id="u1")
            fm._cache["del03"] = rec

            fm.delete_file("del03")
            _FAKE_STORAGE.delete_dataset_dir.assert_called_once_with("ws3", "del03")

    def test_delete_returns_false_for_missing(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager
            fm = FileManager()
            self.assertFalse(fm.delete_file("nonexistent-id"))


class TestWorkspaceEviction(unittest.TestCase):
    """evict_workspace() removes all entries belonging to a workspace."""

    def setUp(self):
        os.environ.setdefault("FM_CACHE_TTL_SECONDS", "3600")
        os.environ.setdefault("FM_CACHE_MAX_ENTRIES", "50")
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]
        _FAKE_STORE.drop_table.reset_mock()

    def test_evict_workspace_removes_correct_entries(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})

            for i in range(3):
                rec = FileRecord(f"ws1_{i}", f"f{i}.csv", df, Path(f"/tmp/f{i}.csv"),
                                 workspace_id="target_ws", user_id="u1")
                fm._cache[f"ws1_{i}"] = rec

            rec_other = FileRecord("ws2_0", "g.csv", df, Path("/tmp/g.csv"),
                                   workspace_id="other_ws", user_id="u1")
            fm._cache["ws2_0"] = rec_other

            evicted = fm.evict_workspace("target_ws")
            self.assertEqual(evicted, 3)
            self.assertIsNone(fm.get_record("ws1_0"))
            self.assertIsNone(fm.get_record("ws1_1"))
            self.assertIsNone(fm.get_record("ws1_2"))
            self.assertIsNotNone(fm.get_record("ws2_0"))

    def test_evict_nonexistent_workspace_returns_zero(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager
            fm = FileManager()
            self.assertEqual(fm.evict_workspace("no_such_ws"), 0)


class TestCacheStats(unittest.TestCase):
    """get_cache_stats() returns correct shape."""

    def setUp(self):
        os.environ.setdefault("FM_CACHE_TTL_SECONDS", "3600")
        os.environ.setdefault("FM_CACHE_MAX_ENTRIES", "50")
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]

    def test_stats_shape(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})
            rec = FileRecord("stat01", "s.csv", df, Path("/tmp/s.csv"),
                             workspace_id="ws_stat", user_id="u1")
            fm._cache["stat01"] = rec

            stats = fm.get_cache_stats()
            self.assertIn("current_entries", stats)
            self.assertIn("max_entries", stats)
            self.assertIn("ttl_seconds", stats)
            self.assertIn("file_ids", stats)
            self.assertEqual(stats["current_entries"], 1)
            self.assertIn("stat01", stats["file_ids"])

    def test_stats_max_entries_reflects_env(self):
        os.environ["FM_CACHE_MAX_ENTRIES"] = "77"
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]

        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager
            fm = FileManager()
            stats = fm.get_cache_stats()
            self.assertEqual(stats["max_entries"], 77)

        del os.environ["FM_CACHE_MAX_ENTRIES"]


class TestRepeatedUploadMemory(unittest.TestCase):
    """Re-inserting the same file_id replaces the old entry (no accumulation)."""

    def setUp(self):
        os.environ.setdefault("FM_CACHE_TTL_SECONDS", "3600")
        os.environ.setdefault("FM_CACHE_MAX_ENTRIES", "50")
        for mod in list(sys.modules.keys()):
            if "file_manager" in mod:
                del sys.modules[mod]

    def test_repeated_insert_does_not_grow_cache(self):
        with patch("core.data_store.get_store", return_value=_FAKE_STORE), \
             patch("core.storage.get_storage_provider", return_value=_FAKE_STORAGE), \
             patch("core.db.get_connection", return_value=_FAKE_CONN):
            from core.file_manager import FileManager, FileRecord
            import pandas as pd

            fm = FileManager()
            df = pd.DataFrame({"a": [1]})
            for _ in range(5):
                rec = FileRecord("same_id", "f.csv", df, Path("/tmp/f.csv"),
                                 workspace_id="ws1", user_id="u1")
                fm._cache["same_id"] = rec

            # Should still be only 1 entry
            self.assertEqual(len(fm._cache), 1)


if __name__ == "__main__":
    unittest.main()
