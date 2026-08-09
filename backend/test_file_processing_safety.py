import io
import os
import unittest
import zipfile

import pandas as pd

from core.file_manager import FileManager


class TestFileProcessingSafety(unittest.TestCase):
    def setUp(self):
        self.old_env = {
            key: os.environ.get(key)
            for key in ("MAX_DATASET_ROWS", "MAX_DATASET_COLUMNS", "MAX_WORKBOOK_DECOMPRESSED_BYTES")
        }
        self.manager = FileManager()

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_rejects_too_many_rows(self):
        os.environ["MAX_DATASET_ROWS"] = "2"
        with self.assertRaises(ValueError):
            self.manager._validate_dataframe_bounds(pd.DataFrame({"a": [1, 2, 3]}))

    def test_rejects_too_many_columns(self):
        os.environ["MAX_DATASET_COLUMNS"] = "2"
        with self.assertRaises(ValueError):
            self.manager._validate_dataframe_bounds(pd.DataFrame([[1, 2, 3]], columns=["a", "b", "c"]))

    def test_rejects_xlsx_zip_expansion_over_limit(self):
        os.environ["MAX_WORKBOOK_DECOMPRESSED_BYTES"] = "10"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/sharedStrings.xml", "x" * 100)

        with self.assertRaises(ValueError):
            self.manager._validate_workbook_expansion(buffer.getvalue(), ".xlsx")


if __name__ == "__main__":
    unittest.main()
