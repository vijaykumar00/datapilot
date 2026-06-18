"""
suggestion_engine.py — Deterministic smart suggestion generator for DataPilot.

Analyzes a FileRecord's DataFrame + semantic metadata to produce a prioritized
list of proactive AI suggestions. Zero LLM calls required.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("datapilot.suggestions")

# Priority levels
P_CRITICAL = 1   # Data quality issues — user must know
P_HIGH = 2       # High-value analysis opportunities
P_MEDIUM = 3     # Always-available actions


def _has_date_column(df: pd.DataFrame) -> str | None:
    """Return the first detected date-like column name, or None."""
    date_kws = {"date", "time", "month", "year", "week", "period", "day", "created", "updated", "timestamp"}
    for col in df.columns:
        if any(kw in str(col).lower() for kw in date_kws):
            try:
                pd.to_datetime(df[col], errors="raise")
                return col
            except Exception:
                pass
    # Fallback: check value patterns
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(20)
        converted = pd.to_datetime(sample, errors="coerce")
        if converted.notna().sum() / max(len(sample), 1) > 0.7:
            return col
    return None


def _find_numeric_columns(df: pd.DataFrame) -> list[str]:
    return list(df.select_dtypes(include="number").columns)


def _find_currency_columns(df: pd.DataFrame, sem_map: dict) -> list[str]:
    """Columns with semantic type 'currency' or name matching revenue/sales/amount."""
    currency_kws = {"revenue", "sales", "amount", "cost", "price", "spend", "profit", "income", "salary"}
    results = []
    for col in df.columns:
        sem = sem_map.get(str(col), {})
        if sem.get("semantic_type") == "currency":
            results.append(col)
            continue
        if any(kw in str(col).lower() for kw in currency_kws):
            results.append(col)
    return results


def _find_id_columns(df: pd.DataFrame, sem_map: dict) -> list[str]:
    id_kws = {"id", "key", "code", "pk", "fk", "sku", "invoice", "order", "num"}
    results = []
    for col in df.columns:
        sem = sem_map.get(str(col), {})
        if sem.get("semantic_type") == "id":
            results.append(col)
            continue
        if any(kw in str(col).lower() for kw in id_kws):
            results.append(col)
    return results


def _find_categorical_columns(df: pd.DataFrame, sem_map: dict) -> list[str]:
    results = []
    for col in df.select_dtypes(include="object").columns:
        sem = sem_map.get(str(col), {})
        if sem.get("semantic_type") in ("categorical", "text") or df[col].nunique() <= 50:
            results.append(col)
    return results


def generate_suggestions(df: pd.DataFrame, filename: str, metadata: dict) -> list[dict[str, Any]]:
    """
    Analyze a file's DataFrame and metadata to generate prioritized suggestions.
    Returns a list of suggestion dicts, sorted by priority, capped at 6.
    """
    suggestions: list[dict] = []
    sem_map: dict = metadata.get("semantic_map", {})
    row_count = len(df)
    col_count = len(df.columns)

    date_col = _has_date_column(df)
    num_cols = _find_numeric_columns(df)
    currency_cols = _find_currency_columns(df, sem_map)
    id_cols = _find_id_columns(df, sem_map)
    cat_cols = _find_categorical_columns(df, sem_map)

    # ── RULE 1: Duplicate IDs (Priority CRITICAL) ─────────────────────────────
    for id_col in id_cols[:2]:  # Check first 2 ID columns
        total = len(df)
        unique = df[id_col].nunique()
        dupes = total - unique
        if dupes > 0:
            dupe_pct = round(dupes / total * 100, 1)
            suggestions.append({
                "id": f"suggest_dedup_{id_col}",
                "type": "clean",
                "priority": P_CRITICAL,
                "title": f"Found {dupes:,} Duplicate {id_col}s",
                "description": f"{dupe_pct}% of rows share a duplicate `{id_col}` value. Remove duplicates to ensure data integrity.",
                "prompt": f"Remove duplicate rows based on {id_col}",
                "icon": "🔁",
                "badge": "Data Issue",
                "detected_evidence": f"{dupes} duplicate {id_col} values out of {total} rows",
            })

    # ── RULE 2: Missing Values (Priority CRITICAL) ────────────────────────────
    null_info = []
    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        null_pct = null_count / row_count * 100 if row_count > 0 else 0
        if null_pct > 5:
            null_info.append((col, null_count, round(null_pct, 1)))

    if null_info:
        # Surface the worst column
        worst_col, worst_n, worst_pct = max(null_info, key=lambda x: x[2])
        cols_affected = len(null_info)
        suggestions.append({
            "id": "suggest_fix_nulls",
            "type": "clean",
            "priority": P_CRITICAL,
            "title": f"Missing Values in {cols_affected} Column{'s' if cols_affected > 1 else ''}",
            "description": f"`{worst_col}` is {worst_pct}% empty. I can fill gaps using mean, median, or forward-fill strategies.",
            "prompt": f"Handle missing values in the dataset, especially in {worst_col}",
            "icon": "🕳️",
            "badge": "Data Issue",
            "detected_evidence": f"{worst_n} nulls in {worst_col} ({worst_pct}%)",
        })

    # ── RULE 3: Forecast Opportunity (Priority HIGH) ──────────────────────────
    if date_col and num_cols:
        # Pick best numeric column for forecast
        forecast_col = currency_cols[0] if currency_cols else num_cols[0]
        suggestions.append({
            "id": f"suggest_forecast_{forecast_col}",
            "type": "forecast",
            "priority": P_HIGH,
            "title": f"Forecast {forecast_col} Trend",
            "description": f"Detected date column `{date_col}` and metric `{forecast_col}`. I can project the next 3 months with confidence intervals.",
            "prompt": f"Forecast {forecast_col} for the next 3 months",
            "icon": "🔮",
            "badge": "AI Ready",
            "detected_evidence": f"date_col={date_col}, value_col={forecast_col}, {row_count} rows",
        })

    # ── RULE 4: Revenue / Sales Trend Analysis (Priority HIGH) ───────────────
    if currency_cols and date_col:
        rev_col = currency_cols[0]
        suggestions.append({
            "id": f"suggest_revenue_trend_{rev_col}",
            "type": "insight",
            "priority": P_HIGH,
            "title": f"Analyze {rev_col} by Month",
            "description": f"Break down `{rev_col}` over time using `{date_col}`. Spot growth patterns and seasonal dips.",
            "prompt": f"Show total {rev_col} grouped by {date_col}",
            "icon": "💰",
            "badge": "Business Intel",
            "detected_evidence": f"currency_col={rev_col}, date_col={date_col}",
        })
    elif currency_cols and cat_cols:
        rev_col = currency_cols[0]
        cat_col = cat_cols[0]
        suggestions.append({
            "id": f"suggest_revenue_by_{cat_col}",
            "type": "insight",
            "priority": P_HIGH,
            "title": f"{rev_col} by {cat_col}",
            "description": f"Which `{cat_col}` drives the most `{rev_col}`? Find your top performers instantly.",
            "prompt": f"Show total {rev_col} grouped by {cat_col} ordered by highest",
            "icon": "💡",
            "badge": "Business Intel",
            "detected_evidence": f"currency_col={rev_col}, cat_col={cat_col}",
        })

    # ── RULE 5: Chart Opportunity (Priority HIGH) ─────────────────────────────
    if cat_cols and num_cols:
        cat_col = cat_cols[0]
        num_col = currency_cols[0] if currency_cols else num_cols[0]
        suggestions.append({
            "id": f"suggest_chart_{cat_col}_{num_col}",
            "type": "visualize",
            "priority": P_HIGH,
            "title": f"Visualize {num_col} by {cat_col}",
            "description": f"Generate a bar chart comparing `{num_col}` across all `{cat_col}` categories.",
            "prompt": f"Show me a bar chart of {num_col} by {cat_col}",
            "icon": "📊",
            "badge": "Chart Ready",
            "detected_evidence": f"cat_col={cat_col}, metric_col={num_col}, {df[cat_col].nunique()} categories",
        })

    # ── RULE 6: High-cardinality category insight (Priority HIGH) ────────────
    high_card_cols = [c for c in cat_cols if df[c].nunique() > 15]
    if high_card_cols and num_cols:
        hc_col = high_card_cols[0]
        metric_col = currency_cols[0] if currency_cols else num_cols[0]
        suggestions.append({
            "id": f"suggest_top_{hc_col}",
            "type": "insight",
            "priority": P_HIGH,
            "title": f"Top 10 {hc_col} by {metric_col}",
            "description": f"`{hc_col}` has {df[hc_col].nunique()} unique values. Rank the top 10 by `{metric_col}` to identify key drivers.",
            "prompt": f"Show top 10 {hc_col} by total {metric_col}",
            "icon": "🏆",
            "badge": "Ranking",
            "detected_evidence": f"{df[hc_col].nunique()} unique {hc_col} values",
        })

    # ── RULE 7: Distribution / Outlier Analysis (Priority MEDIUM) ────────────
    if num_cols:
        # Find column with highest relative std (most interesting distribution)
        best_col = None
        best_cv = 0.0
        for col in num_cols[:5]:  # Check first 5 numeric cols
            col_data = df[col].dropna()
            if len(col_data) < 5:
                continue
            mean = col_data.mean()
            std = col_data.std()
            cv = abs(std / mean) if mean != 0 else 0
            if cv > best_cv:
                best_cv = cv
                best_col = col
        if best_col:
            suggestions.append({
                "id": f"suggest_distribution_{best_col}",
                "type": "visualize",
                "priority": P_MEDIUM,
                "title": f"Distribution of {best_col}",
                "description": f"`{best_col}` shows high variability (CV={best_cv:.1f}x). A histogram will reveal outliers and clusters.",
                "prompt": f"Show the distribution and outliers of {best_col}",
                "icon": "📉",
                "badge": "Outlier Check",
                "detected_evidence": f"coefficient_of_variation={best_cv:.2f}",
            })

    # ── RULE 8: Executive Summary (Priority MEDIUM, always available) ─────────
    if row_count >= 10:
        suggestions.append({
            "id": "suggest_summary",
            "type": "summary",
            "priority": P_MEDIUM,
            "title": "Generate Executive Summary",
            "description": f"Summarize key statistics, notable trends, and data quality for all {col_count} columns in `{filename}`.",
            "prompt": "Generate an executive summary of this dataset",
            "icon": "📋",
            "badge": "Always Ready",
            "detected_evidence": f"{row_count} rows, {col_count} columns",
        })

    # ── RULE 9: Data Type Normalization (Priority MEDIUM) ────────────────────
    # Check for columns that look numeric but are stored as strings
    type_issues = []
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(50)
        try:
            converted = pd.to_numeric(sample, errors="coerce")
            ratio = converted.notna().sum() / max(len(sample), 1)
            if ratio > 0.85:
                type_issues.append(col)
        except Exception:
            pass

    if type_issues:
        col_list = ", ".join(f"`{c}`" for c in type_issues[:3])
        suggestions.append({
            "id": "suggest_type_fix",
            "type": "clean",
            "priority": P_MEDIUM,
            "title": f"Fix Column Types",
            "description": f"{col_list} {'are' if len(type_issues) > 1 else 'is'} stored as text but contain numbers. Converting will unlock math operations.",
            "prompt": f"Fix column data types and convert text columns to numeric where appropriate",
            "icon": "🔧",
            "badge": "Type Error",
            "detected_evidence": f"{len(type_issues)} columns with type mismatch",
        })

    # ── Sort by priority, deduplicate by id, cap at 6 ────────────────────────
    seen_ids: set[str] = set()
    unique_suggestions = []
    for s in sorted(suggestions, key=lambda x: x["priority"]):
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            unique_suggestions.append(s)

    final = unique_suggestions[:6]
    logger.info(f"Generated {len(final)} suggestions for '{filename}' from {len(suggestions)} candidates")
    return final


def build_greeting(filename: str, row_count: int, col_count: int, suggestions: list[dict]) -> str:
    """
    Build the proactive greeting message injected into chat on upload.
    Surfaces the top 3 findings in bullet form.
    """
    lines = [
        f"👋 I've analyzed **{filename}** ({row_count:,} rows, {col_count} columns). Here's what I found:\n"
    ]

    # Surface top-priority findings
    for s in suggestions[:4]:
        badge_map = {
            "clean": "⚠️",
            "forecast": "🔮",
            "insight": "💡",
            "visualize": "📊",
            "summary": "📋",
        }
        emoji = badge_map.get(s["type"], "✦")
        lines.append(f"- {emoji} **{s['title']}** — {s['description']}")

    lines.append(
        "\n> Click any suggestion below to run the analysis instantly, or ask me anything about your data."
    )
    return "\n".join(lines)
