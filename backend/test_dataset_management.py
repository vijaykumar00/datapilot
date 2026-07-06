import os
import sys
import unittest
from fastapi.testclient import TestClient

# Add current directory to path to import backend core modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
import core.dataset_store as dataset_store

class TestDatasetManagement(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_datasets = []
        import core.db as db
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM dataset_registry WHERE dataset_id LIKE 'test_ds_%';")
            conn.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id, filename, display_name, description, tags, row_count, column_count,
                    sheet_count, file_size_bytes, archived, upload_date, user_id, workspace_id, created_at, updated_at
                ) VALUES 
                ('test_ds_1', 'file1.csv', 'Sales Data', 'Active sales logs', '["sales", "2026"]', 1500, 10, 1, 45000, 0, '2026-06-18T20:00:00', 'default_user', 'default_workspace', '2026-06-18T20:00:00', '2026-06-18T20:00:00'),
                ('test_ds_2', 'file2.xlsx', 'Marketing Budget', 'Archived budget logs', '["marketing", "2025"]', 800, 15, 2, 98000, 1, '2026-06-18T20:00:00', 'default_user', 'default_workspace', '2026-06-18T20:00:00', '2026-06-18T20:00:00');
                """
            )
            conn.commit()
            self.test_datasets = ["test_ds_1", "test_ds_2"]
        finally:
            conn.close()

    def tearDown(self):
        import core.db as db
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM dataset_registry WHERE dataset_id LIKE 'test_ds_%';")
            conn.commit()
        finally:
            conn.close()

    def test_combined_dataset_listing(self):
        """Test retrieving all active and archived datasets using the modified archived query parameter."""
        resp = self.client.get("/datasets")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(any(d["dataset_id"] == "test_ds_1" for d in data["datasets"]))
        self.assertFalse(any(d["dataset_id"] == "test_ds_2" for d in data["datasets"]))

        resp_archived = self.client.get("/datasets?archived=true")
        self.assertEqual(resp_archived.status_code, 200)
        data_archived = resp_archived.json()
        self.assertFalse(any(d["dataset_id"] == "test_ds_1" for d in data_archived["datasets"]))
        self.assertTrue(any(d["dataset_id"] == "test_ds_2" for d in data_archived["datasets"]))

        resp_all = self.client.get("/datasets?archived=all")
        self.assertEqual(resp_all.status_code, 200)
        data_all = resp_all.json()
        self.assertTrue(any(d["dataset_id"] == "test_ds_1" for d in data_all["datasets"]))
        self.assertTrue(any(d["dataset_id"] == "test_ds_2" for d in data_all["datasets"]))

    def test_last_query_date_logging(self):
        """Test that sending a query touching a dataset updates its last_query_date."""
        ds1 = dataset_store.get_dataset("test_ds_1")
        self.assertIsNone(ds1.get("last_query_date"))

        payload = {
            "message": "Summarize my dataset",
            "file_ids": ["test_ds_1"],
            "conversation_history": [],
            "session_id": None
        }
        resp = self.client.post("/chat/stream", json=payload)
        self.assertEqual(resp.status_code, 200)
        
        ds1_updated = dataset_store.get_dataset("test_ds_1")
        self.assertIsNotNone(ds1_updated.get("last_query_date"))

if __name__ == "__main__":
    unittest.main()
