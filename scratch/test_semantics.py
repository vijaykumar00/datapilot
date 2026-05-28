"""
test_semantics.py — Verify semantic database mapping, column intelligence classifications, and token-limiting safety bounds.
"""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import pandas as pd
import asyncio
from core.insights import infer_semantic_metadata, profile_columns_semantically

def test_heuristic_mapping():
    print("[INFO] Running heuristic column intelligence tests...")
    
    # Test messy name amt_q1_final -> classified as revenue
    series_rev = pd.Series([120.5, 450.0, 920.1])
    meta_rev = infer_semantic_metadata("amt_q1_final", series_rev)
    assert meta_rev["semantic_type"] == "revenue", f"Expected revenue, got {meta_rev['semantic_type']}"
    assert "sales" in meta_rev["aliases"]
    print("[PASS] Messy revenue column classified correctly.")
    
    # Test messy name cust_phone -> classified as phone
    series_phone = pd.Series(["+1-555-0199", "555-3210"])
    meta_phone = infer_semantic_metadata("cust_phone", series_phone)
    assert meta_phone["semantic_type"] == "phone", f"Expected phone, got {meta_phone['semantic_type']}"
    assert "telephone" in meta_phone["aliases"]
    print("[PASS] Messy phone column classified correctly.")
    
    # Test index id -> id
    series_id = pd.Series([1001, 1002, 1003])
    meta_id = infer_semantic_metadata("invoice_idx", series_id)
    assert meta_id["semantic_type"] == "id", f"Expected id, got {meta_id['semantic_type']}"
    print("[PASS] Messy ID column classified correctly.")

async def test_bulk_limit():
    print("[INFO] Running bulk boundary mapping limits tests...")
    # Create 35 columns
    data = {f"col_{i}": [1, 2, 3] for i in range(35)}
    df = pd.DataFrame(data)
    
    sem_map = await profile_columns_semantically(df, table_name="test_table")
    assert len(sem_map) == 35
    print(f"[PASS] Successfully mapped {len(sem_map)} columns semantically.")

if __name__ == "__main__":
    test_heuristic_mapping()
    asyncio.run(test_bulk_limit())
    print("\nALL SEMANTIC ENGINE TESTS PASSED!")
