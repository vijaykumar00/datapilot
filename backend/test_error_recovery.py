import unittest
import pandas as pd
import tempfile
from pathlib import Path
import os
import shutil

from core.error_intelligence import (
    IntelligentException,
    diagnose_sql_error,
    diagnose_upload_error,
    diagnose_transform_error,
    diagnose_empty_result,
)
from core.file_manager import FileManager, FileRecord
from agents.insight_agent import InsightAgent
from core.data_store import get_store
from core.llm_client import get_llm_client

class MockLLM:
    async def generate(self, prompt, system=None, json_mode=False):
        # Mock LLM returns a query referencing a column with a typo
        return '{"sql": "SELECT SUM(revenuee) as total FROM file_mock", "explanation": "Calculates total revenue"}'

class TestErrorRecoverySystem(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.store = get_store()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_unsupported_and_empty_file_upload(self):
        # 1. Test unsupported file format
        exc = Exception("Unsupported format")
        err = diagnose_upload_error(exc, "document.pdf", b"pdf_raw_bytes")
        self.assertEqual(err["code"], "UNSUPPORTED_FORMAT")
        self.assertEqual(err["title"], "Unsupported file")
        self.assertIn(".pdf", err["message"])

        # 2. Test empty file
        exc = Exception("File is empty")
        err = diagnose_upload_error(exc, "data.csv", b"")
        self.assertEqual(err["code"], "EMPTY_FILE")
        self.assertEqual(err["title"], "File appears to be empty")

    def test_invalid_date_format_transform(self):
        # Test invalid date parsing error in transform diagnostics
        exc = Exception("ParserError: Unknown string format: 2023-abc-99")
        err = diagnose_transform_error(exc, {"operation": "to_datetime", "column": "my_date"})
        self.assertEqual(err["code"], "INVALID_DATE_FORMAT")
        self.assertEqual(err["title"], "Invalid date format")
        self.assertEqual(err["affected_column"], "my_date")

    async def test_incorrect_sheet_name(self):
        """Switching to a wrong sheet name raises IntelligentException with a fuzzy-match recovery."""
        fm = FileManager()
        record = FileRecord(
            file_id="mock_id",
            filename="test.xlsx",
            df=pd.DataFrame({"revenue": [100, 200]}),
            path="unused",
            metadata={"sheet_names": ["RevenueSheet", "CostSheet"], "active_sheet": "RevenueSheet"},
        )
        fm.get_record = lambda file_id, workspace_id=None: record

        with self.assertRaises(IntelligentException) as context:
            fm.switch_sheet("mock_id", "CostShit")

        err = context.exception.err_dict
        self.assertEqual(err["code"], "INCORRECT_SHEET_NAME")
        self.assertEqual(err["title"], "Incorrect sheet name")
        self.assertIn("CostSheet", err["message"])
        self.assertEqual(err["recovery"]["type"], "switch_sheet")
        self.assertEqual(err["recovery"]["sheet"], "CostSheet")

    async def test_auto_recovery_column_typo(self):
        """InsightAgent recovers from a column typo, runs the corrected SQL in the sandbox and flags it."""
        df = pd.DataFrame({"revenue": [100, 200, 300]})

        class MockFileManager:
            def get_record(self, fid, workspace_id=None):
                return FileRecord(file_id="mock", filename="test.csv", df=df, path="test.csv")

        class TypoLLM:
            settings = None

            async def generate(self, prompt, system=None, json_mode=False, **kwargs):
                return '{"sql": "SELECT SUM(revenuee) as total FROM file_mock", "explanation": "Calculates total revenue"}'

        agent = InsightAgent(llm_client=TypoLLM(), data_store=self.store, file_manager=MockFileManager(), workspace_id="ws")
        response = await agent.run("Calculate total revenuee", ["mock"])

        self.assertIsNone(response.error)
        self.assertIn("'revenue' was used instead", response.content)
        self.assertEqual(response.table_data[0]["total"], 600)
        self.assertTrue(response.metadata.get("auto_recovered"))


if __name__ == "__main__":
    unittest.main()
