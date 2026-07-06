"""
insight_agent.py — NL → DuckDB SQL → formatted results.
Uses few-shot prompting for reliable SQL generation.
"""

import hashlib
import json
import logging
import re
import time

from agents.base_agent import AgentResponse, BaseAgent
from core.error_intelligence import diagnose_sql_error, diagnose_empty_result, format_for_user

logger = logging.getLogger("datapilot.agent.insight")

# Simple 5-minute query cache: {hash: (result, timestamp)}
_query_cache: dict[str, tuple[AgentResponse, float]] = {}
CACHE_TTL = 300  # 5 minutes


def _build_sql_explain(
    sql: str,
    explanation: str,
    row_count: int,
    table_name: str,
    filename: str = "N/A",
    sheet: str = "N/A"
) -> dict:
    """Parse SQL into a structured explain block for the frontend ExplainPanel."""
    sql_upper = sql.upper()
    sections = []

    # 1. Query Intent
    if explanation:
        sections.append({
            "label": "Query Intent",
            "icon": "🎯",
            "content": explanation
        })

    # 2. SELECT clause — extract column/expression list
    select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
    if select_match:
        fields_raw = select_match.group(1).strip()
        # Split on top-level commas (not inside parens)
        fields = []
        depth = 0
        current = []
        for ch in fields_raw:
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

        field_lines = []
        for f in fields:
            f = f.strip()
            alias_match = re.search(r"\bAS\b\s+(\S+)$", f, re.IGNORECASE)
            alias = alias_match.group(1).strip('"') if alias_match else None
            agg_match = re.match(r"(COUNT|SUM|AVG|MIN|MAX|ROUND)\s*\(", f, re.IGNORECASE)
            if agg_match:
                agg = agg_match.group(1).upper()
                label = f"→ {agg}({alias or '?'}) — aggregation"
            elif alias:
                label = f"→ {f.split('AS')[0].strip()} as {alias}"
            else:
                label = f"→ {f}"
            field_lines.append(label)

        sections.append({
            "label": "Fields Selected",
            "icon": "📋",
            "content": field_lines
        })

    # 3. FROM clause
    from_match = re.search(r"FROM\s+(\S+)", sql, re.IGNORECASE)
    if from_match:
        sections.append({
            "label": "Data Source",
            "icon": "🗄️",
            "content": f"Scanning table `{from_match.group(1)}`"
        })

    # 4. WHERE clause
    where_match = re.search(r"WHERE\s+(.+?)(?:GROUP\s+BY|ORDER\s+BY|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
    if where_match:
        sections.append({
            "label": "Row Filters",
            "icon": "🔍",
            "content": where_match.group(1).strip()
        })

    # 5. GROUP BY clause
    group_match = re.search(r"GROUP\s+BY\s+(.+?)(?:ORDER\s+BY|LIMIT|HAVING|$)", sql, re.IGNORECASE | re.DOTALL)
    if group_match:
        sections.append({
            "label": "Grouping",
            "icon": "📦",
            "content": f"Results grouped by: {group_match.group(1).strip()}"
        })

    # 6. ORDER BY clause
    order_match = re.search(r"ORDER\s+BY\s+(.+?)(?:LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
    if order_match:
        sections.append({
            "label": "Sorting",
            "icon": "⬇️",
            "content": f"Ordered by: {order_match.group(1).strip()}"
        })

    # 7. LIMIT clause
    limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    if limit_match:
        sections.append({
            "label": "Row Limit",
            "icon": "✂️",
            "content": f"Capped at {limit_match.group(1)} rows for safety"
        })

    # 8. Execution result
    sections.append({
        "label": "Execution Result",
        "icon": "✅",
        "content": f"{row_count} row{'s' if row_count != 1 else ''} returned from `{table_name}`"
    })

    # 9. Column usage
    col_refs = re.findall(r'"?([a-zA-Z_][a-zA-Z0-9_]*)"?', sql)
    sql_keywords = {"SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT", "AS",
                    "AND", "OR", "NOT", "NULL", "IS", "IN", "LIKE", "BETWEEN", "DESC",
                    "ASC", "COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "DISTINCT", "TRUE", "FALSE"}
    user_cols = sorted(set(c for c in col_refs if c.upper() not in sql_keywords and not c.isdigit()))
    if user_cols:
        sections.append({
            "label": "Columns Referenced",
            "icon": "🏷️",
            "content": user_cols
        })

    # Calculations
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
        "confidence_score": 0.98,
        "reasoning_summary": explanation or "SQL statement formed and successfully run on target dataset."
    }

SQL_SYSTEM = """You are a SQL expert. Generate a single DuckDB SQL SELECT query for the user's question.

Rules:
1. Return ONLY valid JSON: {"sql": "<sql_query>", "explanation": "<one sentence>"}
2. Use the table name provided exactly as given
3. Use LIMIT 100 for safety unless user asks for all rows
4. Use double quotes for column names with spaces: "My Column"
5. For aggregations, use GROUP BY and ORDER BY DESC
6. Never use DELETE, DROP, INSERT, UPDATE — only SELECT
7. If a column doesn't exist, pick the closest matching one

Few-shot examples:
Q: top 5 products by revenue | table: file_abc123
A: {"sql": "SELECT product, SUM(revenue) as total_revenue FROM file_abc123 GROUP BY product ORDER BY total_revenue DESC LIMIT 5", "explanation": "Groups by product and sums revenue, ordered by highest total"}

Q: average salary by department | table: file_xyz789
A: {"sql": "SELECT department, ROUND(AVG(salary), 2) as avg_salary FROM file_xyz789 GROUP BY department ORDER BY avg_salary DESC LIMIT 100", "explanation": "Averages salary per department"}

Q: how many rows have null values | table: file_aaa111
A: {"sql": "SELECT COUNT(*) as null_count FROM file_aaa111 WHERE TRUE AND (col1 IS NULL OR col2 IS NULL)", "explanation": "Counts rows with any null value"}
"""


def _cache_key(query: str, table_name: str) -> str:
    return hashlib.md5(f"{query}:{table_name}".encode()).hexdigest()


class InsightAgent(BaseAgent):
    agent_type = "insight"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response(
                "No file loaded. Please upload a CSV or Excel file first.",
                "insight",
            )

        table_name = record.table_name
        df = record.df

        # Check cache
        key = _cache_key(query, table_name)
        now = time.time()
        if key in _query_cache:
            cached, ts = _query_cache[key]
            if now - ts < CACHE_TTL:
                logger.info("Cache hit for insight query")
                cached.metadata["cached"] = True
                return cached

        # Build schema context for LLM
        columns_info = ", ".join(
            f'"{col}" ({dtype})' for col, dtype in zip(df.columns, df.dtypes)
        )
        prompt = (
            f"Table: {table_name}\n"
            f"Columns: {columns_info}\n"
            f"Sample values: {df.head(2).to_dict(orient='records')}\n"
            f"Question: {query}"
        )

        # Generate SQL
        raw = await self.llm.generate(prompt, system=SQL_SYSTEM, json_mode=True)

        sql = ""
        explanation = ""

        # Strip markdown code fences (Gemini/Claude often wrap output in ```json...```)
        clean = re.sub(r"```(?:json|sql)?\s*", "", raw).replace("```", "").strip()

        # Try JSON parse first
        try:
            parsed = json.loads(clean)
            sql = parsed.get("sql", "").strip()
            explanation = parsed.get("explanation", "")
        except (json.JSONDecodeError, AttributeError):
            # Try extracting JSON object with sql key from anywhere in the text
            json_match = re.search(r'\{[^{}]*"sql"\s*:\s*"([^"]+)"[^{}]*\}', clean, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    sql = parsed.get("sql", "").strip()
                    explanation = parsed.get("explanation", "")
                except Exception:
                    sql = json_match.group(1).strip()
            else:
                # Last resort: find a SELECT statement directly in the text
                sel_match = re.search(r"(SELECT\s+.+)", clean, re.IGNORECASE | re.DOTALL)
                if sel_match:
                    sql = sel_match.group(1).strip().rstrip(";")

        if not sql or not sql.upper().lstrip().startswith("SELECT"):
            logger.warning(f"Could not extract SQL. Raw LLM output: {raw[:300]}")
            return AgentResponse.error_response(
                f"Could not generate a valid SQL query for: '{query}'", "insight"
            )

        # Execute
        try:
            results = self.store.execute(sql)
        except Exception as e:
            intelligent_err = diagnose_sql_error(e, sql, df, file_record=record)
            
            # Automatic recovery:
            if intelligent_err.get("code") == "COLUMN_NOT_FOUND" and df is not None:
                bad_col = intelligent_err.get("affected_column")
                import difflib
                close = difflib.get_close_matches(bad_col, list(df.columns), n=1, cutoff=0.6)
                if close:
                    suggested = close[0]
                    # Automatically replace bad column name in SQL
                    fixed_sql = re.sub(r'\b' + re.escape(bad_col) + r'\b', suggested, sql, flags=re.IGNORECASE)
                    fixed_sql = fixed_sql.replace(f'"{bad_col}"', f'"{suggested}"').replace(f"'{bad_col}'", f"'{suggested}'")
                    try:
                        logger.info(f"Auto-recovery: retrying SQL with '{suggested}' instead of '{bad_col}'")
                        results = self.store.execute(fixed_sql)
                        row_count = len(results)
                        
                        content_lines = [
                            f"⚠️ **Note:** Column '{bad_col}' was not found. We automatically corrected it to '{suggested}' and ran the query.\n",
                            f"**Query:** `{fixed_sql}`\n"
                        ]
                        if explanation:
                            content_lines.append(f"*{explanation}*\n")
                        content_lines.append(f"**{row_count} row(s) returned.**")
                        
                        filename = record.filename if record else "N/A"
                        sheet = record.metadata.get("active_sheet") or "Sheet1"
                        
                        explain = _build_sql_explain(fixed_sql, explanation, row_count, table_name, filename, sheet)
                        
                        return AgentResponse(
                            type="insight",
                            content="\n".join(content_lines),
                            table_data=results,
                            metadata={
                                "sql": fixed_sql,
                                "explanation": explanation,
                                "row_count": row_count,
                                "table_name": table_name,
                                "cached": False,
                                "explain": explain,
                                "auto_recovered": True,
                                "recovery_message": f"Automatically replaced missing column '{bad_col}' with '{suggested}'"
                            },
                        )
                    except Exception:
                        pass
            
            return AgentResponse.error_response(
                format_for_user(intelligent_err), "insight", intelligent_error=intelligent_err
            )

        # Zero-row result — provide context-rich explanation
        row_count = len(results)
        if row_count == 0:
            empty_err = diagnose_empty_result(sql, df, query)
            return AgentResponse.error_response(
                format_for_user(empty_err), "insight", intelligent_error=empty_err
            )

        # Format response
        content_lines = [f"**Query:** `{sql}`\n"]
        if explanation:
            content_lines.append(f"*{explanation}*\n")
        content_lines.append(f"**{row_count} row(s) returned.**")

        filename = "N/A"
        sheet = "N/A"
        if record:
            filename = record.filename
            sheet = record.metadata.get("active_sheet") or "Sheet1"

        explain = _build_sql_explain(sql, explanation, row_count, table_name, filename, sheet)

        response = AgentResponse(
            type="insight",
            content="\n".join(content_lines),
            table_data=results,
            metadata={
                "sql": sql,
                "explanation": explanation,
                "row_count": row_count,
                "table_name": table_name,
                "cached": False,
                "explain": explain,
            },
        )

        # Cache it
        _query_cache[key] = (response, now)
        # Evict old entries
        expired = [k for k, (_, ts) in _query_cache.items() if now - ts > CACHE_TTL]
        for k in expired:
            del _query_cache[k]

        return response
