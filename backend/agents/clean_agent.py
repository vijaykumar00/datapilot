"""
clean_agent.py — Automated data quality detection and safe fixing.
Never modifies the original; returns a diff of changes.
"""

import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.clean")


def _detect_outliers_iqr(series: pd.Series) -> pd.Series:
    """Return boolean mask of outliers using IQR method."""
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return (series < lower) | (series > upper)


class CleanAgent(BaseAgent):
    agent_type = "clean"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response(
                "No file loaded. Upload a CSV or Excel file first.", "clean"
            )

        df = record.df.copy()
        issues: list[dict[str, Any]] = []
        fixes: list[dict[str, Any]] = []

        # --- 1. Duplicate rows ---
        dup_count = int(df.duplicated().sum())
        if dup_count > 0:
            issues.append(
                {
                    "type": "duplicates",
                    "severity": "medium",
                    "description": f"{dup_count} duplicate row(s) detected",
                    "affected_rows": dup_count,
                    "fix": "Remove duplicate rows",
                }
            )

        # --- 2. Missing values ---
        null_counts = df.isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                pct = round(count / len(df) * 100, 1)
                dtype = str(df[col].dtype)
                if "float" in dtype or "int" in dtype:
                    strategy = f"fill with median ({df[col].median():.2f})"
                elif "object" in dtype or "string" in dtype:
                    mode_val = df[col].mode()
                    strategy = f"fill with mode ('{mode_val.iloc[0]}')" if len(mode_val) > 0 else "fill with 'Unknown'"
                else:
                    strategy = "drop rows"

                issues.append(
                    {
                        "type": "missing_values",
                        "severity": "high" if pct > 20 else "low",
                        "description": f"Column '{col}': {count} nulls ({pct}%)",
                        "column": col,
                        "count": int(count),
                        "percentage": pct,
                        "fix": strategy,
                    }
                )

        # --- 3. Type mismatches (numbers stored as strings) ---
        for col in df.select_dtypes(include="object").columns:
            sample = df[col].dropna().head(100)
            numeric_count = pd.to_numeric(sample, errors="coerce").notna().sum()
            if numeric_count / max(len(sample), 1) > 0.8:
                issues.append(
                    {
                        "type": "type_mismatch",
                        "severity": "medium",
                        "description": f"Column '{col}' looks numeric but is stored as text",
                        "column": col,
                        "fix": f"Convert '{col}' to numeric type",
                    }
                )

        # --- 4. Outliers in numeric columns ---
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols[:10]:  # Cap at 10 columns for speed
            if df[col].nunique() < 5:
                continue
            outlier_mask = _detect_outliers_iqr(df[col].dropna())
            outlier_count = int(outlier_mask.sum())
            if outlier_count > 0:
                pct = round(outlier_count / len(df) * 100, 1)
                q1 = df[col].quantile(0.25)
                q3 = df[col].quantile(0.75)
                iqr = q3 - q1
                issues.append(
                    {
                        "type": "outlier",
                        "severity": "low",
                        "description": f"Column '{col}': {outlier_count} outlier(s) ({pct}%) outside IQR range [{q1 - 1.5*iqr:.2f}, {q3 + 1.5*iqr:.2f}]",
                        "column": col,
                        "count": outlier_count,
                        "fix": "Flag or cap outliers (review recommended)",
                    }
                )

        # Build summary
        high_count = sum(1 for i in issues if i["severity"] == "high")
        med_count = sum(1 for i in issues if i["severity"] == "medium")
        low_count = sum(1 for i in issues if i["severity"] == "low")

        if not issues:
            content = "✅ **Your data looks clean!** No significant issues detected."
        else:
            content = (
                f"🔍 **Data Quality Report** — {len(issues)} issue(s) found\n\n"
                f"- 🔴 High: {high_count}  🟡 Medium: {med_count}  🟢 Low: {low_count}\n\n"
                f"**Issues detected:**\n"
            )
            for i, issue in enumerate(issues, 1):
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(issue["severity"], "⚪")
                content += f"{i}. {sev_icon} {issue['description']}\n   → *Suggested fix:* {issue['fix']}\n\n"

            content += "\n> ⚠️ No changes have been made. Confirm in the UI to apply fixes."

        return AgentResponse(
            type="clean",
            content=content,
            table_data=issues,
            metadata={
                "total_issues": len(issues),
                "high": high_count,
                "medium": med_count,
                "low": low_count,
                "row_count": len(df),
                "column_count": len(df.columns),
            },
        )
