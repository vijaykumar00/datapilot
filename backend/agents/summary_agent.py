"""
summary_agent.py — Executive business summary with key drivers and anomalies.
Combines statistical analysis with LLM narrative generation.
"""

import logging

import numpy as np
import pandas as pd

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.summary")

SUMMARY_SYSTEM = """You are a business analyst writing executive summaries.

Given dataset statistics, write a concise executive summary:
1. Start with a 1-sentence overview of what the dataset contains
2. List the TOP 3 key insights or patterns (use bullet points)
3. List up to 2 anomalies or concerns
4. End with 1 actionable recommendation

Keep it under 200 words. Use business language. No code. No jargon."""


class SummaryAgent(BaseAgent):
    agent_type = "summary"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response(
                "No file loaded. Upload a file first.", "summary"
            )

        df = record.df
        stats = self._compute_stats(df, record.filename)

        # Ask LLM to narrate the stats
        prompt = f"Dataset: {record.filename}\n\nStatistics:\n{stats['text_summary']}"
        narrative = await self.llm.generate(prompt, system=SUMMARY_SYSTEM, temperature=0.3)

        content = f"## 📋 Executive Summary: *{record.filename}*\n\n"
        content += narrative
        content += f"\n\n---\n**Dataset at a glance:**\n"
        content += f"- Rows: **{stats['row_count']:,}** | Columns: **{stats['col_count']}**\n"
        content += f"- Numeric columns: {stats['num_cols']} | Text columns: {stats['cat_cols']}\n"
        if stats['null_pct'] > 0:
            content += f"- Missing data: **{stats['null_pct']:.1f}%** of cells\n"
        if stats['dup_count'] > 0:
            content += f"- Duplicate rows: **{stats['dup_count']:,}**\n"

        return AgentResponse(
            type="summary",
            content=content,
            table_data=stats["column_stats"],
            metadata=stats,
        )

    def _compute_stats(self, df: pd.DataFrame, filename: str) -> dict:
        """Compute statistical summary for LLM context."""
        num_df = df.select_dtypes(include="number")
        cat_df = df.select_dtypes(include="object")

        text_parts = [f"File: {filename}, {len(df)} rows, {len(df.columns)} columns"]

        # Numeric stats
        col_stats = []
        for col in num_df.columns:
            series = num_df[col].dropna()
            if len(series) == 0:
                continue
            stat = {
                "column": col,
                "type": "numeric",
                "mean": round(float(series.mean()), 2),
                "median": round(float(series.median()), 2),
                "std": round(float(series.std()), 2),
                "min": round(float(series.min()), 2),
                "max": round(float(series.max()), 2),
                "null_count": int(df[col].isnull().sum()),
            }
            col_stats.append(stat)
            text_parts.append(
                f"{col}: mean={stat['mean']}, median={stat['median']}, "
                f"min={stat['min']}, max={stat['max']}, std={stat['std']}"
            )

        # Categorical stats
        for col in cat_df.columns[:5]:  # limit to 5 cat cols
            vc = df[col].value_counts()
            top3 = vc.head(3).to_dict()
            col_stats.append(
                {
                    "column": col,
                    "type": "categorical",
                    "unique_count": int(df[col].nunique()),
                    "top_values": {str(k): int(v) for k, v in top3.items()},
                    "null_count": int(df[col].isnull().sum()),
                }
            )
            text_parts.append(f"{col}: {df[col].nunique()} unique values, top={list(top3.keys())}")

        total_cells = df.shape[0] * df.shape[1]
        null_cells = int(df.isnull().sum().sum())

        return {
            "row_count": len(df),
            "col_count": len(df.columns),
            "num_cols": len(num_df.columns),
            "cat_cols": len(cat_df.columns),
            "null_pct": null_cells / max(total_cells, 1) * 100,
            "dup_count": int(df.duplicated().sum()),
            "column_stats": col_stats,
            "text_summary": "\n".join(text_parts),
        }
