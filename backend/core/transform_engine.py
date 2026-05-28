"""
transform_engine.py — Declarative Pandas transformation execution engine.
Translates structured transformation actions into highly safe, deterministic operations.
"""

import logging
import pandas as pd
import numpy as np
from typing import Any, Dict

logger = logging.getLogger("datapilot.transform_engine")


def execute_transform(df: pd.DataFrame, action: Dict[str, Any]) -> pd.DataFrame:
    """Execute a single declarative transformation step safely on the dataframe."""
    op = action.get("action")
    if not op:
        raise ValueError("No transformation action specified")

    df = df.copy()
    logger.info("Executing declarative transform: %s", op)

    if op == "remove_duplicates":
        return df.drop_duplicates(ignore_index=True)

    elif op == "drop_nulls":
        columns = action.get("columns")
        if columns:
            missing = [c for c in columns if c not in df.columns]
            if missing:
                raise ValueError(f"Columns do not exist: {missing}")
            return df.dropna(subset=columns).reset_index(drop=True)
        return df.dropna().reset_index(drop=True)

    elif op == "fill_nulls":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        strategy = action.get("strategy", "constant")
        val = action.get("fill_value")

        if strategy == "mean":
            val = df[col].mean()
        elif strategy == "median":
            val = df[col].median()
        elif strategy == "mode":
            modes = df[col].mode()
            val = modes.iloc[0] if len(modes) > 0 else None
        
        # Guard against NaN/None issues
        df[col] = df[col].fillna(val)
        return df

    elif op == "normalize_text":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        strategy = action.get("strategy", "strip")

        if strategy == "lower":
            df[col] = df[col].astype(str).str.lower()
        elif strategy == "upper":
            df[col] = df[col].astype(str).str.upper()
        elif strategy == "title":
            df[col] = df[col].astype(str).str.title()
        elif strategy == "strip":
            df[col] = df[col].astype(str).str.strip()
        return df

    elif op == "convert_type":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        target = action.get("target_type")

        if target == "int":
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        elif target == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        elif target == "str":
            df[col] = df[col].astype(str)
        elif target == "datetime":
            df[col] = pd.to_datetime(df[col], errors="coerce")
        else:
            raise ValueError(f"Unsupported target type: '{target}'")
        return df

    elif op == "filter_rows":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        operator = action.get("operator")
        val = action.get("value")

        if operator == "==":
            df = df[df[col] == val]
        elif operator == "!=":
            df = df[df[col] != val]
        elif operator == ">":
            df = df[df[col] > val]
        elif operator == "<":
            df = df[df[col] < val]
        elif operator == ">=":
            df = df[df[col] >= val]
        elif operator == "<=":
            df = df[df[col] <= val]
        elif operator == "contains":
            df = df[df[col].astype(str).str.contains(str(val), case=False, na=False)]
        else:
            raise ValueError(f"Unsupported filter operator: '{operator}'")
        return df.reset_index(drop=True)

    elif op == "group_aggregate":
        group_by = action.get("group_by", [])
        aggs_list = action.get("aggregations", [])
        if not group_by:
            raise ValueError("Group by column list cannot be empty")
        if not aggs_list:
            raise ValueError("Aggregations list cannot be empty")

        agg_dict = {}
        for item in aggs_list:
            c = item.get("column")
            f = item.get("func", "sum")
            if c not in df.columns:
                raise ValueError(f"Aggregation column '{c}' does not exist")
            if c not in agg_dict:
                agg_dict[c] = []
            agg_dict[c].append(f)

        grouped = df.groupby(group_by).agg(agg_dict)
        # Flatten multi-index column headers
        grouped.columns = [f"{col}_{func}" for col, func in grouped.columns]
        return grouped.reset_index()

    elif op == "merge_columns":
        cols = action.get("columns", [])
        target = action.get("target_column")
        if not target:
            raise ValueError("Target column name must be provided")
        sep = action.get("separator", " ")
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"Columns do not exist: {missing}")

        df[target] = df[cols].astype(str).agg(sep.join, axis=1)
        return df

    elif op == "split_column":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        targets = action.get("target_columns", [])
        if not targets:
            raise ValueError("Target column list cannot be empty")
        delim = action.get("delimiter", " ")

        split_df = df[col].astype(str).str.split(delim, n=len(targets) - 1, expand=True)
        for idx, target in enumerate(targets):
            df[target] = split_df[idx] if idx in split_df.columns else None
        return df

    elif op == "rename_column":
        col = action.get("column")
        new_name = action.get("new_name")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        if not new_name:
            raise ValueError("New column name cannot be empty")
        return df.rename(columns={col: new_name})

    elif op == "drop_column":
        col = action.get("column")
        if col not in df.columns:
            raise ValueError(f"Column '{col}' does not exist")
        return df.drop(columns=[col])

    else:
        raise ValueError(f"Unsupported transformation action: '{op}'")


TRANSFORM_SYSTEM = """You are a data engineering assistant. Map the user's natural language command into a list of structured declarative transformation actions to apply to the dataset.

Allowed Actions:
1. {"action": "remove_duplicates"}
2. {"action": "drop_nulls", "columns": ["col1", "col2"]}
3. {"action": "fill_nulls", "column": "colName", "strategy": "mean|median|mode|constant", "fill_value": anyValue}
4. {"action": "normalize_text", "column": "colName", "strategy": "lower|upper|title|strip"}
5. {"action": "convert_type", "column": "colName", "target_type": "int|float|str|datetime"}
6. {"action": "filter_rows", "column": "colName", "operator": "==|!=|>|<|>=|<=|contains", "value": anyValue}
7. {"action": "group_aggregate", "group_by": ["col1"], "aggregations": [{"column": "col2", "func": "sum|mean|count|min|max"}]}
8. {"action": "merge_columns", "columns": ["col1", "col2"], "target_column": "newName", "separator": "delim"}
9. {"action": "split_column", "column": "colName", "target_columns": ["col1", "col2"], "delimiter": "delim"}
10. {"action": "rename_column", "column": "colName", "new_name": "newName"}
11. {"action": "drop_column", "column": "colName"}

Rules:
1. Output ONLY a valid JSON array of action objects. No explanation, no markdown.
2. Only generate actions for columns that exist in the active schema.
3. Keep descriptions simple and business-oriented.
"""


async def propose_transformations(query: str, df: pd.DataFrame, table_name: str = "data") -> list[dict]:
    """Propose one or more declarative transformations based on natural language query, using LLM or rule fallbacks."""
    query_lower = query.lower()
    proposed = []

    # 1. Run local zero-fail rule-based heuristic checks first
    if "duplicate" in query_lower or "dup" in query_lower:
        dup_count = int(df.duplicated().sum())
        proposed.append({
            "action": "remove_duplicates",
            "description": f"Remove {dup_count} duplicate row(s) from the dataset." if dup_count > 0 else "Scan and drop duplicate rows.",
            "severity": "info"
        })

    if "fill" in query_lower or "null" in query_lower or "missing" in query_lower or "impute" in query_lower:
        null_counts = df.isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                dtype = str(df[col].dtype)
                strategy = "median" if ("float" in dtype or "int" in dtype) else "mode"
                proposed.append({
                    "action": "fill_nulls",
                    "column": col,
                    "strategy": strategy,
                    "description": f"Impute {count} missing values in '{col}' with column {strategy}.",
                    "severity": "warning"
                })

    if "normalize" in query_lower or "text" in query_lower or "strip" in query_lower or "case" in query_lower:
        for col in df.select_dtypes(include="object").columns:
            proposed.append({
                "action": "normalize_text",
                "column": col,
                "strategy": "strip",
                "description": f"Normalize and trim leading/trailing whitespace in text column '{col}'.",
                "severity": "info"
            })

    if "date" in query_lower or "time" in query_lower:
        date_indicators = {"date", "time", "created", "updated", "timestamp", "dt"}
        for col in df.columns:
            if any(ind in str(col).lower() for ind in date_indicators) and not pd.api.types.is_datetime64_any_dtype(df[col].dtype):
                proposed.append({
                    "action": "convert_type",
                    "column": col,
                    "target_type": "datetime",
                    "description": f"Standardize timeline string column '{col}' into datetime64 format.",
                    "severity": "info"
                })

    if "clean" in query_lower or "fix" in query_lower or "standard" in query_lower:
        # General cleaning proposal
        dup_count = int(df.duplicated().sum())
        if dup_count > 0:
            proposed.append({
                "action": "remove_duplicates",
                "description": f"Remove {dup_count} duplicate row(s) to normalize the dataset.",
                "severity": "info"
            })
        null_counts = df.isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                dtype = str(df[col].dtype)
                strategy = "median" if ("float" in dtype or "int" in dtype) else "mode"
                proposed.append({
                    "action": "fill_nulls",
                    "column": col,
                    "strategy": strategy,
                    "description": f"Fill {count} blank cells in '{col}' with column {strategy}.",
                    "severity": "warning"
                })

    # If we found heuristic steps, we can return them directly or check if LLM can do advanced planning
    from core.llm_client import get_llm_client
    llm = get_llm_client()
    if not await llm.is_online():
        logger.info("LLM is offline. Returning local heuristic cleaning plans.")
        # If no heuristics matched but query is non-empty, provide default duplicate scanner
        if not proposed:
            proposed.append({
                "action": "remove_duplicates",
                "description": "Standard data clean: Scan and remove duplicate rows.",
                "severity": "info"
            })
        return proposed

    # Prepare schema details for advanced LLM mapping
    columns_info = ", ".join(f'"{col}" ({dtype})' for col, dtype in zip(df.columns, df.dtypes))
    import json
    sample_data = df.head(2).to_dict(orient="records")

    prompt = (
        f"Table Name: {table_name}\n"
        f"Active Columns: {columns_info}\n"
        f"Sample Records: {json.dumps(sample_data)}\n"
        f"User Query: {query}\n\n"
        "Generate a JSON array of transformation steps to accomplish the user command. Output ONLY the JSON array."
    )

    try:
        import re
        import json
        raw = await llm.generate(prompt, system=TRANSFORM_SYSTEM, json_mode=True)
        clean = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        parsed = json.loads(clean)
        if isinstance(parsed, list) and len(parsed) > 0:
            # Validate each item has action and build simple descriptions
            validated = []
            for item in parsed:
                action_name = item.get("action")
                if action_name:
                    # Seeding business description if not generated
                    desc = item.get("description")
                    if not desc:
                        col = item.get("column", "")
                        desc = f"Execute '{action_name}' transformation step on dataset"
                        if col:
                            desc += f" targeting '{col}'"
                    
                    validated.append({
                        "action": action_name,
                        "column": item.get("column"),
                        "columns": item.get("columns"),
                        "strategy": item.get("strategy"),
                        "fill_value": item.get("fill_value"),
                        "target_type": item.get("target_type"),
                        "operator": item.get("operator"),
                        "value": item.get("value"),
                        "group_by": item.get("group_by"),
                        "aggregations": item.get("aggregations"),
                        "target_column": item.get("target_column"),
                        "target_columns": item.get("target_columns"),
                        "separator": item.get("separator"),
                        "delimiter": item.get("delimiter"),
                        "new_name": item.get("new_name"),
                        "description": desc,
                        "severity": "info"
                    })
            if validated:
                logger.info("Successfully generated AI workflow transformation plan.")
                return validated
    except Exception as e:
        logger.warning(f"AI workflow planning failed: {e}. Falling back to rule-based heuristics.")

    if not proposed:
        proposed.append({
            "action": "remove_duplicates",
            "description": "Scan and remove exact duplicate rows from the dataset.",
            "severity": "info"
        })
    return proposed
