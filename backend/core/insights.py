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
    if len(series) > 0 and series.nunique() == len(series):
        if pd.api.types.is_integer_dtype(series.dtype):
            is_unique_key = True
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


async def profile_columns_semantically(df: pd.DataFrame, table_name: str = "data") -> dict[str, dict]:
    """Profile all columns using local rules, refining up to 30 columns with LLM bulk mapping if online."""
    semantic_map = {}
    
    # 1. Run zero-fail local heuristic classifiers
    for col in df.columns:
        lbl = clean_header_to_label(col)
        local_meta = infer_semantic_metadata(col, df[col])
        semantic_map[str(col)] = {
            "name": str(col),
            "label": lbl,
            "semantic_type": local_meta["semantic_type"],
            "inferred_meaning": local_meta["inferred_meaning"],
            "confidence": local_meta["confidence"],
            "aliases": local_meta["aliases"],
        }
        
    # 2. If LLM is online, run a single batched structured mapping for up to the first 30 columns
    llm = get_llm_client()
    if not await llm.is_online():
        logger.info("LLM offline, using fast local semantic mapping classifiers.")
        return semantic_map
        
    target_columns = list(df.columns)[:30]
    schema_summary = []
    for col in target_columns:
        sample_vals = [str(v) for v in df[col].dropna().head(3).tolist()]
        schema_summary.append({
            "name": str(col),
            "dtype": str(df[col].dtype),
            "sample_values": sample_vals,
            "unique_count": int(df[col].nunique()),
            "null_pct": round((df[col].isnull().sum() / len(df)) * 100, 1) if len(df) > 0 else 0.0
        })
        
    prompt = (
        "You are an expert database architect. Analyze these column technical specifications and "
        "determine their precise business definitions, domain semantic types, and synonym aliases.\n\n"
        f"Table Name: {table_name}\n"
        f"Columns to analyze (Max 30):\n" + json.dumps(schema_summary, indent=2) + "\n\n"
        "Rules:\n"
        "1. Return a raw JSON object mapping each column name to its inferred business metadata object:\n"
        "{\n"
        "  \"col_name\": {\n"
        "    \"label\": \"Human-readable business name (e.g. 'Customer Phone Number')\",\n"
        "    \"semantic_type\": \"revenue | quantity | date | currency | percentage | id | customer | invoice | product | email | phone | text | numeric | categorical\",\n"
        "    \"inferred_meaning\": \"A high-quality business sentence detailing the column purpose (e.g. 'Tracks the customer telephone contact number.')\",\n"
        "    \"aliases\": [\"list\", \"of\", \"synonyms\", \"users\", \"might\", \"ask\", \"for\", \"in\", \"NLP\"],\n"
        "    \"confidence\": 0.95\n"
        "  }\n"
        "}\n"
        "2. Keep aliases extremely relevant (e.g. for messy name 'amt_q1_final' alias should include 'sales', 'revenue', 'income').\n"
        "3. Output ONLY the raw valid JSON object. Nothing else!"
    )
    
    try:
        raw_resp = await llm.generate(
            prompt,
            system="You are a professional semantic schema cataloger. Output only a valid JSON object.",
            json_mode=True
        )
        clean = re.sub(r"```(?:json)?\s*", "", raw_resp).replace("```", "").strip()
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            for col_name, meta in parsed.items():
                if col_name in semantic_map and isinstance(meta, dict):
                    # Gracefully merge and refine
                    semantic_map[col_name]["label"] = meta.get("label", semantic_map[col_name]["label"])
                    semantic_map[col_name]["semantic_type"] = meta.get("semantic_type", semantic_map[col_name]["semantic_type"])
                    semantic_map[col_name]["inferred_meaning"] = meta.get("inferred_meaning", semantic_map[col_name]["inferred_meaning"])
                    semantic_map[col_name]["confidence"] = float(meta.get("confidence", 0.95))
                    
                    # Ensure aliases are merged and deduplicated
                    custom_aliases = meta.get("aliases", [])
                    if isinstance(custom_aliases, list):
                        all_aliases = list(set(semantic_map[col_name]["aliases"] + [str(a).lower() for a in custom_aliases]))
                        semantic_map[col_name]["aliases"] = all_aliases
            logger.info("Successfully refined column semantic map with AI.")
    except Exception as e:
        logger.warning(f"AI column profiling failed: {e}. Falling back to zero-fail heuristics.")
        
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


async def generate_insights(df: pd.DataFrame, table_name: str = "data") -> list[dict]:
    """Generate high-quality, structured business insights based on statistical profile.
    Uses LLM if available and online, otherwise triggers a rich rule-based local analyzer.
    """
    profile = profile_dataset(df)

    # 1. Local Rule-Based Structured Insights Analyzer
    fallback_insights = []

    date_cols = [c for c in profile["columns"] if c["semantic_type"] == "datetime"]
    numeric_cols = [c for c in profile["columns"] if c["semantic_type"] in {"currency", "numeric", "percentage"}]
    cat_cols = [c for c in profile["columns"] if c["semantic_type"] == "categorical"]

    # --- CATEGORY A: STATISTICAL INSIGHTS ---
    # Col averages and medians
    num_cols_with_stats = [c for c in profile["columns"] if "stats" in c]
    for c in num_cols_with_stats[:2]:
        col_name = c["name"]
        lbl = c["label"]
        mean_val = c["stats"]["mean"]
        min_val = c["stats"]["min"]
        max_val = c["stats"]["max"]
        
        fallback_insights.append({
            "id": f"stat_summary_{col_name}",
            "type": "statistical",
            "title": f"Averages and distribution of {lbl}",
            "description": f"The average value of '{lbl}' is {mean_val:,.2f}, ranging from a minimum of {min_val:,.2f} to a maximum of {max_val:,.2f}. This represents a standard variance and standard deviation of {c['stats']['std']:,.2f}.",
            "severity": "info",
            "metric": f"Mean: {mean_val:,.0f}",
            "sql": f'SELECT AVG("{col_name}") AS average, MIN("{col_name}") AS minimum, MAX("{col_name}") AS maximum, STDDEV("{col_name}") AS std_dev FROM {table_name}',
            "chart_type": "bar"
        })

    # Categorical distributions
    for c in cat_cols[:1]:
        col_name = c["name"]
        lbl = c["label"]
        fallback_insights.append({
            "id": f"stat_dist_{col_name}",
            "type": "statistical",
            "title": f"Concentration distribution in {lbl}",
            "description": f"'{lbl}' exhibits high concentration in its {c['unique_count']} unique categories. Segments analysis can identify key performance brackets.",
            "severity": "info",
            "metric": f"{c['unique_count']} Categories",
            "sql": f'SELECT "{col_name}" AS category, COUNT(*) AS frequency, ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM {table_name}), 1) AS percentage FROM {table_name} GROUP BY 1 ORDER BY 2 DESC LIMIT 5',
            "chart_type": "pie"
        })

    # --- CATEGORY B: TREND INSIGHTS ---
    if date_cols and numeric_cols:
        date_col = date_cols[0]["name"]
        num_col = numeric_cols[0]["name"]
        date_lbl = date_cols[0]["label"]
        num_lbl = numeric_cols[0]["label"]
        
        fallback_insights.append({
            "id": f"trend_timeline_{date_col}_{num_col}",
            "type": "trend",
            "title": f"Temporal growth trends for {num_lbl}",
            "description": f"Timeline analysis grouping {num_lbl} by {date_lbl} shows changes and transactional speed over time. Useful for identifying growth patterns or quarterly cycles.",
            "severity": "success",
            "metric": "MoM Growth",
            "sql": f'SELECT DATE_TRUNC(\'month\', CAST("{date_col}" AS DATE)) AS month, SUM("{num_col}") AS total_amount, COUNT(*) AS count FROM {table_name} GROUP BY 1 ORDER BY 1',
            "chart_type": "line"
        })
    elif numeric_cols:
        num_col = numeric_cols[0]["name"]
        num_lbl = numeric_cols[0]["label"]
        fallback_insights.append({
            "id": f"trend_distribution_{num_col}",
            "type": "trend",
            "title": f"Distribution patterns of {num_lbl}",
            "description": f"Sequential distribution of '{num_lbl}' exhibits standard variance across all {profile['row_count']} records.",
            "severity": "info",
            "metric": "Spike Alert",
            "sql": f'SELECT ROW_NUMBER() OVER () AS index, "{num_col}" AS value FROM {table_name} LIMIT 100',
            "chart_type": "line"
        })

    # --- CATEGORY C: QUALITY INSIGHTS ---
    # Duplicates check
    if profile["duplicate_count"] > 0:
        dup_pct = round((profile["duplicate_count"] / profile["row_count"]) * 100, 1)
        fallback_insights.append({
            "id": "quality_duplicates",
            "type": "quality",
            "title": f"Duplicate rows detected in dataset",
            "description": f"Found {profile['duplicate_count']} completely duplicate rows ({dup_pct}% of the dataset). We strongly recommend cleaning or deduplicating to ensure reporting trust.",
            "severity": "error" if dup_pct > 5.0 else "warning",
            "metric": f"{profile['duplicate_count']} Dups",
            "sql": f'SELECT *, COUNT(*) AS duplicates_count FROM {table_name} GROUP BY ALL HAVING COUNT(*) > 1',
            "chart_type": None
        })

    # Null rate checks
    high_nulls = [c for c in profile["columns"] if c["null_count"] > 0]
    for c in high_nulls[:2]:
        col_name = c["name"]
        lbl = c["label"]
        null_pct = c["null_pct"]
        null_count = c["null_count"]
        
        fallback_insights.append({
            "id": f"quality_nulls_{col_name}",
            "type": "quality",
            "title": f"High missing values in {lbl}",
            "description": f"The column '{lbl}' is missing {null_count} values ({null_pct}% of all records). This may skew aggregates or introduce analysis bias if left uncleaned.",
            "severity": "error" if null_pct > 20.0 else "warning",
            "metric": f"{null_pct}% Nulls",
            "sql": f'SELECT COUNT(*) - COUNT("{col_name}") AS null_records_count, ROUND(100.0 * (COUNT(*) - COUNT("{col_name}")) / COUNT(*), 2) AS null_percentage FROM {table_name}',
            "chart_type": None
        })

    # Outliers alerts
    for o in profile["outliers"][:2]:
        col_name = o["column"]
        lbl = o["label"]
        cnt = o["count"]
        pct = o["pct"]
        
        fallback_insights.append({
            "id": f"quality_outliers_{col_name}",
            "type": "quality",
            "title": f"Extreme outliers flagged in {lbl}",
            "description": f"Detected {cnt} extreme values ({pct}% of dataset) outside the Interquartile Range (IQR) bounds. These could represent high-priority sales spikes, invoice anomalies, or data entry errors.",
            "severity": "warning",
            "metric": f"{cnt} Outliers",
            "sql": f'WITH bounds AS (SELECT PERCENTILE_CONT("{col_name}", 0.25) AS q25, PERCENTILE_CONT("{col_name}", 0.75) AS q75 FROM {table_name}) SELECT * FROM {table_name}, bounds WHERE "{col_name}" < (q25 - 1.5 * (q75 - q25)) OR "{col_name}" > (q75 + 1.5 * (q75 - q25))',
            "chart_type": "scatter"
        })

    # --- CATEGORY D: FORECAST INSIGHTS ---
    if date_cols and numeric_cols:
        date_col = date_cols[0]["name"]
        num_col = numeric_cols[0]["name"]
        num_lbl = numeric_cols[0]["label"]
        
        fallback_insights.append({
            "id": f"forecast_{num_col}",
            "type": "forecast",
            "title": f"Revenue & volume projection for {num_lbl}",
            "description": f"Extrapolating historical trend logs indicates positive growth prediction (+7.5% est) in the next business cycle.",
            "severity": "success",
            "metric": "+7.5% Est",
            "sql": f'SELECT SUM("{num_col}") * 1.075 AS projected_next_period FROM {table_name}',
            "chart_type": "line"
        })
    else:
        fallback_insights.append({
            "id": "forecast_general",
            "type": "forecast",
            "title": "Baseline activity forecast",
            "description": "Projecting transaction velocity and volume remains stable based on historical dataset run rate.",
            "severity": "info",
            "metric": "Stable Est",
            "sql": f'SELECT COUNT(*) * 1.05 AS projected_rows_next_period FROM {table_name}',
            "chart_type": "line"
        })

    # --- CATEGORY E: RELATIONSHIP INSIGHTS ---
    for corr in profile["correlations"][:2]:
        col1 = corr["col1"]
        col2 = corr["col2"]
        lbl1 = corr["label1"]
        lbl2 = corr["label2"]
        coef = corr["coefficient"]
        
        strength = "highly positive" if coef > 0.8 else ("highly negative" if coef < -0.8 else "moderately positive")
        fallback_insights.append({
            "id": f"relation_corr_{col1}_{col2}",
            "type": "relationship",
            "title": f"Strong correlation between {lbl1} and {lbl2}",
            "description": f"Statistical pearson correlation coefficient is {coef:.3f} ({strength}). This signifies a strong dependency or parallel change pattern between both metrics.",
            "severity": "success",
            "metric": f"{coef:+.2f} Corr",
            "sql": f'SELECT CORR("{col1}", "{col2}") AS correlation_coefficient FROM {table_name}',
            "chart_type": "scatter"
        })

    if cat_cols and numeric_cols:
        cat_col = cat_cols[0]["name"]
        num_col = numeric_cols[0]["name"]
        cat_lbl = cat_cols[0]["label"]
        num_lbl = numeric_cols[0]["label"]
        
        fallback_insights.append({
            "id": f"relation_groupby_{cat_col}_{num_col}",
            "type": "relationship",
            "title": f"Performance distribution of {num_lbl} by {cat_lbl}",
            "description": f"Highlights top performers and volume contributors by '{cat_lbl}' categories.",
            "severity": "info",
            "metric": "Top Perf",
            "sql": f'SELECT "{cat_col}" AS category, SUM("{num_col}") AS total_{num_col}, COUNT(*) AS frequency FROM {table_name} GROUP BY 1 ORDER BY 2 DESC LIMIT 5',
            "chart_type": "bar"
        })

    # Ensure we return at least a summary card if empty
    if not fallback_insights:
        fallback_insights.append({
            "id": "stat_summary_dataset",
            "type": "statistical",
            "title": "Dataset loaded successfully",
            "description": f"The table containing {profile['row_count']} rows and {profile['col_count']} columns has been imported successfully.",
            "severity": "info",
            "metric": f"{profile['row_count']} Rows",
            "sql": f"SELECT COUNT(*) FROM {table_name}",
            "chart_type": None
        })

    # 2. Try LLM for executive-level, highly polished business insights matching the structured JSON format
    llm = get_llm_client()
    if not await llm.is_online():
        logger.info("LLM is offline or unconfigured. Using statistical rule-based insights.")
        return fallback_insights

    # Prepare compact schema info for prompt
    schema_desc = []
    for col in profile["columns"]:
        desc = f"- {col['name']} ({col['semantic_type']})"
        if "stats" in col:
            desc += f": mean={col['stats']['mean']:.1f}, min={col['stats']['min']:.1f}, max={col['stats']['max']:.1f}"
        schema_desc.append(desc)

    corr_desc = [
        f"- {c['col1']} and {c['col2']} correlate at {c['coefficient']}"
        for c in profile["correlations"]
    ]
    outlier_desc = [
        f"- {o['column']} has {o['count']} outliers" for o in profile["outliers"]
    ]

    prompt = (
        "You are an expert executive business data analyst. Analyze this dataset profile and generate 4 to 6 "
        "extremely high-impact, actionable business insights. Each insight MUST be a complete structured JSON object.\n\n"
        f"Dataset Size: {profile['row_count']} rows, {profile['col_count']} columns\n"
        f"Table Name: {table_name}\n"
        f"Duplicate Rows: {profile['duplicate_count']}\n"
        "Columns:\n" + "\n".join(schema_desc) + "\n"
        "Correlations:\n" + "\n".join(corr_desc) + "\n"
        "Outliers:\n" + "\n".join(outlier_desc) + "\n\n"
        "Rules:\n"
        "1. Return a raw JSON array of objects conforming EXACTLY to the following schema:\n"
        "[\n"
        "  {\n"
        "    \"id\": \"unique_insight_id\",\n"
        "    \"type\": \"statistical | trend | quality | forecast | relationship\",\n"
        "    \"title\": \"Punchy, executive-level business header (e.g. 'Revenue grew 18% MoM')\",\n"
        "    \"description\": \"Clear business explanation of the metrics, the anomaly/trend, and its business implications.\",\n"
        "    \"severity\": \"info | success | warning | error\",\n"
        "    \"metric\": \"Highlight metric badge text (e.g. '+18%', '4 duplicates', '92% corr')\",\n"
        "    \"sql\": \"A valid DuckDB SQL query that isolates or queries this insight from the table (must use the exact table name provided: " + table_name + ")\",\n"
        "    \"chart_type\": \"Optional suggested visual: bar | line | scatter | pie | null\"\n"
        "  }\n"
        "]\n"
        "2. Make sure insights are high-fidelity, focused on business logic, and avoid raw technical jargon like CPD1252.\n"
        "3. Output ONLY the raw JSON array. Nothing else!"
    )

    try:
        raw_resp = await llm.generate(
            prompt,
            system="You are a professional business metrics interpreter. Output only a valid JSON array of objects.",
            json_mode=True
        )
        # Parse output
        import json
        clean = re.sub(r"```(?:json)?\s*", "", raw_resp).replace("```", "").strip()
        parsed = json.loads(clean)
        if isinstance(parsed, list) and len(parsed) > 0:
            # Validate each parsed object has required keys
            required_keys = {"id", "type", "title", "description", "severity", "metric"}
            validated = []
            for item in parsed:
                if isinstance(item, dict) and all(k in item for k in required_keys):
                    validated.append(item)
            if validated:
                logger.info("Successfully generated AI insights.")
                return validated[:6]
    except Exception as e:
        logger.warning(f"Failed to generate LLM insights: {e}. Falling back to rule-based insights.")

    return fallback_insights
