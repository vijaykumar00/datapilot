"""
crossfile_agent.py — Multi-file joins via sandboxed SQL.

Only the datasets the caller explicitly selected (and which belong to the
caller's workspace) are registered in the sandbox connection.
"""

import logging

from agents.base_agent import AgentResponse, BaseAgent
from agents.insight_agent import _extract_sql
from core.data_store import QueryTimeoutError, UnsafeQueryError, describe_dataframe
from core.jsonsafe import to_jsonable

logger = logging.getLogger("datapilot.agent.crossfile")

CROSSFILE_SYSTEM = """You are a SQL expert specializing in multi-table joins in DuckDB.

Rules:
1. Return ONLY JSON: {"sql": "<query>", "explanation": "<one sentence>", "join_key": "<column used to join>"}
2. Use the exact table names provided; no other tables exist
3. Use INNER JOIN unless the user wants all rows (then LEFT JOIN)
4. Prefix ambiguous columns with table name: t1.col
5. LIMIT 100 unless asked for more
6. A single read-only SELECT statement only
"""


class CrossFileAgent(BaseAgent):
    agent_type = "crossfile"

    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        if len(file_ids) < 2:
            return AgentResponse.error_response(
                "Cross-file analysis requires at least 2 uploaded files. Upload another file and try again.",
                "crossfile",
            )

        tables, tables_info = {}, []
        for fid in file_ids:
            record = await self._get_record(fid)
            if record is None:
                continue
            tables[record.table_name] = record.df
            schema = await self.cpu(describe_dataframe, record.df)
            tables_info.append({"table": record.table_name, "filename": record.filename, "columns": schema})

        if len(tables_info) < 2:
            return AgentResponse.error_response("Could not find at least 2 accessible files.", "crossfile")

        schema_text = ""
        for t in tables_info:
            cols = ", ".join(f"{c['column']} ({c['type']})" for c in t["columns"])
            schema_text += f"Table: {t['table']} (file: {t['filename']})\nColumns: {cols}\n\n"

        raw = await self.llm.generate(f"User query: {query}\n\nAvailable tables:\n{schema_text}",
                                      system=CROSSFILE_SYSTEM, json_mode=True)
        sql, explanation = _extract_sql(raw)
        if not sql:
            return AgentResponse.error_response(f"Could not generate a valid JOIN query for: '{query}'", "crossfile")

        try:
            result = await self.cpu(self.store.execute, sql, tables)
        except UnsafeQueryError as exc:
            return AgentResponse.error_response(f"The generated query was rejected for safety reasons ({exc}).", "crossfile")
        except QueryTimeoutError as exc:
            return AgentResponse.error_response(str(exc), "crossfile")
        except Exception as e:
            return AgentResponse.error_response(f"Join query failed: {e}\nSQL: `{sql}`", "crossfile")

        content = f"🔗 **Cross-file analysis** ({len(tables_info)} files joined)\n\n**SQL:** `{sql}`\n"
        if explanation:
            content += f"\n*{explanation}*\n"
        if result.truncated:
            content += f"\n**Showing the first {len(result.rows):,} rows** — export for the full result."
        else:
            content += f"\n**{len(result.rows)} row(s) returned.**"

        return AgentResponse(
            type="crossfile",
            content=content,
            table_data=result.rows,
            metadata=to_jsonable({
                "sql": sql,
                "explanation": explanation,
                "row_count": len(result.rows),
                "truncated": result.truncated,
                "tables": [t["table"] for t in tables_info],
            }),
        )
