"""
test_explainability.py — E2E verification for Phase 6 AI Explainability & Trust System.
Tests that all three agent types produce well-formed metadata.explain blocks.
"""

import sys
import asyncio
import pandas as pd
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from agents.insight_agent import _build_sql_explain
from agents.forecast_agent import _build_forecast_explain
from agents.viz_agent import _build_chart_explain


def run_tests():
    print("[START] Phase 6 AI Explainability E2E Tests...\n")

    # ── Load test data ────────────────────────────────────────────────────────
    csv_path = Path(__file__).parent.parent / "test_sales.csv"
    df = pd.read_csv(csv_path)
    print(f"[DATA] Loaded dataset: {list(df.columns)} | {len(df)} rows\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 1: SQL Explainability - complex query
    # ════════════════════════════════════════════════════════════════
    print("[Test 1] SQL Explainability — clause decomposition...")

    sql = (
        "SELECT product, SUM(revenue) as total_revenue "
        "FROM file_abc123 "
        "WHERE revenue > 0 "
        "GROUP BY product "
        "ORDER BY total_revenue DESC "
        "LIMIT 10"
    )
    explanation = "Groups by product and sums revenue, ordered by highest total"
    explain = _build_sql_explain(sql, explanation, row_count=10, table_name="file_abc123")

    assert explain["type"] == "sql", "Expected type=sql"
    assert explain["sql"] == sql, "Expected sql to be preserved"
    sections = explain["sections"]
    labels = [s["label"] for s in sections]

    print(f"  Sections generated: {labels}")
    assert "Query Intent" in labels, "Missing Query Intent section"
    assert "Fields Selected" in labels, "Missing Fields Selected section"
    assert "Data Source" in labels, "Missing Data Source section"
    assert "Row Filters" in labels, "Missing Row Filters section"
    assert "Grouping" in labels, "Missing Grouping section"
    assert "Sorting" in labels, "Missing Sorting section"
    assert "Row Limit" in labels, "Missing Row Limit section"
    assert "Execution Result" in labels, "Missing Execution Result section"
    assert "Columns Referenced" in labels, "Missing Columns Referenced section"

    # Validate content correctness
    intent = next(s for s in sections if s["label"] == "Query Intent")
    assert explanation in intent["content"], "Intent content mismatch"

    limit_sec = next(s for s in sections if s["label"] == "Row Limit")
    assert "10" in limit_sec["content"], "Limit value should be 10"

    fields_sec = next(s for s in sections if s["label"] == "Fields Selected")
    assert isinstance(fields_sec["content"], list), "Fields should be a list"
    # SUM aggregation should be detected
    sum_fields = [f for f in fields_sec["content"] if "SUM" in f]
    assert len(sum_fields) > 0, "SUM aggregation should be detected in Fields Selected"

    print("[SUCCESS] SQL Explainability — all sections validated.\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 2: SQL Explainability - simple query (no WHERE/GROUP BY)
    # ════════════════════════════════════════════════════════════════
    print("[Test 2] SQL Explainability — simple SELECT...")
    simple_sql = "SELECT month, revenue FROM file_xyz LIMIT 100"
    explain2 = _build_sql_explain(simple_sql, "Fetches all months and revenue values", 100, "file_xyz")
    labels2 = [s["label"] for s in explain2["sections"]]
    assert "Row Filters" not in labels2, "WHERE should not appear in simple SELECT"
    assert "Grouping" not in labels2, "GROUP BY should not appear in simple SELECT"
    assert "Fields Selected" in labels2
    assert "Row Limit" in labels2
    print(f"  Sections: {labels2}")
    print("[SUCCESS] Simple SQL — no phantom clause sections.\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 3: Forecast Explainability — Holt-Winters path
    # ════════════════════════════════════════════════════════════════
    print("[Test 3] Forecast Explainability — Holt-Winters method...")
    explain_hw = _build_forecast_explain(
        method="holt_winters",
        value_col="revenue",
        date_col="month",
        n_periods=3,
        n_points=24,
        r2=None,
        last_val=15000.0,
        next_val=16200.0,
        pct_change=8.0,
        resample_freq="ME",
        warnings=[],
    )

    assert explain_hw["type"] == "forecast"
    hw_labels = [s["label"] for s in explain_hw["sections"]]
    print(f"  Sections: {hw_labels}")
    assert "Method Selected" in hw_labels
    assert "Data Basis" in hw_labels
    assert "Detected Trend" in hw_labels
    assert "Confidence Interpretation" in hw_labels
    assert "Notices" not in hw_labels, "No warnings should produce no Notices section"

    method_sec = next(s for s in explain_hw["sections"] if s["label"] == "Method Selected")
    assert "Holt-Winters" in method_sec["content"][0], "Method label should mention Holt-Winters"
    assert "24" in method_sec["content"][1], "Data points count should appear in rationale"

    trend_sec = next(s for s in explain_hw["sections"] if s["label"] == "Detected Trend")
    assert "Rising" in trend_sec["content"], "8% positive change should be Rising"

    conf_sec = next(s for s in explain_hw["sections"] if s["label"] == "Confidence Interpretation")
    assert "95%" in conf_sec["content"], "HW confidence should mention 95%"

    print("[SUCCESS] Forecast Explainability (HW) — all sections validated.\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 4: Forecast Explainability — Linear Regression fallback
    # ════════════════════════════════════════════════════════════════
    print("[Test 4] Forecast Explainability — Linear Regression fallback...")
    explain_lr = _build_forecast_explain(
        method="linear_regression",
        value_col="sales",
        date_col=None,
        n_periods=3,
        n_points=5,
        r2=0.62,
        last_val=800.0,
        next_val=750.0,
        pct_change=-6.25,
        resample_freq=None,
        warnings=["Only 5 data points — using linear regression."],
    )

    assert explain_lr["type"] == "forecast"
    lr_labels = [s["label"] for s in explain_lr["sections"]]
    assert "Notices" in lr_labels, "Warnings should produce a Notices section"
    assert "Method Selected" in lr_labels

    method_lr_sec = next(s for s in explain_lr["sections"] if s["label"] == "Method Selected")
    assert "Linear Regression" in method_lr_sec["content"][0]
    assert "no date column" in method_lr_sec["content"][1]

    trend_lr = next(s for s in explain_lr["sections"] if s["label"] == "Detected Trend")
    assert "Declining" in trend_lr["content"], "-6.25% should be Declining"

    conf_lr = next(s for s in explain_lr["sections"] if s["label"] == "Confidence Interpretation")
    assert "±1 standard deviation" in conf_lr["content"], "LR confidence should mention std dev"

    basis_lr = next(s for s in explain_lr["sections"] if s["label"] == "Data Basis")
    assert any("No date column" in line for line in basis_lr["content"]), "Should note missing date column"

    print("[SUCCESS] Forecast Explainability (LR) — all sections validated.\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 5: Chart Explainability — bar chart with real data
    # ════════════════════════════════════════════════════════════════
    print("[Test 5] Chart Explainability — bar chart with real CSV data...")
    chart_info = {
        "chart_type": "bar",
        "x_column": "product",
        "y_column": "revenue",
        "title": "Revenue by Product",
    }
    explain_bar = _build_chart_explain(chart_info, df, detection_method="keyword")

    assert explain_bar["type"] == "chart"
    assert explain_bar["chart_type"] == "bar"
    bar_labels = [s["label"] for s in explain_bar["sections"]]
    print(f"  Sections: {bar_labels}")
    assert "Chart Type Rationale" in bar_labels
    assert "Axis Mapping" in bar_labels
    assert "Aggregation Applied" in bar_labels
    assert "Data Scope" in bar_labels

    rationale = next(s for s in explain_bar["sections"] if s["label"] == "Chart Type Rationale")
    assert "Rule Matched" in rationale["content"][0], "Keyword detection should be Rule Matched"
    assert "bar" in rationale["content"][0]

    agg_sec = next(s for s in explain_bar["sections"] if s["label"] == "Aggregation Applied")
    assert any("Highest" in line for line in agg_sec["content"]), "Should report top category"
    assert any("Lowest" in line for line in agg_sec["content"]), "Should report bottom category"

    print("[SUCCESS] Chart Explainability (bar) — all sections validated.\n")

    # ════════════════════════════════════════════════════════════════
    # TEST 6: Chart Explainability — line chart trend detection
    # ════════════════════════════════════════════════════════════════
    print("[Test 6] Chart Explainability — line chart trend detection...")
    chart_info_line = {
        "chart_type": "line",
        "x_column": "month",
        "y_column": "revenue",
        "title": "Revenue over Time",
        "reasoning": "Time-series trend detected from keyword 'over time'",
    }
    explain_line = _build_chart_explain(chart_info_line, df, detection_method="llm")

    line_labels = [s["label"] for s in explain_line["sections"]]
    assert "Trend Detected" in line_labels, "Line chart should have Trend Detected section"

    rationale_line = next(s for s in explain_line["sections"] if s["label"] == "Chart Type Rationale")
    assert "AI Selected" in rationale_line["content"][0], "LLM detection should be AI Selected"
    assert "AI reasoning" in rationale_line["content"][2], "Reasoning should be included"

    print("[SUCCESS] Chart Explainability (line) — all sections validated.\n")

    print("[COMPLETE] All 6 Phase 6 AI Explainability E2E tests passed successfully! [PASS]")


if __name__ == "__main__":
    run_tests()
