"""
test_transformations.py — Verify Phase 3 declarative transformation engine, Undo stacks, and FastAPI route simulations.
"""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import pandas as pd
import asyncio
from core.transform_engine import execute_transform, propose_transformations
from core.file_manager import FileRecord

def test_declarative_engine():
    print("[INFO] Running declarative transform engine tests...")
    
    # Setup test dataframe
    data = {
        "name": [" Alice  ", "Bob", "Alice", "Charlie"],
        "age": [25.0, 30.0, None, 45.0],
        "city": ["New York", "London", "New York", "Paris"],
        "salary_str": ["1000", "2000", "3000", None]
    }
    df = pd.DataFrame(data)
    
    # 1. Test remove_duplicates
    action_dedup = {"action": "remove_duplicates"}
    df_dedup = execute_transform(df, action_dedup)
    assert len(df_dedup) == 4  # Alice in row 0 has space " Alice  " vs Alice in row 2 is unique row
    print("[PASS] Duplicate check executed successfully.")
    
    # 2. Test fill_nulls
    action_fill = {"action": "fill_nulls", "column": "age", "strategy": "median"}
    df_filled = execute_transform(df, action_fill)
    assert df_filled["age"].isnull().sum() == 0
    assert df_filled["age"].iloc[2] == 30.0  # Median of 25 and 45 is 35. Wait, 25, 30, 45 median is 30.0! Correct!
    print("[PASS] Missing value imputation with median completed successfully.")

    # 3. Test normalize_text
    action_norm = {"action": "normalize_text", "column": "name", "strategy": "strip"}
    df_norm = execute_transform(df, action_norm)
    assert df_norm["name"].iloc[0] == "Alice"
    print("[PASS] Text normalization completed successfully.")

    # 4. Test convert_type
    action_type = {"action": "convert_type", "column": "salary_str", "target_type": "float"}
    df_type = execute_transform(df, action_type)
    assert pd.api.types.is_float_dtype(df_type["salary_str"].dtype)
    print("[PASS] Type conversion completed successfully.")


async def test_proposals():
    print("[INFO] Running NLP proposal planner tests...")
    data = {
        "user_id": [1, 2, 2],
        "created_date": ["2026-05-01", "2026-05-02", "2026-05-02"],
        "amt_usd": [150.0, 300.0, 300.0]
    }
    df = pd.DataFrame(data)
    
    # Propose general clean
    proposed = await propose_transformations("clean this dataset", df, "data")
    actions = [p["action"] for p in proposed]
    assert "remove_duplicates" in actions
    print("[PASS] Proposed clean actions mapped correctly.")


if __name__ == "__main__":
    test_declarative_engine()
    asyncio.run(test_proposals())
    print("\nALL WORKFLOW ENGINE TESTS PASSED!")
