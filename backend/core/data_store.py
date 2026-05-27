"""
data_store.py — DuckDB in-process analytics store.
Manages table registration, SQL execution, and result formatting.
"""

import logging
from typing import Any
import duckdb
import pandas as pd

logger = logging.getLogger("datapilot.data_store")


class DataStore:
    """Singleton DuckDB connection shared across agents."""

    def __init__(self):
        self.conn = duckdb.connect(database=":memory:", read_only=False)
        logger.info("DuckDB in-memory store initialized")

    def register_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        """Register a Pandas DataFrame as a DuckDB view."""
        try:
            self.conn.unregister(table_name)
        except Exception:
            pass
        self.conn.register(table_name, df)
        logger.info(f"Registered table '{table_name}' with {len(df)} rows")

    def execute(self, sql: str, params: list | None = None) -> list[dict[str, Any]]:
        """Execute SQL and return list of dicts."""
        try:
            result = self.conn.execute(sql, params or [])
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"SQL execution failed: {e}\nSQL: {sql}")
            raise

    def execute_df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Execute SQL and return a Pandas DataFrame."""
        try:
            return self.conn.execute(sql, params or []).df()
        except Exception as e:
            logger.error(f"SQL execution (df) failed: {e}\nSQL: {sql}")
            raise

    def table_exists(self, table_name: str) -> bool:
        try:
            result = self.conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchone()
            return result[0] > 0
        except Exception:
            return False

    def get_schema(self, table_name: str) -> list[dict[str, str]]:
        """Return column names and types for a registered table."""
        try:
            result = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
            return [{"column": row[0], "type": row[1]} for row in result]
        except Exception as e:
            logger.error(f"get_schema failed for '{table_name}': {e}")
            return []

    def drop_table(self, table_name: str) -> None:
        try:
            self.conn.execute(f"DROP VIEW IF EXISTS {table_name}")
            logger.info(f"Dropped view '{table_name}'")
        except Exception as e:
            logger.warning(f"Could not drop '{table_name}': {e}")

    def close(self) -> None:
        self.conn.close()


# Module-level singleton
_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store
