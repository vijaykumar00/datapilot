"""
report_agent.py — Data report: computed statistics + AI-written narrative.

The narrative is generated ONLY from statistics computed here, the prompt
forbids inventing figures, and the computed facts are always appended so the
reader can verify every number.  If the AI provider fails the request fails —
there is no canned "fallback narrative".
"""

import logging

import pandas as pd

from agents.base_agent import AgentResponse, BaseAgent
from core.jsonsafe import to_jsonable

logger = logging.getLogger("datapilot.agent.report")

REPORT_SYSTEM = """You are a data analyst. Write a professional data report with these sections:

## Overview
One paragraph describing the dataset.

## Key Metrics
List 5-8 important metrics with values.

## Trends & Patterns
2-3 notable patterns supported by the statistics.

## Data Quality
Brief assessment of data completeness and reliability.

## Recommendations
2-3 concrete next steps.

STRICT RULES: use ONLY numbers that appear verbatim in the statistics provided. Never estimate,
extrapolate or invent figures, growth rates or percentages. If something cannot be determined
from the statistics, say so. Keep under 400 words."""


def compute_report_facts(df: pd.DataFrame, filename: str, focus: str | None = None) -> dict:
    """Deterministic statistics used both in the prompt and in the rendered report."""
    total_cells = max(df.shape[0] * df.shape[1], 1)
    missing = int(df.isnull().sum().sum())
    facts = {
        "dataset": filename,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing_cells": missing,
        "missing_pct": round(missing / total_cells * 100, 2),
        "duplicate_rows": int(df.duplicated().sum()),
        "numeric": {},
        "categorical": {},
    }
    num_df = df.select_dtypes(include="number")
    for col in list(num_df.columns)[:8]:
        s = num_df[col].dropna()
        if s.empty:
            continue
        facts["numeric"][str(col)] = {
            "sum": round(float(s.sum()), 4), "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4), "min": round(float(s.min()), 4), "max": round(float(s.max()), 4),
        }
    for col in list(df.select_dtypes(exclude="number").columns)[:5]:
        vc = df[col].value_counts().head(3)
        facts["categorical"][str(col)] = {"unique": int(df[col].nunique()),
                                          "top": {str(k): int(v) for k, v in vc.items()}}
    return to_jsonable(facts)


def facts_to_text(facts: dict) -> str:
    lines = [
        f"Dataset: {facts['dataset']}",
        f"Rows: {facts['rows']:,} | Columns: {facts['columns']}",
        f"Missing values: {facts['missing_cells']:,} cells ({facts['missing_pct']}%)",
        f"Duplicate rows: {facts['duplicate_rows']:,}",
    ]
    if facts["numeric"]:
        lines.append("\nNumeric column statistics:")
        for col, st in facts["numeric"].items():
            lines.append(f"  {col}: sum={st['sum']}, mean={st['mean']}, median={st['median']}, min={st['min']}, max={st['max']}")
    if facts["categorical"]:
        lines.append("\nCategorical columns:")
        for col, st in facts["categorical"].items():
            lines.append(f"  {col}: {st['unique']} unique, top={st['top']}")
    return "\n".join(lines)


class ReportAgent(BaseAgent):
    agent_type = "report"

    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        file_id, record = await self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response("No file loaded. Upload a file first.", "report")

        facts = await self.cpu(compute_report_facts, record.df, record.filename)
        stats_text = facts_to_text(facts)
        narrative = await self.llm.generate(f"{stats_text}\n\nUser request: {query}", system=REPORT_SYSTEM, temperature=0.2)

        content = (
            f"# 📊 Data Report: *{record.filename}*\n\n{narrative}\n\n---\n"
            f"*AI-written narrative based only on the computed statistics below.*\n\n```\n{stats_text}\n```"
        )
        return AgentResponse(
            type="report",
            content=content,
            metadata={"filename": record.filename, "row_count": facts["rows"], "col_count": facts["columns"],
                      "facts": facts, "narrative_source": "ai"},
        )
