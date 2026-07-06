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
        # Test that switching to an incorrect sheet name raises IntelligentException with suggestions/recovery
        fm = FileManager()
        
        # Create a dummy excel file with two sheets
        xlsx_path = Path(self.tmp_dir) / "test.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            pd.DataFrame({"revenue": [100, 200]}).to_excel(writer, sheet_name="RevenueSheet", index=False)
            pd.DataFrame({"cost": [50, 60]}).to_excel(writer, sheet_name="CostSheet", index=False)
            
        record = FileRecord(
            file_id="mock_id",
            filename="test.xlsx",
            df=pd.DataFrame({"revenue": [100, 200]}),
            path=xlsx_path,
            metadata={"sheet_names": ["RevenueSheet", "CostSheet"], "active_sheet": "RevenueSheet"}
        )
        fm._cache["mock_id"] = record
        
        # Test switching to incorrect sheet name (fuzzy suggestion 'CostSheet')
        with self.assertRaises(IntelligentException) as context:
            await fm.switch_sheet("mock_id", "CostShit")
            
        err = context.exception.err_dict
        self.assertEqual(err["code"], "INCORRECT_SHEET_NAME")
        self.assertEqual(err["title"], "Incorrect sheet name")
        self.assertIn("CostSheet", err["message"])
        self.assertIsNotNone(err["recovery"])
        self.assertEqual(err["recovery"]["type"], "switch_sheet")
        self.assertEqual(err["recovery"]["sheet"], "CostSheet")

    async def test_auto_recovery_column_typo(self):
        # Test that InsightAgent automatically recovers from column typos using fuzzy matching
        df = pd.DataFrame({"revenue": [100, 200, 300]})
        self.store.register_dataframe("file_mock", df)
        
        mock_llm = MockLLM()
        # Create InsightAgent with mock dependencies
        agent = InsightAgent(llm_client=mock_llm, data_store=self.store, file_manager=None)
        
        # Mock FileManager record lookup
        class MockFileManager:
            def get_record(self, fid):
                return FileRecord(
                    file_id="mock",
                    filename="test.csv",
                    df=df,
                    path=Path("test.csv")
                )
        agent.files = MockFileManager()
        
        # Run agent query. The LLM returns SQL: SELECT SUM(revenuee) FROM file_mock
        # The agent should catch the COLUMN_NOT_FOUND error on 'revenuee', 
        # auto-correct it to 'revenue', re-run successfully, and return result.
        response = await agent.run("Calculate total revenuee", ["mock"])
        
        self.assertIsNone(response.error)
        self.assertIn("automatically corrected it to 'revenue'", response.content)
        self.assertEqual(response.table_data[0]["total"], 600)
        self.assertTrue(response.metadata.get("auto_recovered"))

if __name__ == "__main__":
    unittest.main()
