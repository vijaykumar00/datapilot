"""
test_suggestions.py — E2E verification for Phase 8 Smart AI Assistant Experience.
Tests the suggestion_engine.py deterministic rules against synthetic DataFrames.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import pandas as pd
import numpy as np
from core.suggestion_engine import generate_suggestions, build_greeting

print("[START] Phase 8 Smart AI Suggestions E2E Tests...\n")

# ════════════════════════════════════════════════════════════════════
# TEST 1: Forecast opportunity — date + numeric column
# ════════════════════════════════════════════════════════════════════
print("[Test 1] Forecast opportunity — date + revenue column...")

df_forecast = pd.DataFrame({
    "date": pd.date_range("2023-01-01", periods=20, freq="ME").astype(str),
    "revenue": np.random.uniform(1000, 5000, 20),
    "product": ["Widget"] * 20,
})
suggestions = generate_suggestions(df_forecast, "sales.csv", {})
types = [s["type"] for s in suggestions]
ids = [s["id"] for s in suggestions]

print(f"  Generated {len(suggestions)} suggestions: {ids}")
assert "forecast" in types, "Should suggest forecast when date + numeric present"
forecast_sg = next(s for s in suggestions if s["type"] == "forecast")
assert "revenue" in forecast_sg["prompt"].lower() or "date" in forecast_sg["detected_evidence"].lower()
print("[SUCCESS] Forecast suggestion generated.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 2: Duplicate IDs detection (Priority CRITICAL)
# ════════════════════════════════════════════════════════════════════
print("[Test 2] Duplicate ID detection...")

df_dupes = pd.DataFrame({
    "invoice_id": [101, 102, 103, 102, 104, 101, 105],  # 2 dupes
    "amount": [500, 300, 700, 300, 200, 500, 100],
})
suggestions_dupes = generate_suggestions(df_dupes, "invoices.csv", {})
dupe_suggestions = [s for s in suggestions_dupes if "dedup" in s["id"]]

print(f"  Dedup suggestions: {[s['title'] for s in dupe_suggestions]}")
assert len(dupe_suggestions) > 0, "Should detect duplicate invoice_id"
assert dupe_suggestions[0]["priority"] == 1, "Duplicate IDs must be CRITICAL (priority=1)"
assert "2" in dupe_suggestions[0]["detected_evidence"] or "Duplicate" in dupe_suggestions[0]["title"]
print("[SUCCESS] Duplicate ID suggestion generated with critical priority.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 3: Missing values detection (Priority CRITICAL)
# ════════════════════════════════════════════════════════════════════
print("[Test 3] Missing value detection — column with 40% nulls...")

df_nulls = pd.DataFrame({
    "product": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
    "revenue": [100, None, None, None, 500, None, 700, None, 200, 100],  # 40% null
    "region": ["North"] * 10,
})
suggestions_nulls = generate_suggestions(df_nulls, "data.csv", {})
null_sg = next((s for s in suggestions_nulls if s["id"] == "suggest_fix_nulls"), None)

assert null_sg is not None, "Should detect 40% null column"
assert null_sg["priority"] == 1, "Missing values must be CRITICAL"
assert "revenue" in null_sg["description"].lower()
assert "50" in null_sg["detected_evidence"]  # 5 nulls out of 10 = 50%
print(f"  Null suggestion: {null_sg['title']}")
print("[SUCCESS] Missing values suggestion with correct percentage.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 4: No critical issues — only quality suggestions below 5% threshold
# ════════════════════════════════════════════════════════════════════
print("[Test 4] Clean data — no CRITICAL suggestions for < 5% nulls...")

df_clean = pd.DataFrame({
    "category": ["A", "B", "C", "D", "E"] * 10,
    "sales": np.random.uniform(500, 2000, 50),
    "region": ["North", "South", "East", "West", "Central"] * 10,
})
suggestions_clean = generate_suggestions(df_clean, "clean_data.csv", {})
critical = [s for s in suggestions_clean if s["priority"] == 1]
assert len(critical) == 0, f"Clean data should have no CRITICAL suggestions, got: {[s['id'] for s in critical]}"
print(f"  Suggestions: {[s['type'] for s in suggestions_clean]}")
print("[SUCCESS] No false-positive critical alerts on clean data.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 5: Chart opportunity — categorical + numeric
# ════════════════════════════════════════════════════════════════════
print("[Test 5] Chart opportunity — categorical + numeric columns...")

df_chart = pd.DataFrame({
    "region": ["North", "South", "East", "West"] * 5,
    "sales": np.random.uniform(1000, 5000, 20),
})
suggestions_chart = generate_suggestions(df_chart, "regions.csv", {})
chart_types = [s["type"] for s in suggestions_chart]
print(f"  Types: {chart_types}")
assert "visualize" in chart_types, "Should suggest visualize for categorical + numeric"
print("[SUCCESS] Chart suggestion generated.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 6: Summary always present for files with >= 10 rows
# ════════════════════════════════════════════════════════════════════
print("[Test 6] Summary always generated for files with >= 10 rows...")

df_small = pd.DataFrame({
    "a": range(15),
    "b": [float(x) * 1.5 for x in range(15)],
})
suggestions_small = generate_suggestions(df_small, "small.csv", {})
summary_sg = next((s for s in suggestions_small if s["id"] == "suggest_summary"), None)
assert summary_sg is not None, "Summary suggestion should always be present for >= 10 rows"
assert summary_sg["priority"] == 3  # P_MEDIUM
print(f"  Summary: {summary_sg['title']}")
print("[SUCCESS] Summary suggestion always present.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 7: Results capped at 6, sorted by priority
# ════════════════════════════════════════════════════════════════════
print("[Test 7] Suggestions capped at 6 and ordered by priority...")

# A complex file that would trigger many rules
df_complex = pd.DataFrame({
    "invoice_id": list(range(1, 20)) + [1],  # 1 duplicate
    "date": pd.date_range("2023-01-01", periods=20, freq="ME").astype(str),
    "revenue": [float(i * 100) if i % 4 != 0 else None for i in range(20)],  # nulls
    "product": ["Widget", "Gadget", "Donut"] * 6 + ["Widget", "Gadget"],
    "region": ["North", "South", "East", "West", "Central"] * 4,
    "cost": np.random.uniform(50, 500, 20),
})
suggestions_complex = generate_suggestions(df_complex, "complex.csv", {})
print(f"  Count: {len(suggestions_complex)}")
assert len(suggestions_complex) <= 6, f"Should not exceed 6 suggestions, got {len(suggestions_complex)}"

priorities = [s["priority"] for s in suggestions_complex]
assert priorities == sorted(priorities), f"Suggestions not sorted by priority: {priorities}"
print(f"  Priorities: {priorities}")
print("[SUCCESS] Cap at 6 and priority sort confirmed.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 8: build_greeting produces markdown-formatted text
# ════════════════════════════════════════════════════════════════════
print("[Test 8] Greeting message generation...")

suggestions_for_greeting = generate_suggestions(df_forecast, "sales.csv", {})
greeting = build_greeting("sales.csv", 20, 3, suggestions_for_greeting)
print(f"  Greeting preview: {greeting[:120]}...")
assert "sales.csv" in greeting, "Greeting should mention filename"
assert "20" in greeting, "Greeting should mention row count"
assert "**" in greeting, "Greeting should use markdown bold"
assert "Click any suggestion" in greeting, "Greeting should have CTA"
print("[SUCCESS] Greeting message correctly formatted.\n")

# ════════════════════════════════════════════════════════════════════
# TEST 9: Type mismatch detection — text columns containing numbers
# ════════════════════════════════════════════════════════════════════
print("[Test 9] Type mismatch — numeric data stored as string...")

df_types = pd.DataFrame({
    "product": ["A", "B", "C"] * 5,
    "price_str": ["10.5", "20.0", "15.3"] * 5,   # Numeric stored as string
})
suggestions_types = generate_suggestions(df_types, "prices.csv", {})
type_fix = next((s for s in suggestions_types if s["id"] == "suggest_type_fix"), None)
assert type_fix is not None, "Should detect price_str as type mismatch"
assert "price_str" in type_fix["description"]
print(f"  Type fix: {type_fix['title']}")
print("[SUCCESS] Type mismatch suggestion correctly identified.\n")

print("[COMPLETE] All 9 Phase 8 Smart AI Suggestions E2E tests passed! [PASS]")
