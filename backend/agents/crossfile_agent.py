"""
crossfile_agent.py — Multi-file joins and cross-dataset queries.
Uses DuckDB SQL for fast in-memory joins.
"""

import json
import logging

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.crossfile")

CROSSFILE_SYSTEM = """You are a SQL expert specializing in joining multiple tables.
Given two or more tables with their column schemas, write a DuckDB SQL query to answer the user's question.

Rules:
1. Return ONLY valid JSON: {"sql": "<query>", "explanation": "<one sentence>"}
2. Use proper JOIN syntax (INNER, LEFT, etc.)
3. Match columns by semantic similarity (e.g., "customer_id" joins to "cust_id")
4. Always use table aliases
5. LIMIT 100 unless asked for more
6. Only SELECT queries"""


class CrossFileAgent(BaseAgent):
    agent_type = "crossfile"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        if len(file_ids) < 2:
            return AgentResponse.error_response(
                "Cross-file analysis requires at least 2 uploaded files. "
                "Upload another file and try again.",
                "crossfile",
            )

        # Gather schemas for all loaded files
        tables_info = []
        for fid in file_ids:
            record = self.files.get_record(fid)
            if record is None:
                continue
            schema = self.store.get_schema(record.table_name)
            tables_info.append(
                {
                    "table": record.table_name,
                    "filename": record.filename,
                    "columns": schema,
                    "sample": record.df.head(2).to_dict(orient="records"),
                }
            )

        if len(tables_info) < 2:
            return AgentResponse.error_response(
                "Could not find at least 2 loaded files in memory.", "crossfile"
            )

        schema_text = ""
        for t in tables_info:
            cols = ", ".join(f"{c['column']} ({c['type']})" for c in t["columns"])
            schema_text += f"Table: {t['table']} (file: {t['filename']})\nColumns: {cols}\n\n"

        prompt = f"User query: {query}\n\nAvailable tables:\n{schema_text}"
        raw = await self.llm.generate(prompt, system=CROSSFILE_SYSTEM, json_mode=True)

        try:
            parsed = json.loads(raw)
            sql = parsed.get("sql", "").strip()
            explanation = parsed.get("explanation", "")
        except (json.JSONDecodeError, AttributeError):
            sql = raw.strip()
            explanation = ""

        if not sql or not sql.upper().startswith("SELECT"):
            return AgentResponse.error_response(
                f"Could not generate a valid JOIN query for: '{query}'", "crossfile"
            )

        try:
            results = self.store.execute(sql)
        except Exception as e:
            return AgentResponse.error_response(
                f"Join query failed: {e}\nSQL: `{sql}`", "crossfile"
            )

        content = (
            f"🔗 **Cross-file analysis** ({len(tables_info)} files joined)\n\n"
            f"**SQL:** `{sql}`\n"
        )
        if explanation:
            content += f"\n*{explanation}*\n"
        content += f"\n**{len(results)} row(s) returned.**"

        return AgentResponse(
            type="crossfile",
            content=content,
            table_data=results,
            metadata={"sql": sql, "tables": [t["table"] for t in tables_info]},
        )
