import os
import sys
import unittest
from fastapi.testclient import TestClient

# Add current directory to path to import backend core modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
from core.explain_enricher import enrich_explain_metadata
from agents.insight_agent import _build_sql_explain
from agents.forecast_agent import _build_forecast_explain
from agents.viz_agent import _build_chart_explain

class TestExplainableAI(unittest.TestCase):
    def test_enrich_explain_metadata_defaults(self):
        """Test central explainability metadata enricher adds defaults."""
        meta = {
            "row_count": 42,
            "sql": "SELECT * FROM test_table"
        }
        enriched = enrich_explain_metadata(meta, [], None)
        
        self.assertEqual(enriched["data_source"], "N/A")
        self.assertEqual(enriched["sheet"], "N/A")
        self.assertEqual(enriched["filters"], "None")
        self.assertEqual(enriched["sql"], "SELECT * FROM test_table")
        self.assertEqual(enriched["confidence_score"], 0.90)
        self.assertIn("SQL returned row count: 42", enriched["intermediate_calculations"])

    def test_sql_explain_builder(self):
        """Test SQL explain block contains specific fields."""
        explain = _build_sql_explain(
            sql="SELECT age, name FROM users WHERE age > 20 GROUP BY age ORDER BY age LIMIT 5",
            explanation="Selected users over 20",
            row_count=5,
            table_name="users",
            filename="users_data.csv",
            sheet="Sheet1"
        )
        
        self.assertEqual(explain["data_source"], "users_data.csv")
        self.assertEqual(explain["sheet"], "Sheet1")
        self.assertEqual(explain["filters"], "age > 20")
        self.assertEqual(explain["confidence_score"], 0.98)
        self.assertIn("age", explain["columns"])
        self.assertIn("SQL returned row count: 5", explain["intermediate_calculations"])

    def test_forecast_explain_builder(self):
        """Test forecast explain block contains specific fields."""
        explain = _build_forecast_explain(
            method="linear_regression",
            value_col="revenue",
            date_col="date",
            n_periods=3,
            n_points=24,
            r2=0.85,
            last_val=100.0,
            next_val=110.0,
            pct_change=10.0,
            resample_freq="ME",
            warnings=[],
            filename="sales_history.xlsx",
            sheet="Monthly Sales"
        )
        
        self.assertEqual(explain["data_source"], "sales_history.xlsx")
        self.assertEqual(explain["sheet"], "Monthly Sales")
        self.assertEqual(explain["confidence_score"], 0.85)
        self.assertIn("revenue", explain["columns"])
        self.assertIn("date", explain["columns"])
        self.assertIn("R² coefficient: 0.850", explain["intermediate_calculations"])

if __name__ == "__main__":
    unittest.main()
