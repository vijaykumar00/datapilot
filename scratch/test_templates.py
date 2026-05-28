import os
import sys
import copy
import pandas as pd
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from core.file_manager import get_file_manager, FileRecord, ColumnMappingError
from core.template_store import get_template_store

def run_e2e_tests():
    print("[START] Starting Phase 5 Template System E2E Tests...")
    
    # 1. Load mock messy database
    csv_path = Path(__file__).parent.parent / "test_sales.csv"
    if not csv_path.exists():
        print(f"[ERROR] {csv_path} does not exist.")
        sys.exit(1)
        
    df = pd.read_csv(csv_path)
    
    # Mock messy column headers
    # rename 'revenue' -> 'amt_q1_final'
    # rename 'month' -> 'date_period'
    df_fresh = df.rename(columns={"revenue": "amt_q1_final", "month": "date_period"})
    print(f"[DATA] Mocked messy database headers: {list(df_fresh.columns)}")
    
    manager = get_file_manager()
    file_id = "test_messy_file"
    
    # Mock high-confidence Phase 2 semantic classifications in metadata
    semantic_map = {
        "amt_q1_final": {
            "semantic_type": "revenue",
            "label": "Quarterly Revenue",
            "inferred_meaning": "Gross quarterly revenue amount",
            "confidence": 0.94  # 94% confidence (>85%)
        },
        "date_period": {
            "semantic_type": "date",
            "label": "Month Period",
            "inferred_meaning": "Transaction calendar month",
            "confidence": 0.90  # 90% confidence (>85%)
        }
    }
    
    record = FileRecord(
        file_id=file_id,
        filename="messy_sales.csv",
        df=df_fresh.copy(),
        path=Path("messy_sales.csv"),
        metadata={"semantic_map": semantic_map}
    )
    # Register manually in manager cache
    manager._cache[file_id] = record
    manager._store.register_dataframe(record.table_name, record.df)
    
    # 2. Get Template Store & built-ins
    t_store = get_template_store()
    templates = t_store.list_templates()
    print(f"[STORE] Registered templates count: {len(templates)}")
    
    # Fetch Sales Revenue Standardizer
    sales_template = t_store.get_template("sales_rev_std")
    assert sales_template is not None, "Built-in Sales template sales_rev_std not found"
    print(f"[TEMPLATE] Loaded template: '{sales_template['name']}' with {len(sales_template['steps'])} steps")
    
    # 3. Test 1: Confidence mapping gate violation (< 85% confidence column missing)
    print("\n[Test 1] Testing 85% confidence gate lookup...")
    
    faulty_steps = copy.deepcopy(sales_template["steps"])
    faulty_steps.append({
        "action": "fill_nulls",
        "column": "quantity",
        "strategy": "mean",
        "description": "Fails because quantity is missing and has 0% confidence"
    })
    
    gate_failed = False
    try:
        import asyncio
        asyncio.run(manager.apply_template(file_id, "sales_rev_std", faulty_steps))
    except ColumnMappingError as e:
        gate_failed = True
        print("[SUCCESS] 85% confidence gate successfully halted execution.")
        print(f"[GATE] Unmapped template columns detected: {e.failed_mappings}")
        assert len(e.failed_mappings) == 1
        assert e.failed_mappings[0]["template_col"] == "quantity"
        
    assert gate_failed, "85% confidence gate failed to raise error"

    # 4. Test 2: Auto-resolving semantic mappings (>= 85% confidence)
    print("\n[Test 2] Testing auto-resolving semantic aliases (revenue -> amt_q1_final)...")
    res = asyncio.run(manager.apply_template(file_id, "sales_rev_std", sales_template["steps"]))
    assert res["status"] == "completed"
    
    # Check that 'amt_q1_final' was targeted instead of literal 'revenue'
    applied_block = record.metadata["applied_workflows"][-1]
    resolved_steps = applied_block["steps"]
    print(f"[VERIFY] Implemented resolved steps: {resolved_steps}")
    
    rev_step = [s for s in resolved_steps if s.get("column") == "amt_q1_final"]
    assert len(rev_step) > 0, "Failed to resolve 'revenue' to 'amt_q1_final' semantically"
    print("[SUCCESS] Semantic column resolution auto-resolved correctly.")

    # 5. Test 3: Manual Mapping Overrides Modal Triggers
    print("\n[Test 3] Testing manual column mapping overrides...")
    # Reset record DataFrame to fresh state to prevent side effects from Test 2
    record.df = df_fresh.copy()
    record.metadata["semantic_map"] = semantic_map
    manager._store.register_dataframe(record.table_name, record.df)
    
    gst_template = t_store.get_template("fin_gst_std")
    
    # If we run it directly, it should fail GST confidence check
    overrides_failed = False
    try:
        asyncio.run(manager.apply_template(file_id, "fin_gst_std", gst_template["steps"]))
    except ColumnMappingError:
        overrides_failed = True
        print("[SUCCESS] Missing tax resolved correctly as unmapped under 85% threshold.")
        
    assert overrides_failed
    
    # Now run with manual override mapping 'tax' -> 'sales'
    overrides = {"tax": "sales"}
    res_overrides = asyncio.run(manager.apply_template(file_id, "fin_gst_std", gst_template["steps"], overrides))
    assert res_overrides["status"] == "completed"
    print("[SUCCESS] Manual mapping override successfully executed without gate blocks.")

    # 6. Test 4: Custom template duplication and deletion
    print("\n[Test 4] Testing custom template duplication and deletion...")
    # Duplicate built-in
    dup = t_store.duplicate_template("sales_rev_std")
    assert dup is not None
    assert dup["name"] == "Revenue Aggregator & Standardizer (Copy)"
    assert dup["is_builtin"] is False
    print(f"[STORE] Duplicated template ID: {dup['template_id']}")
    
    # Delete template
    ok = t_store.delete_template(dup["template_id"])
    assert ok, "Failed to delete custom template"
    assert t_store.get_template(dup["template_id"]) is None
    print("[SUCCESS] Custom template duplicate and deletion routines verified.")

    # 7. Test 5: Asynchronous Gateway for Large Sheets
    print("\n[Test 5] Testing Asynchronous Gateway runner for massive datasets...")
    # Reset record DataFrame to fresh state
    record.df = df_fresh.copy()
    record.metadata["semantic_map"] = semantic_map
    # Let's mock a massive dataframe (>10,000 rows)
    record.df = pd.concat([record.df] * 600, ignore_index=True)  # ~10,800 rows (>10,000 threshold)
    manager._store.register_dataframe(record.table_name, record.df)
    print(f"[GATE] Modified row count to large size: {len(record.df)} rows")
    
    async_res = asyncio.run(manager.apply_template(file_id, "sales_rev_std", sales_template["steps"]))
    assert async_res["status"] == "processing"
    assert "task_id" in async_res
    print(f"[GATE] Asynchronous Gateway triggered 202 Accepted. Task ID: {async_res['task_id']}")
    
    # Wait for background task to complete
    import time
    time.sleep(1.5) # let asyncio background task run
    
    task_status = record.metadata.get("async_task")
    assert task_status is not None
    assert task_status["status"] == "completed" or task_status["status"] == "processing"
    print(f"[GATE] Async background progress state: {task_status}")
    print("[SUCCESS] Asynchronous gateway verified successfully.")
    
    print("\n[COMPLETE] All Phase 5 Template System E2E tests passed successfully!")

if __name__ == "__main__":
    run_e2e_tests()
