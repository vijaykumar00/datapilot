"""Question engine (AI-free answers) and question→SQL cache."""

import asyncio
import uuid

import pandas as pd
import pytest

from agents.insight_agent import InsightAgent, _query_cache
from core import sql_cache
from core.data_store import execute_select, get_store
from core.file_manager import FileRecord
from core.question_engine import plan_question

TABLE = "file_test"


@pytest.fixture(scope="module")
def sales():
    rows = []
    regions = ["North", "South", "East", "West"]
    products = ["Widget", "Gadget", "Gizmo"]
    for i in range(48):
        rows.append({
            "order_id": f"00{1000 + i}",
            "date": f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}",
            "region": regions[i % 4],
            "product": products[i % 3],
            "units": (i % 7) + 1,
            "revenue": round(100.5 + i * 10.25, 2),
        })
    return pd.DataFrame(rows)


def run(df, question):
    plan = plan_question(question, df, TABLE)
    assert plan is not None, f"engine should answer: {question}"
    return plan, execute_select(plan.sql, {TABLE: df}).rows


def expect_ai(df, question):
    assert plan_question(question, df, TABLE) is None, f"engine must defer to AI: {question}"


def test_total_and_grouped_totals_match_pandas(sales):
    _, rows = run(sales, "What is the total revenue?")
    assert rows[0]["total_revenue"] == pytest.approx(sales.revenue.sum())

    _, rows = run(sales, "total revenue by region")
    expected = sales.groupby("region").revenue.sum().sort_values(ascending=False)
    assert [r["region"] for r in rows] == list(expected.index)
    assert rows[0]["total_revenue"] == pytest.approx(expected.iloc[0])


def test_average_median_min_max(sales):
    assert run(sales, "average units per product")[1][0]["average_units"] == pytest.approx(
        round(sales.groupby("product").units.mean().max(), 2))
    assert run(sales, "median revenue")[1][0]["median_revenue"] == pytest.approx(sales.revenue.median(), abs=0.01)
    assert run(sales, "highest revenue")[1][0]["max_revenue"] == pytest.approx(sales.revenue.max())
    assert run(sales, "lowest units")[1][0]["min_units"] == sales.units.min()


def test_top_bottom_and_which(sales):
    plan, rows = run(sales, "top 2 products by revenue")
    assert "LIMIT 2" in plan.sql and len(rows) == 2
    assert rows[0]["product"] == sales.groupby("product").revenue.sum().idxmax()

    _, rows = run(sales, "bottom 3 regions by units")
    assert len(rows) == 3 and rows[0]["total_units"] == sales.groupby("region").units.sum().min()

    _, rows = run(sales, "which region has the highest revenue")
    assert len(rows) == 1 and rows[0]["region"] == sales.groupby("region").revenue.sum().idxmax()


def test_counts_and_distinct(sales):
    assert run(sales, "how many rows")[1][0]["count"] == len(sales)
    assert run(sales, "how many orders in West")[1][0]["count"] == int((sales.region == "West").sum())
    assert run(sales, "number of unique products")[1][0]["count"] == sales["product"].nunique()
    _, rows = run(sales, "count by region")
    assert {r["region"]: r["count"] for r in rows} == sales.region.value_counts().to_dict()


def test_filters_by_value_year_and_month(sales):
    _, rows = run(sales, "total sales in the West region")  # synonym + value + column word
    assert rows[0]["total_revenue"] == pytest.approx(sales[sales.region == "West"].revenue.sum())
    _, rows = run(sales, "revenue in March")
    march = sales[pd.to_datetime(sales.date).dt.month == 3].revenue.sum()
    assert rows[0]["total_revenue"] == pytest.approx(march)
    plan, _ = run(sales, "average revenue by region in 2026")
    assert "year(" in plan.sql and "= 2026" in plan.sql


def test_time_series_grouping(sales):
    plan, rows = run(sales, "revenue by month")
    assert [r["month"] for r in rows] == sorted(r["month"] for r in rows)
    assert rows[0]["month"] == "2026-01"
    assert run(sales, "monthly revenue")[0].sql == plan.sql
    _, rows = run(sales, "units by quarter")
    assert rows[0]["quarter"] == "2026-Q1" and len(rows) == 4


@pytest.mark.parametrize("question", [
    "why is revenue lower in North",
    "compare West and East revenue",
    "revenue growth by month",
    "what percent of revenue is from Widget",
    "revenue per unit by product",
    "orders where revenue > 1000",
    "total revenue and units by region",
    "total profit",                     # no such column
    "top customers",                    # no such column
    "show me something interesting",
    "summarize this data",
    "revenue not in West",
])
def test_defers_to_ai_when_unsure(sales, question):
    expect_ai(sales, question)


def test_ambiguous_columns_defer_to_ai():
    df = pd.DataFrame({"region": ["A", "B"], "revenue_2025": [1.0, 2.0], "revenue_2026": [3.0, 4.0]})
    expect_ai(df, "total revenue by region")
    assert plan_question("total revenue 2026 by region", df, TABLE) is not None


def test_column_names_with_spaces_and_quotes_are_quoted():
    df = pd.DataFrame({"Sales Rep": ["Ann", "Bo", "Ann"], 'Deal "Size"': [10.0, 20.0, 30.0],
                       "Team": ["O'Brien", "X", "O'Brien"]})
    plan, rows = run(df, "total deal size by sales rep")
    assert '"Sales Rep"' in plan.sql and '"Deal ""Size"""' in plan.sql
    assert rows[0] == {"sales rep": "Ann", 'total_deal "size"': 40.0}
    plan, rows = run(df, "total deal size for o'brien")
    assert "'O''Brien'" in plan.sql and rows[0]['total_deal "size"'] == 40.0


def test_sql_cache_round_trip_is_workspace_scoped(sales):
    ws = f"ws_{uuid.uuid4().hex[:8]}"
    sql = f'SELECT "region", SUM("revenue") AS r FROM "{TABLE}" GROUP BY 1'
    sql_cache.store(ws, sales, "Revenue per region please", TABLE, sql, "by region")
    hit = sql_cache.lookup(ws, sales, "what is revenue per region", "file_other")
    assert hit == ('SELECT "region", SUM("revenue") AS r FROM "file_other" GROUP BY 1', "by region")
    assert sql_cache.lookup("another_workspace", sales, "revenue per region", TABLE) is None
    # A different column layout never reuses the SQL.
    assert sql_cache.lookup(ws, sales.drop(columns=["units"]), "revenue per region", TABLE) is None
    sql_cache.forget(ws, sales, "revenue per region")
    assert sql_cache.lookup(ws, sales, "revenue per region", TABLE) is None


class _CountingLLM:
    settings = None

    def __init__(self, sql):
        self.sql = sql
        self.calls = 0

    async def generate(self, prompt, system=None, json_mode=False, **kwargs):
        self.calls += 1
        return '{"sql": "%s", "explanation": "ai"}' % self.sql.replace('"', '\\"')


def _agent(df, llm, ws):
    class Files:
        def get_record(self, fid, workspace_id=None):
            return FileRecord(file_id=fid, filename="sales.csv", df=df, path="sales.csv")
    return InsightAgent(llm_client=llm, data_store=get_store(), file_manager=Files(), workspace_id=ws)


def test_agent_uses_engine_then_cache_then_ai(sales):
    _query_cache.clear()
    ws = f"ws_{uuid.uuid4().hex[:8]}"
    llm = _CountingLLM('SELECT "product", AVG("revenue") AS avg_rev FROM file_f1 GROUP BY 1')

    # Engine: no AI call at all.
    resp = asyncio.run(_agent(sales, llm, ws).run("total revenue by region", ["f1"]))
    assert resp.error is None and resp.metadata["answered_by"] == "engine" and llm.calls == 0
    assert "no AI" in resp.metadata["explain"]["verification"]

    # Unknown phrasing → AI once, then the SQL cache answers the repeat (even for a new upload).
    q = "revenue per unit sold for each product"
    resp = asyncio.run(_agent(sales, llm, ws).run(q, ["f1"]))
    assert resp.metadata["answered_by"] == "ai" and llm.calls == 1
    _query_cache.clear()
    resp = asyncio.run(_agent(sales, llm, ws).run(q, ["f2"]))
    assert resp.metadata["answered_by"] == "cache" and llm.calls == 1
    assert "file_f2" in resp.metadata["sql"] and resp.table_data


def test_headcount_period_ranking_and_distinct_ids():
    hr = pd.DataFrame({
        "employee_id": ["E1", "E2", "E3", "E4", "E5"],
        "department": ["IT", "IT", "Ops", "Ops", "Ops"],
        "salary": [10, 20, 30, 40, 50],
        "hire_date": ["2024-01-05", "2024-02-05", "2024-02-07", "2025-03-01", "2025-03-09"],
    })
    _, rows = run(hr, "number of employees by department")
    assert {r["department"]: r["count"] for r in rows} == {"IT": 2, "Ops": 3}
    _, rows = run(hr, "headcount by department")
    assert rows[0] == {"department": "Ops", "count": 3}
    plan, rows = run(hr, "which month had the highest salary")
    assert rows == [{"month": "2025-03", "total_salary": 90}] and plan.explanation.startswith("The month")
