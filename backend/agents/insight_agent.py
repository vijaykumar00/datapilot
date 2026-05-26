"""
insight_agent.py — NL → DuckDB SQL → formatted results.
Uses few-shot prompting for reliable SQL generation.
"""

import hashlib
import json
import logging
import time

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.insight")

# Simple 5-minute query cache: {hash: (result, timestamp)}
_query_cache: dict[str, tuple[AgentResponse, float]] = {}
CACHE_TTL = 300  # 5 minutes

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
        try:
            parsed = json.loads(raw)
            sql = parsed.get("sql", "").strip()
            explanation = parsed.get("explanation", "")
        except (json.JSONDecodeError, AttributeError):
            # Fallback: try to extract raw SQL if JSON parsing fails
            sql = raw.strip()
            explanation = ""

        if not sql or not sql.upper().startswith("SELECT"):
            return AgentResponse.error_response(
                f"Could not generate a valid SQL query for: '{query}'", "insight"
            )

        # Execute
        try:
            results = self.store.execute(sql)
        except Exception as e:
            return AgentResponse.error_response(
                f"SQL execution failed: {e}\nGenerated SQL: `{sql}`", "insight"
            )

        # Format response
        row_count = len(results)
        content_lines = [f"**Query:** `{sql}`\n"]
        if explanation:
            content_lines.append(f"*{explanation}*\n")
        content_lines.append(f"**{row_count} row(s) returned.**")

        response = AgentResponse(
            type="insight",
            content="\n".join(content_lines),
            table_data=results,
            metadata={
                "sql": sql,
                "row_count": row_count,
                "table_name": table_name,
                "cached": False,
            },
        )

        # Cache it
        _query_cache[key] = (response, now)
        # Evict old entries
        expired = [k for k, (_, ts) in _query_cache.items() if now - ts > CACHE_TTL]
        for k in expired:
            del _query_cache[k]

        return response
