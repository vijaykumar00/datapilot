"""
test_error_intelligence.py — Diagnostic tests verifying 100% deterministic error diagnosis.
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import unittest
import pandas as pd
import numpy as np

from core.error_intelligence import (
    diagnose_upload_error,
    diagnose_schema,
    diagnose_sql_error,
    diagnose_empty_result,
    diagnose_agent_error,
    diagnose_transform_error,
    format_for_user
)

class TestErrorIntelligence(unittest.TestCase):

    def test_1_upload_encoding_error(self):
        print("[RUN] test_1_upload_encoding_error")
        exc = Exception("utf-8 codec can't decode byte 0x92 in position 12")
        err = diagnose_upload_error(exc, "sales_q1.csv", b"dummy bytes")
        self.assertEqual(err["code"], "ENCODING_ERROR")
        self.assertEqual(err["severity"], "error")
        self.assertTrue(any("Excel" in s for s in err["suggestions"]))
        print("[PASS] upload encoding error diagnosed.")

    def test_2_upload_too_large(self):
        print("[RUN] test_2_upload_too_large")
        exc = Exception("File size exceeds maximum limit of 50MB")
        # 60MB raw bytes
        raw_bytes = b"0" * (60 * 1024 * 1024)
        err = diagnose_upload_error(exc, "huge_data.csv", raw_bytes)
        self.assertEqual(err["code"], "FILE_TOO_LARGE")
        self.assertEqual(err["severity"], "error")
        self.assertTrue(any("Filter" in s for s in err["suggestions"]))
        print("[PASS] upload file too large diagnosed.")

    def test_3_schema_mixed_types(self):
        print("[RUN] test_3_schema_mixed_types")
        # Create column with mixed types (90% numeric, 10% text)
        data = [10.5] * 90 + ["$20.0"] * 10
        df = pd.DataFrame({"Revenue": data})
        warnings = diagnose_schema(df, "sales.csv")
        mixed_warnings = [w for w in warnings if w["code"] == "MIXED_TYPES"]
        self.assertEqual(len(mixed_warnings), 1)
        w = mixed_warnings[0]
        self.assertEqual(w["affected_column"], "Revenue")
        self.assertEqual(w["affected_rows"], (91, 100))
        self.assertEqual(w["severity"], "warning")
        print("[PASS] schema mixed-type column diagnosed.")

    def test_4_schema_high_null_rate(self):
        print("[RUN] test_4_schema_high_null_rate")
        # 90% null column
        data = [None] * 90 + ["active"] * 10
        df = pd.DataFrame({"Status": data})
        warnings = diagnose_schema(df, "sales.csv")
        null_warnings = [w for w in warnings if w["code"] == "HIGH_NULL_RATE"]
        self.assertEqual(len(null_warnings), 1)
        w = null_warnings[0]
        self.assertEqual(w["affected_column"], "Status")
        self.assertEqual(w["severity"], "critical") # > 80% is critical
        print("[PASS] schema high-null rate diagnosed.")

    def test_5_schema_potential_id_column(self):
        print("[RUN] test_5_schema_potential_id_column")
        # 100% unique integers in ID-like column name
        df = pd.DataFrame({"invoice_idx": list(range(1001, 1051))})
        warnings = diagnose_schema(df, "sales.csv")
        id_warnings = [w for w in warnings if w["code"] == "ID_COLUMN_METRIC"]
        self.assertEqual(len(id_warnings), 1)
        w = id_warnings[0]
        self.assertEqual(w["affected_column"], "invoice_idx")
        self.assertEqual(w["severity"], "info")
        print("[PASS] schema potential ID column diagnosed.")

    def test_6_sql_column_typo(self):
        print("[RUN] test_6_sql_column_typo")
        df = pd.DataFrame({"Revenue": [100, 200], "Region": ["North", "South"]})
        exc = Exception('Binder Error: Referenced column "Revennue" not found')
        sql = "SELECT Revennue FROM data"
        err = diagnose_sql_error(exc, sql, df)
        self.assertEqual(err["code"], "COLUMN_NOT_FOUND")
        self.assertEqual(err["affected_column"], "Revennue")
        self.assertTrue("Revenue" in err["message"])
        print("[PASS] SQL column typo diagnosed with fuzzy match suggestion.")

    def test_7_sql_table_not_found(self):
        print("[RUN] test_7_sql_table_not_found")
        exc = Exception('Binder Error: Table "file_abc" does not exist')
        sql = "SELECT * FROM file_abc"
        err = diagnose_sql_error(exc, sql, None)
        self.assertEqual(err["code"], "TABLE_NOT_FOUND")
        self.assertEqual(err["severity"], "error")
        print("[PASS] SQL table not found diagnosed.")

    def test_8_empty_result_date_range(self):
        print("[RUN] test_8_empty_result_date_range")
        # Date column
        df = pd.DataFrame({
            "Date": pd.to_datetime(["2023-01-01", "2023-12-31"]),
            "Region": ["North", "South"]
        })
        sql = "SELECT * FROM data WHERE Date > '2024-01-01'"
        err = diagnose_empty_result(sql, df, "Show sales in 2024")
        self.assertEqual(err["code"], "EMPTY_RESULT")
        self.assertEqual(err["severity"], "info")
        self.assertTrue("2023-01-01" in err["message"])
        self.assertTrue("2023-12-31" in err["message"])
        print("[PASS] empty SQL query result with date ranges diagnosed.")

    def test_9_agent_timeout(self):
        print("[RUN] test_9_agent_timeout")
        # Large dataframe
        df = pd.DataFrame({
            "val": [1] * 120_000
        })
        exc = Exception("asyncio timeout")
        err = diagnose_agent_error(exc, "insight", df, "Get breakdown")
        self.assertEqual(err["code"], "AGENT_TIMEOUT")
        self.assertEqual(err["severity"], "warning")
        self.assertTrue("120,000" in err["message"])
        print("[PASS] agent timeout with row count context diagnosed.")

    def test_10_format_for_user(self):
        print("[RUN] test_10_format_for_user")
        err = {
            "code": "TEST_CODE",
            "title": "Test Title",
            "message": "This is a test warning.",
            "suggestions": ["Do this", "Do that"],
            "severity": "warning",
            "affected_rows": (10, 20)
        }
        md = format_for_user(err)
        self.assertTrue("🟡" in md)
        self.assertTrue("Test Title" in md)
        self.assertTrue("affected rows: 10–20" in md.lower())
        self.assertTrue("Do this" in md)
        print("[PASS] format_for_user renders beautiful markdown.")

if __name__ == "__main__":
    unittest.main()
