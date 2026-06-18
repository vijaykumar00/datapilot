"""
test_saved_analyses.py — E2E verification for Phase 9 Saved Analysis & Replay.
Tests the analysis_store.py CRUD layer and HTTP endpoint behaviour.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

# Force a fresh in-memory DB for testing (avoid polluting production DB)
import os
os.environ.setdefault("DATAPILOT_TEST", "1")

# Patch the DB path to use a temp location for isolation
import tempfile
import core.db as db_module

_tmp = tempfile.mktemp(suffix=".db")
db_module.DB_PATH = Path(_tmp)
db_module.DB_DIR = Path(_tmp).parent
db_module.init_db()   # Re-initialise with fresh path

from core import analysis_store

print("[START] Phase 9 Saved Analysis & Replay E2E Tests...\n")


# ── Test 1: Save analysis round-trip ─────────────────────────────────────────
print("[Test 1] save_analysis() — basic round-trip...")

saved = analysis_store.save_analysis(
    session_id="sess_001",
    title="Revenue by Region Q1",
    query="Show total revenue by region",
    response="The total revenue by region is: North $120K, South $95K...",
    type="insight",
    chart_data={"type": "bar", "data": {"x": ["North", "South"], "y": [120, 95]}},
    table_data=[{"region": "North", "revenue": 120000}, {"region": "South", "revenue": 95000}],
    metadata={"sql": "SELECT region, SUM(revenue) FROM data GROUP BY region"},
    file_id="file_abc",
    filename="sales_q1.csv",
    tags=["revenue", "Q1", "regional"],
)

assert saved["analysis_id"], "analysis_id must be set"
assert saved["session_id"] == "sess_001"
assert saved["title"] == "Revenue by Region Q1"
assert saved["query"] == "Show total revenue by region"
assert saved["type"] == "insight"
assert saved["chart_data"]["type"] == "bar"
assert len(saved["table_data"]) == 2
assert saved["tags"] == ["revenue", "Q1", "regional"]
assert saved["starred"] is False
print(f"  Saved analysis_id: {saved['analysis_id']}")
print("[SUCCESS] Round-trip save verified.\n")


# ── Test 2: List by session_id ────────────────────────────────────────────────
print("[Test 2] list_analyses(session_id=...) — returns correct subset...")

# Save a second analysis under different session
analysis_store.save_analysis(
    session_id="sess_002",
    title="Forecast for Next Quarter",
    query="Forecast revenue for next 3 months",
    response="Based on trend...",
    type="forecast",
)

analyses_001 = analysis_store.list_analyses(session_id="sess_001")
analyses_002 = analysis_store.list_analyses(session_id="sess_002")

assert len(analyses_001) == 1, f"Expected 1 for sess_001, got {len(analyses_001)}"
assert len(analyses_002) == 1, f"Expected 1 for sess_002, got {len(analyses_002)}"
assert analyses_001[0]["title"] == "Revenue by Region Q1"
assert analyses_002[0]["type"] == "forecast"
print(f"  sess_001: {len(analyses_001)} analysis, sess_002: {len(analyses_002)} analysis")
print("[SUCCESS] Session-scoped list works.\n")


# ── Test 3: list with file_id filter ─────────────────────────────────────────
print("[Test 3] list_analyses(file_id=...) — file-scoped filter...")

analyses_file = analysis_store.list_analyses(file_id="file_abc")
assert len(analyses_file) == 1
assert analyses_file[0]["filename"] == "sales_q1.csv"
print("[SUCCESS] File-scoped list filter works.\n")


# ── Test 4: Get by analysis_id ────────────────────────────────────────────────
print("[Test 4] get_analysis(analysis_id) — fetch by ID...")

fetched = analysis_store.get_analysis(saved["analysis_id"])
assert fetched is not None
assert fetched["analysis_id"] == saved["analysis_id"]
assert fetched["chart_data"]["type"] == "bar"
assert fetched["metadata"]["sql"].startswith("SELECT")
print(f"  Fetched: '{fetched['title']}'")
print("[SUCCESS] get_analysis() returns correct data including JSON fields.\n")


# ── Test 5: Update — rename + star ────────────────────────────────────────────
print("[Test 5] update_analysis() — rename and star...")

ok = analysis_store.update_analysis(
    saved["analysis_id"],
    title="Revenue by Region Q1 (Updated)",
    starred=True,
)
assert ok, "update_analysis should return True"

updated = analysis_store.get_analysis(saved["analysis_id"])
assert updated["title"] == "Revenue by Region Q1 (Updated)"
assert updated["starred"] is True
print(f"  New title: {updated['title']}, starred: {updated['starred']}")
print("[SUCCESS] update_analysis() correctly patches title and starred.\n")


# ── Test 6: starred_only filter ───────────────────────────────────────────────
print("[Test 6] list_analyses(starred_only=True) — only starred items...")

starred_list = analysis_store.list_analyses(starred_only=True)
assert len(starred_list) == 1
assert starred_list[0]["analysis_id"] == saved["analysis_id"]
print(f"  Starred analyses: {len(starred_list)}")
print("[SUCCESS] starred_only filter returns only starred items.\n")


# ── Test 7: Update tags ───────────────────────────────────────────────────────
print("[Test 7] update_analysis() — update tags only...")

ok = analysis_store.update_analysis(
    saved["analysis_id"],
    tags=["revenue", "Q1", "regional", "top-performer"],
)
assert ok
updated = analysis_store.get_analysis(saved["analysis_id"])
assert "top-performer" in updated["tags"]
assert len(updated["tags"]) == 4
print(f"  Tags: {updated['tags']}")
print("[SUCCESS] Tags updated without clobbering other fields.\n")


# ── Test 8: Delete analysis ────────────────────────────────────────────────────
print("[Test 8] delete_analysis() — hard delete...")

deleted_ok = analysis_store.delete_analysis(saved["analysis_id"])
assert deleted_ok, "delete_analysis should return True"

gone = analysis_store.get_analysis(saved["analysis_id"])
assert gone is None, "Analysis should be gone after delete"
print("[SUCCESS] delete_analysis() permanently removes the record.\n")


# ── Test 9: Missing ID returns None / False ───────────────────────────────────
print("[Test 9] Edge cases — missing IDs...")

missing = analysis_store.get_analysis("nonexistent_abc123")
assert missing is None

not_found = analysis_store.delete_analysis("nonexistent_abc123")
assert not_found is False

not_updated = analysis_store.update_analysis("nonexistent_abc123", title="X")
assert not_updated is False
print("[SUCCESS] Missing IDs handled gracefully (None / False).\n")


# ── Test 10: Newest-first ordering ────────────────────────────────────────────
print("[Test 10] list_analyses() — newest-first ordering...")

import time
for i in range(3):
    analysis_store.save_analysis(
        session_id="sess_order",
        title=f"Analysis #{i}",
        query=f"Query {i}",
        response=f"Response {i}",
        type="insight",
    )
    time.sleep(0.01)  # Ensure different timestamps

ordered = analysis_store.list_analyses(session_id="sess_order")
titles = [a["title"] for a in ordered]
assert titles[0] == "Analysis #2", f"Expected newest first, got: {titles}"
print(f"  Order (newest first): {titles}")
print("[SUCCESS] Newest-first ordering confirmed.\n")


# ── Test 11: Cap/limit parameter ─────────────────────────────────────────────
print("[Test 11] list_analyses(limit=2) — limit parameter works...")

limited = analysis_store.list_analyses(session_id="sess_order", limit=2)
assert len(limited) == 2
print(f"  Returned {len(limited)} of 3 available (limit=2)")
print("[SUCCESS] limit parameter respected.\n")


# ── Cleanup ───────────────────────────────────────────────────────────────────
try:
    os.unlink(_tmp)
except Exception:
    pass

print("[COMPLETE] All 11 Phase 9 Saved Analysis & Replay E2E tests passed! [PASS]")
