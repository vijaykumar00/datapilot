"""
test_file_cache.py — Durable datasets + memory-bounded cache.

The old design kept datasets ONLY in a 50-entry, 1-hour TTL in-process cache, so
datasets disappeared after an hour, after a restart, or when other tenants
uploaded.  These tests pin the new behaviour: storage + registry are the source
of truth, any process (fresh FileManager == another worker / after restart)
can load any version, and the cache is bounded by bytes, not entries/TTL.
"""

import io
import os
import threading
import unittest
import uuid

import pandas as pd

from core.file_manager import ConcurrentModificationError, DatasetCache, FileManager
from core.storage import get_storage_provider


def _csv(text: str, name="sales.csv"):
    path = os.path.join(os.environ["LOCAL_STORAGE_DIR"], f"up_{uuid.uuid4().hex}_{name}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _ingest(fm: FileManager, text: str, ws: str, name="sales.csv") -> str:
    from pathlib import Path

    path = _csv(text, name)
    dataset_id = fm.stage_upload(Path(path), name, os.path.getsize(path), workspace_id=ws, user_id="u1")
    fm.ingest(dataset_id)
    return dataset_id


class TestDatasetCache(unittest.TestCase):
    def test_bounded_by_bytes_lru(self):
        df = pd.DataFrame({"a": range(1000)})
        size = int(df.memory_usage(deep=True).sum())
        cache = DatasetCache(max_bytes=size * 2 + 10)
        cache.put(("a", 1), df)
        cache.put(("b", 1), df)
        cache.get(("a", 1))  # a is now most recently used
        cache.put(("c", 1), df)
        self.assertIsNotNone(cache.get(("a", 1)))
        self.assertIsNone(cache.get(("b", 1)))
        self.assertLessEqual(cache.stats()["current_bytes"], cache.max_bytes)

    def test_oversized_items_are_not_cached(self):
        cache = DatasetCache(max_bytes=10)
        cache.put(("x", 1), pd.DataFrame({"a": range(100)}))
        self.assertEqual(cache.stats()["current_entries"], 0)


class TestDurableDatasets(unittest.TestCase):
    def setUp(self):
        self.ws = f"ws_{uuid.uuid4().hex[:8]}"
        self.fm = FileManager()
        self.dataset_id = _ingest(self.fm, "region,revenue\nN,10\nS,20\nN,30\n", self.ws)

    def tearDown(self):
        self.fm.delete_file(self.dataset_id)

    def test_survives_restart_and_other_workers(self):
        other_worker = FileManager()  # empty cache: simulates a restart or a different process
        record = other_worker.get_record(self.dataset_id, self.ws)
        self.assertIsNotNone(record)
        self.assertEqual(int(record.df["revenue"].sum()), 60)

    def test_is_workspace_scoped(self):
        self.assertIsNone(self.fm.get_record(self.dataset_id, "another_workspace"))

    def test_transforms_are_versioned_durably_and_undoable(self):
        self.fm.apply_transform(self.dataset_id, {"action": "filter_rows", "column": "region", "operator": "==", "value": "N"},
                                "keep N", self.ws)
        fresh = FileManager().get_record(self.dataset_id, self.ws)
        self.assertEqual(len(fresh.df), 2)
        self.assertEqual(fresh.version, 2)
        self.assertEqual(len(fresh.history), 1)

        self.fm.undo_transform(self.dataset_id, self.ws)
        restored = FileManager().get_record(self.dataset_id, self.ws)
        self.assertEqual(len(restored.df), 3)
        self.assertEqual(restored.version, 1)

    def test_concurrent_writers_cannot_overwrite_each_other(self):
        stale = self.fm.get_record(self.dataset_id, self.ws)
        self.fm.apply_edits(self.dataset_id, [{"row_index": 0, "column": "revenue", "value": 11}], self.ws)
        with self.assertRaises(ConcurrentModificationError):
            self.fm._commit(stale, stale.df, "stale write", {"action": "x"})

    def test_parallel_edits_all_land_or_conflict(self):
        errors, ok = [], []

        def edit(i):
            try:
                FileManager().apply_edits(self.dataset_id, [{"row_index": 0, "column": "revenue", "value": i}], self.ws)
                ok.append(i)
            except ConcurrentModificationError:
                errors.append(i)

        threads = [threading.Thread(target=edit, args=(i,)) for i in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        final = FileManager().get_record(self.dataset_id, self.ws)
        self.assertEqual(final.version, 1 + len(ok))
        self.assertEqual(len(ok) + len(errors), 5)

    def test_delete_removes_registry_and_objects(self):
        dataset_id = _ingest(self.fm, "a,b\n1,2\n", self.ws, "tmp.csv")
        prefix_obj = get_storage_provider()._object_path(f"workspace/{self.ws}/datasets/{dataset_id}/")
        self.assertTrue(prefix_obj.exists())
        self.assertTrue(self.fm.delete_file(dataset_id, self.ws))
        self.assertFalse(prefix_obj.exists())
        self.assertIsNone(self.fm.get_record(dataset_id, self.ws))

    def test_list_files_reads_registry_not_memory(self):
        listed = FileManager().list_files(self.ws)
        self.assertEqual([f["file_id"] for f in listed], [self.dataset_id])
        self.assertEqual(listed[0]["row_count"], 3)


if __name__ == "__main__":
    unittest.main()
