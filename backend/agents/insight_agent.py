"""
insight_agent.py — NL → sandboxed DuckDB SQL → formatted, data-grounded results.

* SQL runs in a fresh, locked-down DuckDB connection that contains only the
  caller's dataset (see core.data_store).
* Results are JSON-safe, capped at ``QUERY_MAX_RESULT_ROWS`` and flagged when
  truncated.
* The answer cache is keyed by dataset *version*, so any edit/transform/sheet
  switch automatically invalidates previous answers.
"""

import copy
import difflib
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict

from agents.base_agent import AgentResponse, BaseAgent
from core.data_store import QueryTimeoutError, UnsafeQueryError
from core.error_intelligence import diagnose_empty_result, diagnose_sql_error, format_for_user
from core.jsonsafe import to_jsonable

logger = logging.getLogger("datapilot.agent.insight")
_AS_SPLIT = re.compile(r"\bAS\b", re.IGNORECASE)

CACHE_TTL = 300
CACHE_MAX_ENTRIES = 512
_query_cache: "OrderedDict[str, tuple[dict, float]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        item = _query_cache.get(key)
        if not item:
            return None
        payload, ts = item
        if time.time() - ts > CACHE_TTL:
            _query_cache.pop(key, None)
            return None
        _query_cache.move_to_end(key)
        return copy.deepcopy(payload)


def _cache_put(key: str, payload: dict) -> None:
    with _cache_lock:
        _query_cache[key] = (copy.deepcopy(payload), time.time())
        while len(_query_cache) > CACHE_MAX_ENTRIES:
            _query_cache.popitem(last=False)


def _cache_key(query: str, dataset_id: str, version: int, provider: str) -> str:
    return hashlib.sha256(f"{dataset_id}:{version}:{provider}:{query.strip().lower()}".encode()).hexdigest()


def _build_sql_explain(sql: str, explanation: str, row_count: int, table_name: str, filename: str = "N/A",
                       sheet: str = "N/A", truncated: bool = False) -> dict:
    """Parse SQL into a structured explain block for the frontend ExplainPanel."""
    sections = []
    if explanation:
        sections.append({"label": "Query Intent", "icon": "🎯", "content": explanation})

    select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
    if select_match:
        fields, depth, current = [], 0, []
        for ch in select_match.group(1).strip():
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                fields.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            fields.append("".join(current).strip())
        lines = []
        for f in fields:
            alias_match = re.search(r"\bAS\b\s+(\S+)$", f, re.IGNORECASE)
            alias = alias_match.group(1).strip('"') if alias_match else None
            agg_match = re.match(r"(COUNT|SUM|AVG|MIN|MAX|ROUND)\s*\(", f, re.IGNORECASE)
            if agg_match:
                lines.append(f"→ {agg_match.group(1).upper()}({alias or '?'}) — aggregation")
            elif alias:
                expr = _AS_SPLIT.split(f)[0].strip()
                lines.append(f"→ {expr} as {alias}")
            else:
                lines.append(f"→ {f}")
        sections.append({"label": "Fields Selected", "icon": "📋", "content": lines})

    from_match = re.search(r"FROM\s+(\S+)", sql, re.IGNORECASE)
    if from_match:
        sections.append({"label": "Data Source", "icon": "🗄️", "content": f"Scanning table `{from_match.group(1)}`"})
    where_match = re.search(r"WHERE\s+(.+?)(?:GROUP\s+BY|ORDER\s+BY|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
    if where_match:
        sections.append({"label": "Row Filters", "icon": "🔍", "content": where_match.group(1).strip()})
    group_match = re.search(r"GROUP\s+BY\s+(.+?)(?:ORDER\s+BY|LIMIT|HAVING|$)", sql, re.IGNORECASE | re.DOTALL)
    if group_match:
        sections.append({"label": "Grouping", "icon": "📦", "content": f"Results grouped by: {group_match.group(1).strip()}"})
    order_match = re.search(r"ORDER\s+BY\s+(.+?)(?:LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
    if order_match:
        sections.append({"label": "Sorting", "icon": "⬇️", "content": f"Ordered by: {order_match.group(1).strip()}"})
    limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    if limit_match:
        sections.append({"label": "Row Limit", "icon": "✂️", "content": f"Query limited to {limit_match.group(1)} rows"})
    result_text = f"{row_count} row{'s' if row_count != 1 else ''} returned from `{table_name}`"
    if truncated:
        result_text += " (display capped — export for the full result)"
    sections.append({"label": "Execution Result", "icon": "✅", "content": result_text})

    col_refs = re.findall(r'"?([a-zA-Z_][a-zA-Z0-9_]*)"?', sql)
    sql_keywords = {"SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT", "AS", "AND", "OR", "NOT", "NULL",
                    "IS", "IN", "LIKE", "BETWEEN", "DESC", "ASC", "COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND",
                    "DISTINCT", "TRUE", "FALSE"}
    user_cols = sorted({c for c in col_refs if c.upper() not in sql_keywords and not c.isdigit()})
    if user_cols:
        sections.append({"label": "Columns Referenced", "icon": "🏷️", "content": user_cols})

    calcs = [f"SQL returned row count: {row_count}"]
    if group_match:
        calcs.append(f"Grouping keys: {group_match.group(1).strip()}")
    if order_match:
        calcs.append(f"Sorting keys: {order_match.group(1).strip()}")

    return {
        "type": "sql",
        "sql": sql,
        "sections": sections,
        "data_source": filename,
        "sheet": sheet,
        "columns": user_cols,
        "filters": where_match.group(1).strip() if where_match else "None",
        "intermediate_calculations": calcs,
        "confidence_score": None,
        "verification": "Computed by executing SQL on your data",
        "reasoning_summary": explanation or "SQL statement executed on the dataset.",
    }


SQL_SYSTEM = """You are a SQL expert. Generate a single DuckDB SQL SELECT query for the user's question.

Rules:
1. Return ONLY valid JSON: {"sql": "<sql_query>", "explanation": "<one sentence>"}
2. Use the table name provided exactly as given; it is the ONLY table available
3. Use LIMIT 100 unless the user asks for all rows
4. Use double quotes for column names: "My Column"
5. For aggregations, use GROUP BY and ORDER BY DESC
6. Only a single read-only SELECT statement (WITH ... SELECT allowed)
7. If a column doesn't exist, pick the closest matching one

Few-shot examples:
Q: top 5 products by revenue | table: file_abc123
A: {"sql": "SELECT \\"product\\", SUM(\\"revenue\\") AS total_revenue FROM file_abc123 GROUP BY 1 ORDER BY total_revenue DESC LIMIT 5", "explanation": "Groups by product and sums revenue, ordered by highest total"}

Q: average salary by department | table: file_xyz789
A: {"sql": "SELECT \\"department\\", ROUND(AVG(\\"salary\\"), 2) AS avg_salary FROM file_xyz789 GROUP BY 1 ORDER BY avg_salary DESC LIMIT 100", "explanation": "Averages salary per department"}
"""


def _extract_sql(raw: str) -> tuple[str, str]:
    clean = re.sub(r"```(?:json|sql)?\s*", "", raw or "").replace("```", "").strip()
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            return str(parsed.get("sql", "")).strip(), str(parsed.get("explanation", ""))
    except (json.JSONDecodeError, AttributeError):
        pass
    json_match = re.search(r'\{[^{}]*"sql"\s*:\s*"((?:[^"\\]|\\.)+)"[^{}]*\}', clean, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            return str(parsed.get("sql", "")).strip(), str(parsed.get("explanation", ""))
        except Exception:
            return json_match.group(1).strip(), ""
    sel_match = re.search(r"((?:WITH|SELECT)\s+.+)", clean, re.IGNORECASE | re.DOTALL)
    return (sel_match.group(1).strip().rstrip(";"), "") if sel_match else ("", "")


class InsightAgent(BaseAgent):
    agent_type = "insight"

    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        file_id, record = await self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response("No file loaded. Please upload a CSV or Excel file first.", "insight")

        table_name = record.table_name
        df = record.df
        provider = getattr(getattr(self.llm, "settings", None), "provider", "llm")
        key = _cache_key(query, record.file_id, record.version, provider)
        cached = _cache_get(key)
        if cached is not None:
            cached["metadata"]["cached"] = True
            return AgentResponse(**cached)

        columns_info = ", ".join(f'"{col}" ({dtype})' for col, dtype in zip(df.columns, df.dtypes))
        sample = json.dumps(to_jsonable(df.head(2).to_dict(orient="records")))[:4000]
        prompt = f"Table: {table_name}\nColumns: {columns_info}\nSample values: {sample}\nQuestion: {query}"

        raw = await self.llm.generate(prompt, system=SQL_SYSTEM, json_mode=True)
        sql, explanation = _extract_sql(raw)
        if not sql:
            logger.warning("Could not extract SQL from model output")
            return AgentResponse.error_response(f"Could not generate a valid SQL query for: '{query}'", "insight")

        tables = {table_name: df}
        auto_recovery = None
        try:
            result = await self.cpu(self.store.execute, sql, tables)
        except UnsafeQueryError as exc:
            return AgentResponse.error_response(
                f"The generated query was rejected for safety reasons ({exc}). Try rephrasing the question.", "insight"
            )
        except QueryTimeoutError as exc:
            return AgentResponse.error_response(f"{exc} Try a narrower question.", "insight")
        except Exception as e:
            intelligent_err = diagnose_sql_error(e, sql, df, file_record=record)
            result = None
            if intelligent_err.get("code") == "COLUMN_NOT_FOUND":
                bad_col = intelligent_err.get("affected_column") or ""
                close = difflib.get_close_matches(bad_col, [str(c) for c in df.columns], n=1, cutoff=0.6)
                if close:
                    suggested = close[0]
                    fixed_sql = re.sub(r'"?\b' + re.escape(bad_col) + r'\b"?', f'"{suggested}"', sql, flags=re.IGNORECASE)
                    try:
                        result = await self.cpu(self.store.execute, fixed_sql, tables)
                        auto_recovery = f"Column '{bad_col}' was not found; '{suggested}' was used instead."
                        sql = fixed_sql
                    except Exception:
                        result = None
            if result is None:
                return AgentResponse.error_response(format_for_user(intelligent_err), "insight", intelligent_error=intelligent_err)

        row_count = len(result.rows)
        if row_count == 0:
            empty_err = diagnose_empty_result(sql, df, query)
            return AgentResponse.error_response(format_for_user(empty_err), "insight", intelligent_error=empty_err)

        content_lines = []
        if auto_recovery:
            content_lines.append(f"⚠️ **Note:** {auto_recovery}\n")
        content_lines.append(f"**Query:** `{sql}`\n")
        if explanation:
            content_lines.append(f"*{explanation}*\n")
        if result.truncated:
            content_lines.append(f"**Showing the first {row_count:,} rows** — use Export to download the full result.")
        else:
            content_lines.append(f"**{row_count} row(s) returned.**")

        sheet = record.metadata.get("active_sheet") or "Sheet1"
        explain = _build_sql_explain(sql, explanation, row_count, table_name, record.filename, sheet, result.truncated)
        metadata = {
            "sql": sql,
            "explanation": explanation,
            "row_count": row_count,
            "truncated": result.truncated,
            "row_limit": result.row_limit,
            "table_name": table_name,
            "dataset_version": record.version,
            "cached": False,
            "explain": explain,
        }
        if auto_recovery:
            metadata["auto_recovered"] = True
            metadata["recovery_message"] = auto_recovery

        payload = {"type": "insight", "content": "\n".join(content_lines), "table_data": result.rows, "metadata": metadata}
        _cache_put(key, payload)
        return AgentResponse(**payload)
