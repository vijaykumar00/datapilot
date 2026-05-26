"""
report_agent.py — Full data report combining summary + stats + viz.
"""

import logging

import pandas as pd

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.report")

REPORT_SYSTEM = """You are a data analyst. Write a professional data report with these sections:

## Overview
One paragraph describing the dataset.

## Key Metrics
List 5-8 important metrics with values.

## Trends & Patterns
2-3 notable patterns you observe.

## Data Quality
Brief assessment of data completeness and reliability.

## Recommendations
2-3 concrete next steps.

Be specific, use numbers from the statistics provided. Keep under 400 words."""


class ReportAgent(BaseAgent):
    agent_type = "report"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response(
                "No file loaded. Upload a file first.", "report"
            )

        df = record.df

        # Build stats context
        stats_lines = [
            f"Dataset: {record.filename}",
            f"Rows: {len(df):,} | Columns: {len(df.columns)}",
            f"Columns: {list(df.columns)}",
            f"Missing values: {df.isnull().sum().sum():,} cells ({df.isnull().sum().sum() / (df.shape[0]*df.shape[1])*100:.1f}%)",
            f"Duplicate rows: {df.duplicated().sum():,}",
        ]

        num_df = df.select_dtypes(include="number")
        if not num_df.empty:
            stats_lines.append("\nNumeric column statistics:")
            desc = num_df.describe().round(2)
            for col in desc.columns[:8]:  # limit
                stats_lines.append(
                    f"  {col}: mean={desc.loc['mean', col]}, "
                    f"min={desc.loc['min', col]}, max={desc.loc['max', col]}"
                )

        cat_df = df.select_dtypes(include="object")
        if not cat_df.empty:
            stats_lines.append("\nCategorical columns:")
            for col in cat_df.columns[:5]:
                top = df[col].value_counts().head(3).to_dict()
                stats_lines.append(f"  {col}: {df[col].nunique()} unique, top={top}")

        prompt = "\n".join(stats_lines)
        report_text = await self.llm.generate(prompt, system=REPORT_SYSTEM, temperature=0.2)

        content = f"# 📊 Data Report: *{record.filename}*\n\n" + report_text

        return AgentResponse(
            type="report",
            content=content,
            metadata={
                "filename": record.filename,
                "row_count": len(df),
                "col_count": len(df.columns),
            },
        )
