import os
import tempfile
import unittest
from pathlib import Path

from core.storage import LocalStorageProvider, S3CompatibleStorageProvider, get_storage_provider, reset_storage_provider


class TestStorageProvider(unittest.TestCase):
    def setUp(self):
        self._old_env = {
            key: os.environ.get(key)
            for key in ("APP_ENV", "STORAGE_PROVIDER", "S3_BUCKET", "ALLOW_LOCAL_STORAGE_IN_PRODUCTION")
        }
        reset_storage_provider()

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_storage_provider()

    def test_local_provider_sanitizes_and_namespaces_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = LocalStorageProvider(base_dir=Path(tmp))
            path, uri = provider.save_file("workspace/../A", "dataset/../B", "../private.csv", b"a,b\n1,2\n")

            self.assertEqual(path.name, "private.csv")
            self.assertTrue(path.is_relative_to(Path(tmp)))
            self.assertIn("/uploads/workspace-..-A/dataset-..-B/private.csv", uri)
            self.assertTrue(provider.exists("workspace/../A", "dataset/../B", "../private.csv"))
            self.assertEqual(provider.read_file("workspace/../A", "dataset/../B", "../private.csv"), b"a,b\n1,2\n")
            self.assertEqual(provider.size("workspace/../A", "dataset/../B", "../private.csv"), 8)
            self.assertEqual(provider.list("workspace/../A", "dataset/../B"), ["private.csv"])

    def test_production_rejects_local_storage_without_explicit_override(self):
        os.environ["APP_ENV"] = "production"
        os.environ["STORAGE_PROVIDER"] = "local"
        os.environ.pop("ALLOW_LOCAL_STORAGE_IN_PRODUCTION", None)
        reset_storage_provider()

        with self.assertRaises(RuntimeError):
            get_storage_provider()

    def test_s3_provider_uses_workspace_dataset_key_layout(self):
        os.environ["STORAGE_PROVIDER"] = "s3"
        os.environ["S3_BUCKET"] = "unit-bucket"
        provider = S3CompatibleStorageProvider()

        key = provider._key("workspace/a", "dataset/b", "../report.csv")
        self.assertEqual(key, "workspace/workspace-a/datasets/dataset-b/report.csv")


if __name__ == "__main__":
    unittest.main()
