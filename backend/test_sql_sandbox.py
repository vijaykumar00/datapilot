"""
test_sql_sandbox.py — AI-generated SQL can only read the caller's own tables.
"""

import datetime
import decimal
import json
import os
import unittest

import numpy as np
import pandas as pd

from core import jsonsafe
from core.data_store import QueryTimeoutError, UnsafeQueryError, execute_select, execute_select_df


class TestSqlSandbox(unittest.TestCase):
    def setUp(self):
        self.mine = {"file_mine": pd.DataFrame({"region": ["N", "S"], "revenue": [10, 20]})}

    def test_select_works(self):
        res = execute_select("SELECT SUM(revenue) AS total FROM file_mine", self.mine)
        self.assertEqual(res.rows, [{"total": 30}])

    def test_other_tenant_tables_do_not_exist(self):
        # Another tenant's table is never registered in the caller's connection.
        with self.assertRaises(Exception):
            execute_select("SELECT * FROM file_theirs", self.mine)
        res = execute_select("SELECT table_name FROM information_schema.tables", self.mine)
        self.assertEqual({r["table_name"] for r in res.rows}, {"file_mine"})

    def test_multi_statement_rejected(self):
        with self.assertRaises(UnsafeQueryError):
            execute_select("SELECT 1; COPY file_mine TO '/tmp/leak.csv'", self.mine)
        self.assertFalse(os.path.exists("/tmp/leak.csv"))

    def test_non_select_rejected(self):
        for sql in ("COPY file_mine TO '/tmp/x.csv'", "ATTACH 'x.db'", "INSTALL httpfs", "PRAGMA version",
                    "CREATE TABLE t AS SELECT 1", "SET enable_external_access=true"):
            with self.assertRaises(UnsafeQueryError, msg=sql):
                execute_select(sql, self.mine)

    def test_filesystem_access_blocked(self):
        for sql in ("SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM glob('/etc/*')",
                    "SELECT * FROM '/etc/passwd'", "SELECT * FROM read_text('/etc/hostname')"):
            with self.assertRaises(Exception, msg=sql):
                execute_select(sql, self.mine)

    def test_python_replacement_scans_disabled(self):
        secret_df = pd.DataFrame({"secret": [1]})  # noqa: F841 - would be visible via replacement scan
        with self.assertRaises(Exception):
            execute_select("SELECT * FROM secret_df", self.mine)

    def test_row_cap_and_truncation_flag(self):
        big = {"file_big": pd.DataFrame({"x": range(5000)})}
        res = execute_select("SELECT * FROM file_big", big, max_rows=100)
        self.assertEqual(len(res.rows), 100)
        self.assertTrue(res.truncated)
        full = execute_select_df("SELECT * FROM file_big", big)
        self.assertEqual(len(full), 5000)

    def test_timeout(self):
        with self.assertRaises(QueryTimeoutError):
            execute_select("SELECT COUNT(*) FROM range(10000000000) a", {}, timeout_seconds=1)

    def test_dates_and_decimals_serialize(self):
        df = {"file_d": pd.DataFrame({"d": ["2024-01-05", "2024-02-07"], "v": [1, 2]})}
        res = execute_select(
            "SELECT DATE_TRUNC('month', CAST(d AS DATE)) AS m, CAST(SUM(v) AS DECIMAL(10,2)) AS s FROM file_d GROUP BY 1 ORDER BY 1",
            df,
        )
        payload = json.loads(json.dumps(res.rows))
        self.assertEqual(payload[0]["m"][:10], "2024-01-01")
        self.assertEqual(payload[0]["s"], 1)


class TestJsonSafe(unittest.TestCase):
    def test_all_analytics_types(self):
        value = {
            "dt": datetime.datetime(2024, 1, 1), "d": datetime.date(2024, 1, 2), "dec": decimal.Decimal("1.5"),
            "nan": float("nan"), "inf": float("inf"), "np_int": np.int64(3), "np_float": np.float32(1.5),
            "ts": pd.Timestamp("2024-01-03"), "nat": pd.NaT, "na": pd.NA, "arr": np.array([1, 2]),
        }
        out = json.loads(jsonsafe.dumps(value))
        self.assertIsNone(out["nan"])
        self.assertIsNone(out["inf"])
        self.assertIsNone(out["nat"])
        self.assertEqual(out["dec"], 1.5)
        self.assertEqual(out["arr"], [1, 2])


if __name__ == "__main__":
    unittest.main()
