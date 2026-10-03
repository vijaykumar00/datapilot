"""
data_store.py — Sandboxed, per-request DuckDB query execution.

Security model (fixes the shared-connection / unchecked-SQL issue):

* Every query runs on a brand-new in-memory DuckDB connection that contains
  ONLY the DataFrames the caller is authorised to read (resolved from the
  caller's workspace before execution).  Other tenants' tables simply do not
  exist inside the connection, so cross-tenant access is impossible even if
  the SQL check below were bypassed.
* External access (file system, HTTP, extensions) is disabled and the
  configuration is locked, so ``read_csv``/``glob``/``COPY``/``ATTACH`` and
  replacement scans of server files cannot work.
* The SQL text must parse to exactly ONE statement of type SELECT
  (``WITH … SELECT`` included).  Multi-statement payloads are rejected.
* Execution is bounded by a wall-clock timeout (``con.interrupt()``), a memory
  limit and a maximum number of returned rows.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

import duckdb
import pandas as pd

from core.jsonsafe import to_jsonable

logger = logging.getLogger("datapilot.data_store")


class UnsafeQueryError(ValueError):
    """Raised when SQL is rejected by the sandbox policy."""


class QueryTimeoutError(RuntimeError):
    """Raised when a query exceeds the configured timeout."""


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def max_result_rows() -> int:
    return _int_env("QUERY_MAX_RESULT_ROWS", 1000)


def query_timeout_seconds() -> int:
    return _int_env("QUERY_TIMEOUT_SECONDS", 20)


_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,120}$")


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool = False
    row_limit: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:  # convenience for existing callers
        return len(self.rows)


def _sandbox_config() -> dict[str, Any]:
    return {
        "enable_external_access": False,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "threads": _int_env("QUERY_THREADS", 2),
        "memory_limit": os.getenv("QUERY_MEMORY_LIMIT", "512MB"),
    }


def validate_select_sql(sql: str) -> str:
    """Return normalised SQL if it is a single SELECT statement, else raise."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty SQL query.")
    cleaned = sql.strip().rstrip(";").strip()
    parser = duckdb.connect(":memory:", config=_sandbox_config())
    try:
        try:
            statements = parser.extract_statements(cleaned)
        except duckdb.Error as exc:
            raise UnsafeQueryError(f"SQL could not be parsed: {exc}") from exc
    finally:
        parser.close()
    if len(statements) != 1:
        raise UnsafeQueryError("Only a single SELECT statement is allowed.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeQueryError("Only read-only SELECT queries are allowed.")
    # PRAGMA/SHOW/DESCRIBE/CALL parse as SELECT internally; only accept real queries.
    first = re.sub(r"^(\s|\(|--[^\n]*\n|/\*.*?\*/)+", "", cleaned, flags=re.DOTALL).split(None, 1)
    if not first or first[0].upper() not in {"SELECT", "WITH", "FROM", "VALUES"}:
        raise UnsafeQueryError("Only read-only SELECT queries are allowed.")
    return cleaned


def _sandboxed_connection(tables: Mapping[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config=_sandbox_config())
    try:
        try:
            con.execute("SET python_enable_replacements=false")
        except duckdb.Error:  # option missing in some builds; only registered views exist anyway
            pass
        for name, df in tables.items():
            if not _TABLE_NAME_RE.match(name):
                raise UnsafeQueryError(f"Invalid table name '{name}'.")
            con.register(name, df)
        con.execute("SET lock_configuration=true")
    except Exception:
        con.close()
        raise
    return con


def _run_with_timeout(con, timeout: int, fn):
    timed_out = threading.Event()

    def _interrupt() -> None:
        timed_out.set()
        try:
            con.interrupt()
        except Exception:
            pass

    timer = threading.Timer(timeout, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        return fn()
    except duckdb.InterruptException as exc:
        raise QueryTimeoutError(f"Query exceeded the {timeout}s time limit.") from exc
    except duckdb.Error:
        if timed_out.is_set():
            raise QueryTimeoutError(f"Query exceeded the {timeout}s time limit.")
        raise
    finally:
        timer.cancel()


def execute_select(
    sql: str,
    tables: Mapping[str, pd.DataFrame],
    *,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
) -> QueryResult:
    """Run one validated SELECT against ONLY ``tables`` and return JSON-safe rows."""
    safe_sql = validate_select_sql(sql)
    limit = max_rows or max_result_rows()
    timeout = timeout_seconds or query_timeout_seconds()

    con = _sandboxed_connection(tables)
    try:
        def _go():
            cursor = con.execute(safe_sql)
            cols = [d[0] for d in (cursor.description or [])]
            return cols, cursor.fetchmany(limit + 1)

        columns, raw_rows = _run_with_timeout(con, timeout, _go)
    finally:
        con.close()

    truncated = len(raw_rows) > limit
    raw_rows = raw_rows[:limit]
    rows = [to_jsonable(dict(zip(columns, row))) for row in raw_rows]
    return QueryResult(columns=columns, rows=rows, truncated=truncated, row_limit=limit)


def execute_select_df(
    sql: str,
    tables: Mapping[str, pd.DataFrame],
    *,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
) -> pd.DataFrame:
    """Same sandbox as :func:`execute_select` but returns a DataFrame (full exports)."""
    safe_sql = validate_select_sql(sql)
    limit = max_rows or _int_env("EXPORT_MAX_ROWS", 1_000_000)
    timeout = timeout_seconds or _int_env("EXPORT_QUERY_TIMEOUT_SECONDS", 120)
    con = _sandboxed_connection(tables)
    try:
        return _run_with_timeout(
            con,
            timeout,
            lambda: con.execute(f"SELECT * FROM ({safe_sql}) AS _dp_export LIMIT {int(limit)}").df(),
        )
    finally:
        con.close()


def describe_dataframe(df: pd.DataFrame) -> list[dict[str, str]]:
    """Column names and DuckDB types for prompting (no shared state)."""
    con = _sandboxed_connection({"_dp_describe": df.head(0)})
    try:
        rows = con.execute("DESCRIBE _dp_describe").fetchall()
        return [{"column": r[0], "type": r[1]} for r in rows]
    finally:
        con.close()


class QueryEngine:
    """Stateless engine handed to agents; holds no tenant data."""

    def execute(
        self,
        sql: str,
        tables: Mapping[str, pd.DataFrame],
        *,
        max_rows: int | None = None,
    ) -> QueryResult:
        return execute_select(sql, tables, max_rows=max_rows)

    def get_schema_for(self, df: pd.DataFrame) -> list[dict[str, str]]:
        return describe_dataframe(df)


_engine = QueryEngine()


def get_store() -> QueryEngine:
    """Backwards-compatible accessor; the engine holds no tenant state."""
    return _engine
