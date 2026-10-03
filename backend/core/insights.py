"""
insights.py — Automated profiling, semantic schema understanding, and insight generation.
"""

import json
import logging
import re
from typing import Any
import numpy as np
import pandas as pd
from core.llm_client import get_llm_client

logger = logging.getLogger("datapilot.insights")


def infer_semantic_type(col_name: Any, series: pd.Series) -> str:
    """Infer semantic column type (e.g. date, currency, percentage, ID, email, phone, numeric, categorical)."""
    name_str = str(col_name)
    name_lower = name_str.lower()

    # Drop nulls for checking content patterns
    sample_values = series.dropna().head(100).astype(str).tolist()
    if not sample_values:
        return "empty"

    # 1. Date/Time
    date_indicators = {"date", "time", "created", "updated", "year", "month", "day", "timestamp"}
    if any(ind in name_lower for ind in date_indicators):
        return "datetime"
    # Check values
    date_pattern = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:\s+\d{2}:\d{2}:\d{2})?$")
    if sum(1 for val in sample_values if date_pattern.match(val)) / len(sample_values) > 0.8:
        return "datetime"

    # 2. Email
    email_pattern = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
    if sum(1 for val in sample_values if email_pattern.match(val)) / len(sample_values) > 0.8:
        return "email"

    # 3. Currency
    currency_indicators = {"price", "amount", "cost", "revenue", "sales", "usd", "eur", "gbp", "inr", "amt", "salary", "spend"}
    if any(ind in name_lower for ind in currency_indicators):
        return "currency"
    # Check values for currency symbols
    curr_pattern = re.compile(r"^\s*[\$\u20AC\u00A3\u00A5]?\s*-?\d+(?:\.\d+)?\s*[\$\u20AC\u00A3\u00A5]?\s*$")
    if sum(1 for val in sample_values if curr_pattern.match(val)) / len(sample_values) > 0.8:
        return "currency"

    # 4. Percentage
    pct_indicators = {"pct", "percent", "rate", "margin", "ratio"}
    if any(ind in name_lower for ind in pct_indicators):
        return "percentage"
    pct_pattern = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*%\s*$")
    if sum(1 for val in sample_values if pct_pattern.match(val)) / len(sample_values) > 0.8:
        return "percentage"

    # 5. ID / Key
    id_indicators = {"id", "key", "code", "num", "pk", "fk", "sku"}
    if any(ind in name_lower for ind in id_indicators):
        return "id"
    # Check if highly unique and numeric/alphanumeric
    is_unique = series.nunique() == len(series)
    if is_unique and series.dtype in [np.int64, np.int32]:
        return "id"

    # 6. Phone
    phone_pattern = re.compile(r"^\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}$")
    if sum(1 for val in sample_values if phone_pattern.match(val)) / len(sample_values) > 0.8:
        return "phone"

    # 7. Basic numeric/categorical fallback
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "numeric"

    # High cardinality text vs Low cardinality category
    unique_ratio = series.nunique() / len(series) if len(series) > 0 else 0
    if unique_ratio < 0.2:
        return "categorical"

    return "text"


def clean_header_to_label(col_name: Any) -> str:
    """Convert messy snake_case or camelCase headers into high-quality human-readable labels."""
    col_str = str(col_name)
    # Split camelCase
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1 \2", col_str)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1 \2", s1)
    # Replace underscores and hyphens
    s3 = s2.replace("_", " ").replace("-", " ")
    # Capitalize words
    words = [w.capitalize() if w.lower() not in {"of", "the", "in", "and", "by", "with"} else w.lower() for w in s3.split()]
    label = " ".join(words)
    # Patch typical shorthand
    label = label.replace("Amt", "Amount").replace("Pct", "Percentage").replace("Id", "ID").replace("Sku", "SKU").replace("Qty", "Quantity")
    return label


def infer_semantic_metadata(col_name: Any, series: pd.Series) -> dict:
    """Infer semantic domain classification, inferred meaning, confidence score, and synonyms/aliases locally."""
    name_str = str(col_name)
    name_lower = name_str.lower()
    
    # 1. Timeline & Dates
    date_indicators = {"date", "time", "created", "updated", "year", "month", "day", "timestamp", "dt", "period"}
    if any(ind in name_lower for ind in date_indicators):
        return {
            "semantic_type": "date",
            "inferred_meaning": "Timeline record marking calendar dates or event timestamps for each record.",
            "confidence": 0.9,
            "aliases": ["date", "timeline", "timestamp", "period", "when", "time"]
        }
        
    # 2. Database ID Index (Checked early to override domain overlaps)
    id_indicators = {"id", "key", "code", "pk", "fk", "idx"}
    is_unique_key = False
    measure_words = {"revenue", "sales", "price", "amount", "cost", "spend", "salary", "qty", "quantity",
                     "count", "volume", "units", "total", "value", "score", "profit", "margin", "tax", "fee"}
    if len(series) > 1 and series.nunique() == len(series) and not any(w in name_lower for w in measure_words):
        if pd.api.types.is_integer_dtype(series.dtype):
            ordered = series.dropna().sort_values()
            # Sequential/near-sequential unique integers look like surrogate keys.
            is_unique_key = bool((ordered.diff().dropna() == 1).mean() > 0.9)
    if any(ind in name_lower for ind in id_indicators) or is_unique_key:
        return {
            "semantic_type": "id",
            "inferred_meaning": "Unique database index key or key reference column used to establish tables mapping.",
            "confidence": 0.9 if any(ind in name_lower for ind in id_indicators) else 0.7,
            "aliases": ["id", "key", "code", "index", "unique_id"]
        }
        
    # 3. Financial Metrics: Revenue / Sales / Currency
    rev_indicators = {"revenue", "sales", "price", "amount", "cost", "revenue", "spend", "usd", "eur", "amt", "salary", "spend", "invoice", "bill", "tax", "fee", "earn"}
    if any(ind in name_lower for ind in rev_indicators):
        return {
            "semantic_type": "revenue",
            "inferred_meaning": "Financial indicator representing revenue, costs, item prices, or transaction amounts in currency values.",
            "confidence": 0.85,
            "aliases": ["sales", "revenue", "income", "turnover", "spend", "amount", "cost", "price", "earnings"]
        }

    # 4. Quantities / Item Volumes
    qty_indicators = {"qty", "quantity", "count", "volume", "units", "number", "num", "vol"}
    if any(ind in name_lower for ind in qty_indicators):
        return {
            "semantic_type": "quantity",
            "inferred_meaning": "Numeric volume indicator tracking catalog item counts, transaction volumes, or physical units.",
            "confidence": 0.85,
            "aliases": ["quantity", "units", "count", "volume", "amount", "number"]
        }

    # 5. Email Address
    if "email" in name_lower or "mail" in name_lower:
        return {
            "semantic_type": "email",
            "inferred_meaning": "Primary customer email address for official correspondences and system accounts.",
            "confidence": 0.9,
            "aliases": ["email", "email address", "contact", "mail"]
        }

    # 6. Phone Numbers
    if "phone" in name_lower or "tel" in name_lower or "cell" in name_lower or "mobile" in name_lower:
        return {
            "semantic_type": "phone",
            "inferred_meaning": "Primary telephone contact details for account profiles or transactional shipping logs.",
            "confidence": 0.9,
            "aliases": ["phone", "phone number", "contact", "telephone", "mobile"]
        }

    # 7. Customer details
    cust_indicators = {"cust", "customer", "client", "buyer", "member", "user"}
    if any(ind in name_lower for ind in cust_indicators):
        return {
            "semantic_type": "customer",
            "inferred_meaning": "Customer identifying details such as names, accounts, or company reference records.",
            "confidence": 0.85,
            "aliases": ["customer", "client", "purchaser", "user", "buyer", "name"]
        }

    # 8. Invoice / Orders
    inv_indicators = {"invoice", "inv", "bill", "order", "receipt", "tx", "trans"}
    if any(ind in name_lower for ind in inv_indicators):
        return {
            "semantic_type": "invoice",
            "inferred_meaning": "Billing records, transaction receipts, invoice sequence indexes, or checkout identifiers.",
            "confidence": 0.85,
            "aliases": ["invoice", "order", "receipt", "bill", "transaction"]
        }

    # 9. Product / SKU Catalog
    prod_indicators = {"product", "prod", "item", "sku", "merchandise", "goods"}
    if any(ind in name_lower for ind in prod_indicators):
        return {
            "semantic_type": "product",
            "inferred_meaning": "Item descriptions, catalog specifications, stock catalog indicators, or merchandise types.",
            "confidence": 0.85,
            "aliases": ["product", "item", "sku", "merchandise", "goods"]
        }

    # 10. Percentages / Ratios
    pct_indicators = {"pct", "percent", "rate", "margin", "ratio"}
    if any(ind in name_lower for ind in pct_indicators):
        return {
            "semantic_type": "percentage",
            "inferred_meaning": "Percentage scale values, performance margins, or growth rates.",
            "confidence": 0.85,
            "aliases": ["percentage", "rate", "ratio", "margin"]
        }

    # 11. Numeric Measures
    if pd.api.types.is_numeric_dtype(series.dtype):
        return {
            "semantic_type": "numeric",
            "inferred_meaning": "General numeric metrics and numerical calculation factors.",
            "confidence": 0.6,
            "aliases": ["value", "metric", "number"]
        }

    # 12. Low Cardinality Groupings
    unique_ratio = series.nunique() / len(series) if len(series) > 0 else 0
    if unique_ratio < 0.2:
        return {
            "semantic_type": "categorical",
            "inferred_meaning": "Low cardinality discrete category indicators used to divide or group records.",
            "confidence": 0.6,
            "aliases": ["category", "group", "segment", "type"]
        }

    # 13. General Text Fallback
    return {
        "semantic_type": "text",
        "inferred_meaning": "General text content descriptions and general character strings.",
        "confidence": 0.5,
        "aliases": ["text", "description", "details", "info"]
    }



def heuristic_semantic_map(df: pd.DataFrame, previous: dict | None = None) -> dict[str, dict]:
    """Deterministic semantic map. Reuses prior (possibly AI-refined) labels for unchanged columns."""
    previous = previous or {}
    semantic_map: dict[str, dict] = {}
    for col in df.columns:
        key = str(col)
        if key in previous and isinstance(previous[key], dict):
            semantic_map[key] = previous[key]
            continue
        local_meta = infer_semantic_metadata(col, df[col])
        semantic_map[key] = {
            "name": key,
            "label": clean_header_to_label(col),
            "semantic_type": local_meta["semantic_type"],
            "inferred_meaning": local_meta["inferred_meaning"],
            "confidence": local_meta["confidence"],
            "aliases": local_meta["aliases"],
            "source": "heuristic",
        }
    return semantic_map


async def profile_columns_semantically(df: pd.DataFrame, table_name: str = "data", llm=None) -> dict[str, dict]:
    """Heuristic column semantics, optionally refined by an LLM (labels/aliases only — never numbers).

    ``llm`` must be an explicitly provided, request/workspace-scoped client.  When it
    is None or fails, the deterministic heuristic map is returned unchanged.
    """
    semantic_map = heuristic_semantic_map(df)
    if llm is None:
        return semantic_map

    target_columns = list(df.columns)[:30]
    schema_summary = []
    for col in target_columns:
        sample_vals = [str(v)[:60] for v in df[col].dropna().head(3).tolist()]
        schema_summary.append({
            "name": str(col),
            "dtype": str(df[col].dtype),
            "sample_values": sample_vals,
        })

    prompt = (
        "Analyze these spreadsheet columns and describe each one's business meaning.\n\n"
        f"Columns (max 30):\n{json.dumps(schema_summary, indent=2)}\n\n"
        "Return ONLY a JSON object mapping each column name to "
        '{"label": str, "semantic_type": one of revenue|quantity|date|currency|percentage|id|customer|invoice|product|email|phone|text|numeric|categorical, '
        '"inferred_meaning": str, "aliases": [str]}. Do not include any numbers or statistics.'
    )
    try:
        raw_resp = await llm.generate(
            prompt,
            system="You are a semantic schema cataloger. Output only a valid JSON object.",
            json_mode=True,
        )
        clean = re.sub(r"```(?:json)?\s*", "", raw_resp).replace("```", "").strip()
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            for col_name, meta in parsed.items():
                if col_name in semantic_map and isinstance(meta, dict):
                    entry = semantic_map[col_name]
                    entry["label"] = str(meta.get("label") or entry["label"])[:120]
                    entry["semantic_type"] = str(meta.get("semantic_type") or entry["semantic_type"])[:40]
                    entry["inferred_meaning"] = str(meta.get("inferred_meaning") or entry["inferred_meaning"])[:300]
                    aliases = meta.get("aliases", [])
                    if isinstance(aliases, list):
                        entry["aliases"] = sorted({*entry["aliases"], *[str(a).lower()[:40] for a in aliases[:12]]})
                    entry["source"] = "ai"
    except Exception as e:
        logger.warning("AI column profiling unavailable (%s); using heuristic semantics.", e)
    return semantic_map


def profile_dataset(df: pd.DataFrame) -> dict:
    """Profile dataset and compute statistical metadata (outliers, correlations, nulls, duplicates)."""
    row_count = len(df)
    col_count = len(df.columns)
    duplicate_count = int(df.duplicated().sum())

    columns_meta = []
    numeric_cols = []
    correlation_list = []
    outlier_alerts = []

    # Profile columns
    for col in df.columns:
        series = df[col]
        null_count = int(series.isnull().sum())
        null_pct = round((null_count / row_count) * 100, 2) if row_count > 0 else 0.0
        unique_count = int(series.nunique())
        local_meta = infer_semantic_metadata(col, series)
        label = clean_header_to_label(col)

        col_info = {
            "name": col,
            "label": label,
            "dtype": str(series.dtype),
            "semantic_type": local_meta["semantic_type"],
            "inferred_meaning": local_meta["inferred_meaning"],
            "confidence": local_meta["confidence"],
            "aliases": local_meta["aliases"],
            "null_count": null_count,
            "null_pct": null_pct,
            "unique_count": unique_count,
        }

        # Check numeric stats and outliers
        if pd.api.types.is_numeric_dtype(series.dtype):
            numeric_cols.append(col)
            clean_series = series.dropna()
            if not clean_series.empty:
                min_val = float(clean_series.min())
                max_val = float(clean_series.max())
                mean_val = float(clean_series.mean())
                std_val = float(clean_series.std()) if len(clean_series) > 1 else 0.0
                col_info["stats"] = {"min": min_val, "max": max_val, "mean": mean_val, "std": std_val}

                # Outliers using IQR
                q25, q75 = np.percentile(clean_series, [25, 75])
                iqr = q75 - q25
                lower_bound = q25 - 1.5 * iqr
                upper_bound = q75 + 1.5 * iqr
                outliers = clean_series[(clean_series < lower_bound) | (clean_series > upper_bound)]
                outlier_count = len(outliers)

                if outlier_count > 0:
                    col_info["outlier_count"] = outlier_count
                    outlier_alerts.append({
                        "column": col,
                        "label": label,
                        "count": outlier_count,
                        "pct": round((outlier_count / row_count) * 100, 2),
                    })

        columns_meta.append(col_info)

    # Pearson Correlation Matrix (only if we have multiple numeric columns)
    if len(numeric_cols) > 1:
        corr_matrix = df[numeric_cols].corr(method="pearson")
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                col1 = numeric_cols[i]
                col2 = numeric_cols[j]
                val = corr_matrix.loc[col1, col2]
                if not pd.isna(val) and abs(val) >= 0.7:
                    correlation_list.append({
                        "col1": col1,
                        "label1": clean_header_to_label(col1),
                        "col2": col2,
                        "label2": clean_header_to_label(col2),
                        "coefficient": round(float(val), 3),
                    })

    # Sort correlation by strength
    correlation_list.sort(key=lambda x: abs(x["coefficient"]), reverse=True)

    return {
        "row_count": row_count,
        "col_count": col_count,
        "duplicate_count": duplicate_count,
        "columns": columns_meta,
        "correlations": correlation_list[:5],  # Top 5 correlations
        "outliers": outlier_alerts,
    }



def _safe_name(col: Any) -> str:
    return str(col).replace('"', '""')


def build_insights(df: pd.DataFrame, table_name: str = "data") -> list[dict]:
    """Deterministic, data-grounded insights.

    Every number shown is computed from the DataFrame here.  Nothing is
    extrapolated or invented (the previous version shipped a hard-coded
    "+7.5% growth" forecast and LLM-written metrics that were never verified).
    """
    if df is None or df.empty:
        return [{
            "id": "stat_summary_dataset",
            "type": "statistical",
            "title": "Dataset is empty",
            "description": "The table contains no data rows.",
            "severity": "warning",
            "metric": "0 Rows",
            "sql": f"SELECT COUNT(*) AS row_count FROM {table_name}",
            "chart_type": None,
            "verified": True,
        }]

    profile = profile_dataset(df)
    insights: list[dict] = []
    row_count = profile["row_count"]

    numeric_cols = [c for c in profile["columns"] if "stats" in c and c["semantic_type"] != "id"]
    cat_cols = [c for c in profile["columns"] if c["semantic_type"] == "categorical"]
    date_cols = [c for c in profile["columns"] if c["semantic_type"] in {"datetime", "date"}]

    # A. Distribution of key numeric measures (computed)
    for c in numeric_cols[:2]:
        name, lbl, st = c["name"], c["label"], c["stats"]
        q = _safe_name(name)
        insights.append({
            "id": f"stat_summary_{name}",
            "type": "statistical",
            "title": f"Distribution of {lbl}",
            "description": (
                f"Across {row_count - c['null_count']:,} non-empty values, '{lbl}' averages {st['mean']:,.2f} "
                f"(min {st['min']:,.2f}, max {st['max']:,.2f}, standard deviation {st['std']:,.2f})."
            ),
            "severity": "info",
            "metric": f"Mean: {st['mean']:,.2f}",
            "sql": f'SELECT AVG("{q}") AS average, MIN("{q}") AS minimum, MAX("{q}") AS maximum, STDDEV("{q}") AS std_dev FROM {table_name}',
            "chart_type": "bar",
            "verified": True,
        })

    # B. Category concentration (computed share of the largest category)
    for c in cat_cols[:1]:
        name, lbl = c["name"], c["label"]
        counts = df[name].value_counts(dropna=True)
        if counts.empty:
            continue
        top_val, top_n = counts.index[0], int(counts.iloc[0])
        share = top_n / max(int(counts.sum()), 1) * 100
        q = _safe_name(name)
        insights.append({
            "id": f"stat_dist_{name}",
            "type": "statistical",
            "title": f"Largest '{lbl}' category is {top_val}",
            "description": f"'{top_val}' accounts for {top_n:,} of {int(counts.sum()):,} rows ({share:.1f}%) across {len(counts)} categories.",
            "severity": "info",
            "metric": f"{share:.1f}% share",
            "sql": f'SELECT "{q}" AS category, COUNT(*) AS frequency FROM {table_name} GROUP BY 1 ORDER BY 2 DESC LIMIT 5',
            "chart_type": "pie",
            "verified": True,
        })

    # C. Month-over-month change between the last two COMPLETE months (computed)
    if date_cols and numeric_cols:
        dcol, ncol = date_cols[0]["name"], numeric_cols[0]["name"]
        try:
            dates = pd.to_datetime(df[dcol], errors="coerce")
            values = pd.to_numeric(df[ncol], errors="coerce")
            frame = pd.DataFrame({"d": dates, "v": values}).dropna()
            if not frame.empty:
                monthly = frame.set_index("d")["v"].resample("MS").sum(min_count=1)
                last_date = frame["d"].max()
                month_end = (last_date + pd.offsets.MonthEnd(0)).normalize()
                if last_date.normalize() < month_end:
                    monthly = monthly.iloc[:-1]  # drop the incomplete final month
                monthly = monthly.dropna()
                if len(monthly) >= 2 and monthly.iloc[-2] != 0:
                    prev, last = float(monthly.iloc[-2]), float(monthly.iloc[-1])
                    change = (last - prev) / abs(prev) * 100
                    qd, qn = _safe_name(dcol), _safe_name(ncol)
                    insights.append({
                        "id": f"trend_timeline_{dcol}_{ncol}",
                        "type": "trend",
                        "title": f"{numeric_cols[0]['label']} changed {change:+.1f}% month over month",
                        "description": (
                            f"Total {numeric_cols[0]['label']} was {last:,.2f} in {monthly.index[-1]:%b %Y} versus "
                            f"{prev:,.2f} in {monthly.index[-2]:%b %Y} (last two complete months)."
                        ),
                        "severity": "success" if change >= 0 else "warning",
                        "metric": f"{change:+.1f}% MoM",
                        "sql": f'SELECT DATE_TRUNC(\'month\', TRY_CAST("{qd}" AS TIMESTAMP)) AS month, SUM("{qn}") AS total FROM {table_name} GROUP BY 1 ORDER BY 1',
                        "chart_type": "line",
                        "verified": True,
                    })
        except Exception as exc:
            logger.debug("Trend insight skipped: %s", exc)

    # D. Data quality (computed)
    if profile["duplicate_count"] > 0:
        dup_pct = round(profile["duplicate_count"] / row_count * 100, 1)
        insights.append({
            "id": "quality_duplicates",
            "type": "quality",
            "title": "Duplicate rows detected",
            "description": f"{profile['duplicate_count']:,} rows ({dup_pct}%) are exact duplicates of another row.",
            "severity": "error" if dup_pct > 5.0 else "warning",
            "metric": f"{profile['duplicate_count']:,} Dups",
            "sql": f"SELECT *, COUNT(*) AS duplicates_count FROM {table_name} GROUP BY ALL HAVING COUNT(*) > 1",
            "chart_type": None,
            "verified": True,
        })
    for c in sorted((c for c in profile["columns"] if c["null_count"] > 0), key=lambda c: -c["null_count"])[:2]:
        q = _safe_name(c["name"])
        insights.append({
            "id": f"quality_nulls_{c['name']}",
            "type": "quality",
            "title": f"Missing values in {c['label']}",
            "description": f"'{c['label']}' is empty in {c['null_count']:,} rows ({c['null_pct']}%).",
            "severity": "error" if c["null_pct"] > 20.0 else "warning",
            "metric": f"{c['null_pct']}% Nulls",
            "sql": f'SELECT COUNT(*) - COUNT("{q}") AS null_records FROM {table_name}',
            "chart_type": None,
            "verified": True,
        })
    for o in profile["outliers"][:2]:
        q = _safe_name(o["column"])
        insights.append({
            "id": f"quality_outliers_{o['column']}",
            "type": "quality",
            "title": f"Outliers in {o['label']}",
            "description": f"{o['count']:,} values ({o['pct']}%) fall outside 1.5×IQR of '{o['label']}'.",
            "severity": "warning",
            "metric": f"{o['count']:,} Outliers",
            "sql": (
                f'WITH b AS (SELECT QUANTILE_CONT("{q}", 0.25) AS q1, QUANTILE_CONT("{q}", 0.75) AS q3 FROM {table_name}) '
                f'SELECT t.* FROM {table_name} t, b WHERE t."{q}" < q1 - 1.5*(q3-q1) OR t."{q}" > q3 + 1.5*(q3-q1)'
            ),
            "chart_type": "scatter",
            "verified": True,
        })

    # E. Relationships (computed correlation, top contributor)
    for corr in profile["correlations"][:2]:
        coef = corr["coefficient"]
        insights.append({
            "id": f"relation_corr_{corr['col1']}_{corr['col2']}",
            "type": "relationship",
            "title": f"{corr['label1']} and {corr['label2']} are correlated",
            "description": f"Pearson correlation is {coef:.3f}. Correlation does not imply causation.",
            "severity": "info",
            "metric": f"{coef:+.2f} Corr",
            "sql": f'SELECT CORR("{_safe_name(corr["col1"])}", "{_safe_name(corr["col2"])}") AS correlation FROM {table_name}',
            "chart_type": "scatter",
            "verified": True,
        })
    if cat_cols and numeric_cols:
        ccol, ncol = cat_cols[0]["name"], numeric_cols[0]["name"]
        grouped = pd.to_numeric(df[ncol], errors="coerce").groupby(df[ccol]).sum(min_count=1).dropna()
        total = float(grouped.sum()) if not grouped.empty else 0.0
        if not grouped.empty and total != 0:
            top = grouped.sort_values(ascending=False)
            share = float(top.iloc[0]) / total * 100
            insights.append({
                "id": f"relation_groupby_{ccol}_{ncol}",
                "type": "relationship",
                "title": f"{top.index[0]} leads {numeric_cols[0]['label']}",
                "description": (
                    f"'{top.index[0]}' contributes {float(top.iloc[0]):,.2f} of total {total:,.2f} "
                    f"{numeric_cols[0]['label']} ({share:.1f}%) when grouped by {cat_cols[0]['label']}."
                ),
                "severity": "info",
                "metric": f"{share:.1f}% of total",
                "sql": f'SELECT "{_safe_name(ccol)}" AS category, SUM("{_safe_name(ncol)}") AS total FROM {table_name} GROUP BY 1 ORDER BY 2 DESC LIMIT 5',
                "chart_type": "bar",
                "verified": True,
            })

    if not insights:
        insights.append({
            "id": "stat_summary_dataset",
            "type": "statistical",
            "title": "Dataset loaded",
            "description": f"The table contains {row_count:,} rows and {profile['col_count']} columns.",
            "severity": "info",
            "metric": f"{row_count:,} Rows",
            "sql": f"SELECT COUNT(*) AS row_count FROM {table_name}",
            "chart_type": None,
            "verified": True,
        })
    return insights


async def generate_insights(df: pd.DataFrame, table_name: str = "data") -> list[dict]:
    """Async compatibility wrapper around :func:`build_insights` (deterministic)."""
    return build_insights(df, table_name)
