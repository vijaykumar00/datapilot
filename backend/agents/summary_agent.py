"""
summary_agent.py - Executive business summary with key drivers and anomalies.
Uses local stats first and LLM enhancement when available.
"""

import logging
import os

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

ENABLE_LLM_SUMMARY = os.getenv("ENABLE_LLM_SUMMARY", "0").lower() in {"1", "true", "yes"}


class SummaryAgent(BaseAgent):
    agent_type = "summary"
    timeout_seconds = 20

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

        if self._is_sheet_query(query):
            return self._sheet_response(record)

        df = record.df
        stats = self._compute_stats(df, record.filename, record.metadata)
        narrative = self._build_local_narrative(stats, record)

        if ENABLE_LLM_SUMMARY:
            prompt = f"Dataset: {record.filename}\n\nStatistics:\n{stats['text_summary']}"
            try:
                llm_text = await self.llm.generate(
                    prompt,
                    system=SUMMARY_SYSTEM,
                    temperature=0.3,
                )
                if llm_text and not llm_text.startswith("[Gemini error:"):
                    narrative = llm_text
            except Exception as e:
                logger.warning("Summary LLM enhancement failed; using local summary: %s", e)

        content = f"## Executive Summary: *{record.filename}*\n\n"
        content += narrative
        content += "\n\n---\n**Dataset at a glance:**\n"
        content += f"- Rows: **{stats['row_count']:,}** | Columns: **{stats['col_count']}**\n"
        content += f"- Numeric columns: {stats['num_cols']} | Text columns: {stats['cat_cols']}\n"
        if stats["sheet_names"]:
            content += f"- Excel sheets: {', '.join(stats['sheet_names'])}\n"
        if stats["null_pct"] > 0:
            content += f"- Missing data: **{stats['null_pct']:.1f}%** of cells\n"
        if stats["dup_count"] > 0:
            content += f"- Duplicate rows: **{stats['dup_count']:,}**\n"

        return AgentResponse(
            type="summary",
            content=content,
            table_data=stats["column_stats"],
            metadata=stats,
        )

    def _is_sheet_query(self, query: str) -> bool:
        lower = query.lower()
        keywords = ("sheet", "sheets", "worksheet", "worksheets", "tab", "tabs")
        return any(word in lower for word in keywords)

    def _sheet_response(self, record) -> AgentResponse:
        sheet_names = record.metadata.get("sheet_names", [])
        active_sheet = record.metadata.get("active_sheet")
        if not sheet_names:
            return AgentResponse(
                type="summary",
                content=(
                    f"**{record.filename}** is loaded, but it does not expose multiple Excel "
                    f"sheets in the current upload format. The active data contains "
                    f"**{len(record.df):,} rows** and **{len(record.df.columns)} columns**."
                ),
                metadata={"filename": record.filename},
            )

        lines = [f"**Excel sheets in {record.filename}:**"]
        for name in sheet_names:
            marker = " (active)" if name == active_sheet else ""
            lines.append(f"- {name}{marker}")

        return AgentResponse(
            type="summary",
            content="\n".join(lines),
            metadata={
                "filename": record.filename,
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
            },
        )

    def _build_local_narrative(self, stats: dict, record) -> str:
        lines = [
            (
                f"This dataset contains **{stats['row_count']:,} rows** and "
                f"**{stats['col_count']} columns** from **{record.filename}**."
            )
        ]

        insights = []
        if stats["num_cols"] > 0:
            insights.append(
                f"- The file includes **{stats['num_cols']} numeric columns**, which are ready for quantitative analysis."
            )
        if stats["cat_cols"] > 0:
            insights.append(
                f"- The file includes **{stats['cat_cols']} text/categorical columns**, useful for grouping and segmentation."
            )
        if stats["sheet_names"]:
            insights.append(
                f"- The workbook contains **{len(stats['sheet_names'])} sheet(s)**: {', '.join(stats['sheet_names'])}."
            )
        if stats["top_categorical"]:
            insights.append(f"- Example categories detected: {stats['top_categorical']}.")
        if not insights:
            insights.append("- The upload was parsed successfully and is ready for exploration.")

        concerns = []
        if stats["null_pct"] > 0:
            concerns.append(f"- Missing values affect **{stats['null_pct']:.1f}%** of all cells.")
        if stats["dup_count"] > 0:
            concerns.append(f"- The file contains **{stats['dup_count']:,} duplicate row(s)**.")
        if not concerns:
            concerns.append("- No obvious missing-data or duplicate-row issues were detected at a high level.")

        recommendation = (
            "Use a targeted question next, such as totals by category, trends over time, "
            "or a data-quality check, to get a faster and more precise answer."
        )

        return "\n".join(
            [
                lines[0],
                "",
                "**Key insights**",
                *insights[:3],
                "",
                "**Potential concerns**",
                *concerns[:2],
                "",
                f"**Recommendation:** {recommendation}",
            ]
        )

    def _compute_stats(
        self,
        df: pd.DataFrame,
        filename: str,
        metadata: dict,
    ) -> dict:
        """Compute statistical summary for LLM context."""
        num_df = df.select_dtypes(include="number")
        cat_df = df.select_dtypes(include=["object", "category", "bool"])

        text_parts = [f"File: {filename}, {len(df)} rows, {len(df.columns)} columns"]
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

        top_categorical_parts = []
        for col in cat_df.columns[:5]:
            vc = df[col].value_counts(dropna=True)
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
            top_keys = [str(k) for k in top3.keys()]
            if top_keys:
                top_categorical_parts.append(f"{col}: {', '.join(top_keys)}")
            text_parts.append(f"{col}: {df[col].nunique()} unique values, top={top_keys}")

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
            "top_categorical": "; ".join(top_categorical_parts[:2]),
            "sheet_names": metadata.get("sheet_names", []),
            "text_summary": "\n".join(text_parts),
        }
