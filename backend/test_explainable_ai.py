import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from core.explain_enricher import enrich_explain_metadata
from agents.insight_agent import _build_sql_explain
from agents.forecast_agent import run_forecast


class TestExplainableAI(unittest.TestCase):
    def test_enrich_explain_metadata_defaults_without_fake_confidence(self):
        meta = {"row_count": 42, "sql": "SELECT * FROM test_table"}
        enriched = enrich_explain_metadata(meta, [], None)
        self.assertEqual(enriched["data_source"], "N/A")
        self.assertEqual(enriched["sheet"], "N/A")
        self.assertEqual(enriched["filters"], "None")
        self.assertEqual(enriched["sql"], "SELECT * FROM test_table")
        # No synthetic confidence numbers any more.
        self.assertIsNone(enriched["confidence_score"])
        self.assertIn("verification", enriched)
        self.assertIn("SQL returned row count: 42", enriched["intermediate_calculations"])

    def test_sql_explain_builder(self):
        explain = _build_sql_explain(
            sql="SELECT age, name FROM users WHERE age > 20 GROUP BY age ORDER BY age LIMIT 5",
            explanation="Selected users over 20",
            row_count=5,
            table_name="users",
            filename="users_data.csv",
            sheet="Sheet1",
        )
        self.assertEqual(explain["data_source"], "users_data.csv")
        self.assertEqual(explain["sheet"], "Sheet1")
        self.assertEqual(explain["filters"], "age > 20")
        self.assertIsNone(explain["confidence_score"])
        self.assertIn("SQL", explain["verification"])
        self.assertIn("age", explain["columns"])
        self.assertIn("SQL returned row count: 5", explain["intermediate_calculations"])

    def test_forecast_explain_is_grounded(self):
        dates = pd.date_range("2022-01-01", "2024-06-30", freq="D")
        df = pd.DataFrame({"date": dates.astype(str), "revenue": np.linspace(100, 300, len(dates))})
        out = run_forecast(df, "forecast revenue for the next 3 months", None, "sales_history.xlsx", "Monthly Sales")
        explain = out["metadata"]["explain"]
        self.assertEqual(explain["data_source"], "sales_history.xlsx")
        self.assertEqual(explain["sheet"], "Monthly Sales")
        self.assertIsNone(explain["confidence_score"])
        self.assertIn("revenue", explain["columns"])
        self.assertIn("date", explain["columns"])


if __name__ == "__main__":
    unittest.main()
