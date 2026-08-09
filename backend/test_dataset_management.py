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
        data = dataset_store.list_datasets(user_id="default_user", workspace_id="default_workspace")
        self.assertTrue(any(d["dataset_id"] == "test_ds_1" for d in data))
        self.assertFalse(any(d["dataset_id"] == "test_ds_2" for d in data))

        data_archived = dataset_store.list_datasets(archived=True, user_id="default_user", workspace_id="default_workspace")
        self.assertFalse(any(d["dataset_id"] == "test_ds_1" for d in data_archived))
        self.assertTrue(any(d["dataset_id"] == "test_ds_2" for d in data_archived))

        data_all = dataset_store.list_datasets(archived=None, user_id="default_user", workspace_id="default_workspace")
        self.assertTrue(any(d["dataset_id"] == "test_ds_1" for d in data_all))
        self.assertTrue(any(d["dataset_id"] == "test_ds_2" for d in data_all))

    def test_last_query_date_logging(self):
        """Test that sending a query touching a dataset updates its last_query_date."""
        ds1 = dataset_store.get_dataset("test_ds_1")
        self.assertIsNone(ds1.get("last_query_date"))

        dataset_store.touch_last_query("test_ds_1")
        
        ds1_updated = dataset_store.get_dataset("test_ds_1")
        self.assertIsNotNone(ds1_updated.get("last_query_date"))

if __name__ == "__main__":
    unittest.main()
