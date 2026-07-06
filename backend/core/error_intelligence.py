"""
error_intelligence.py — Deterministic error diagnosis engine for DataPilot.

Converts every raw technical exception or data quality issue into a professional,
human-readable diagnostic with:
  - Exact affected columns / row ranges
  - Repair suggestions
  - Severity classification
  - Schema warnings on upload

100% deterministic — zero LLM calls.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("datapilot.error_intelligence")


class IntelligentException(Exception):
    """Custom exception containing structured diagnostic details."""
    def __init__(self, err_dict: dict):
        self.err_dict = err_dict
        super().__init__(err_dict.get("message", "An error occurred."))


# ── Data structure ─────────────────────────────────────────────────────────────

def _make_error(
    code: str,
    title: str,
    message: str,
    suggestions: list[str] | None = None,
    details: list[str] | None = None,
    severity: str = "error",
    affected_column: str | None = None,
    affected_rows: tuple[int, int] | None = None,
    recovery: dict | None = None,
) -> dict:
    """Build a standard IntelligentError dict."""
    return {
        "code": code,
        "title": title,
        "message": message,
        "suggestions": suggestions or [],
        "details": details or [],
        "severity": severity,
        "affected_column": affected_column,
        "affected_rows": affected_rows,
        "recovery": recovery,
    }


# ── Upload / parse diagnostics ─────────────────────────────────────────────────

def diagnose_upload_error(exc: Exception, filename: str, raw_bytes: bytes | None = None) -> dict:
    """
    Convert a file upload / parse failure into a professional diagnostic.
    Inspects the exception message for common patterns (encoding, size, format).
    """
    msg = str(exc).lower()
    size_mb = round(len(raw_bytes) / (1024 * 1024), 1) if raw_bytes else 0
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    # ── Encoding errors ──
    if any(k in msg for k in ("codec", "encode", "decode", "utf", "unicode", "charmap")):
        encoding = "Windows-1252 (CP1252)" if "cp1252" in msg or "charmap" in msg else "an unknown encoding"
        return _make_error(
            code="ENCODING_ERROR",
            title="Character encoding issue",
            message=(
                f"'{filename}' could not be read because it uses {encoding}. "
                f"This happens when the file contains accented characters or special symbols "
                f"saved outside UTF-8."
            ),
            suggestions=[
                "Re-save the file from Excel as 'CSV UTF-8 (Comma delimited)'.",
                "Open the file in Notepad++, go to Encoding → Convert to UTF-8, then save.",
                "If the file is Excel (.xlsx), upload it directly instead of exporting to CSV.",
            ],
            severity="error",
        )

    # ── File too large ──
    if "too large" in msg or "max" in msg:
        return _make_error(
            code="FILE_TOO_LARGE",
            title="File exceeds size limit",
            message=(
                f"'{filename}' is {size_mb} MB, which exceeds the 50 MB upload limit. "
                f"Large files slow down in-browser analysis and may exceed available memory."
            ),
            suggestions=[
                "Filter the file to the relevant date range before uploading.",
                "Split into multiple files by year, region, or category.",
                "Remove unused columns that are not needed for your analysis.",
                "Compress repeated text columns (e.g., encode categories as integers).",
            ],
            severity="error",
        )

    # ── Empty file ──
    if "empty" in msg or (raw_bytes is not None and len(raw_bytes) == 0):
        return _make_error(
            code="EMPTY_FILE",
            title="File appears to be empty",
            message=f"'{filename}' was uploaded but contains no data rows.",
            suggestions=[
                "Check that the file was saved before uploading.",
                "If exported from a system, ensure the export completed successfully.",
            ],
            severity="error",
        )

    # ── Unsupported format ──
    if "unsupported" in msg or "extension" in msg or "format" in msg:
        return _make_error(
            code="UNSUPPORTED_FORMAT",
            title="Unsupported file",
            message=(
                f"'.{ext}' files are not supported. DataPilot accepts CSV (.csv), "
                f"Excel (.xlsx), and legacy Excel (.xls) files."
            ),
            suggestions=[
                "Export your data as CSV from your source system.",
                "If using Google Sheets, go to File → Download → CSV.",
                "If using a database, export a query result as CSV.",
            ],
            severity="error",
        )

    # ── Excel format mismatch ──
    if "openpyxl" in msg or "xlrd" in msg or "magic" in msg or "excel" in msg:
        return _make_error(
            code="EXCEL_FORMAT_CORRUPT",
            title="Excel file could not be read",
            message=(
                f"'{filename}' could not be opened as an Excel workbook. "
                f"The file may be password-protected, corrupted, or saved in an incompatible format."
            ),
            suggestions=[
                "Open the file in Excel and re-save it as 'Excel Workbook (.xlsx)'.",
                "Remove any sheet password protection before uploading.",
                "If the file is from an older system, try exporting it as CSV instead.",
            ],
            severity="error",
        )

    # ── Parsing fallback ──
    return _make_error(
        code="PARSE_ERROR",
        title="File could not be parsed",
        message=(
            f"'{filename}' could not be processed: {str(exc)[:200]}. "
            f"The file structure may be irregular or contain unexpected formatting."
        ),
        suggestions=[
            "Open the file and check for merged cells, header rows, or irregular formatting.",
            "Ensure the first row contains column headers.",
            "Try exporting a clean copy from your source system.",
        ],
        severity="error",
    )


# ── Schema diagnostics (run proactively on upload) ────────────────────────────

def diagnose_schema(df: pd.DataFrame, filename: str) -> list[dict]:
    """
    Run a full schema health check on an uploaded DataFrame.
    Returns a list of IntelligentError dicts (warnings/info), never errors.
    Runs 100% in-process with pandas — zero LLM calls.
    """
    warnings: list[dict] = []
    total_rows = len(df)
    if total_rows == 0:
        return warnings

    for col in df.columns:
        series = df[col]
        null_pct = series.isnull().mean()
        unique_count = series.nunique(dropna=True)

        # ── High null rate ──
        if null_pct > 0.40:
            severity = "critical" if null_pct > 0.80 else "warning"
            warnings.append(_make_error(
                code="MISSING_VALUES",
                title=f"Missing values: '{col}'",
                message=(
                    f"Column '{col}' is {round(null_pct * 100, 1)}% empty "
                    f"({int(null_pct * total_rows):,} of {total_rows:,} rows are null)."
                ),
                suggestions=[
                    f"Fill missing values with the column median before analysis.",
                    f"Consider excluding '{col}' if it has insufficient data coverage.",
                    f"Check the data export — the source system may not populate this field.",
                ],
                severity=severity,
                affected_column=col,
            ))

        # ── Mixed numeric / text column ──
        if pd.api.types.is_object_dtype(series):
            non_null = series.dropna()
            if len(non_null) > 0:
                numeric_count = pd.to_numeric(non_null, errors="coerce").notna().sum()
                numeric_ratio = numeric_count / len(non_null)
                if 0.05 < numeric_ratio < 0.95:
                    # Find the row range where the mismatch occurs
                    numeric_mask = pd.to_numeric(series, errors="coerce").notna()
                    text_mask = ~numeric_mask & series.notna()
                    text_rows = df.index[text_mask].tolist()
                    row_start = text_rows[0] + 1 if text_rows else None
                    row_end = text_rows[-1] + 1 if text_rows else None

                    # Detect currency/percentage strings
                    currency_sample = non_null.head(50).astype(str)
                    currency_count = currency_sample.str.contains(r'[\$£€¥,]', na=False, regex=True).sum()
                    pct_count = currency_sample.str.contains(r'%', na=False, regex=True).sum()

                    extra = ""
                    if currency_count > 3:
                        sample_vals = non_null[non_null.astype(str).str.contains(r'[\$£€¥,]', na=False, regex=True)].head(2).tolist()
                        extra = f" {currency_count} cells appear to be currency strings (e.g. '{sample_vals[0] if sample_vals else '$1,200'}')."
                    elif pct_count > 3:
                        extra = f" {pct_count} cells contain percentage symbols (e.g. '12.5%')."

                    warnings.append(_make_error(
                        code="MIXED_TYPES",
                        title=f"Mixed numeric/text values: '{col}'",
                        message=(
                            f"Column '{col}' contains mixed numeric and text values "
                            + (f"between rows {row_start}–{row_end}." if row_start else "throughout the column.")
                            + extra
                        ),
                        suggestions=[
                            f"Strip currency symbols and commas, then convert '{col}' to float.",
                            f"Remove percentage signs and divide by 100 to get decimal ratios.",
                            f"Use the 'Clean Data' agent to auto-detect and fix type mismatches.",
                        ],
                        severity="warning",
                        affected_column=col,
                        affected_rows=(row_start, row_end) if row_start else None,
                    ))

        # ── Potential ID column used as metric ──
        if pd.api.types.is_integer_dtype(series) or (
            pd.api.types.is_object_dtype(series) and unique_count == total_rows
        ):
            col_lower = col.lower()
            id_hints = ["id", "key", "code", "ref", "uuid", "guid", "number", "no", "num", "idx"]
            if any(h in col_lower for h in id_hints) and unique_count == total_rows and total_rows > 5:
                warnings.append(_make_error(
                    code="ID_COLUMN_METRIC",
                    title=f"Possible ID column: '{col}'",
                    message=(
                        f"Column '{col}' has {unique_count:,} unique values across {total_rows:,} rows — "
                        f"every value is distinct. This looks like an identifier, not a metric."
                    ),
                    suggestions=[
                        f"Exclude '{col}' from aggregations (SUM/AVG) — ID columns have no numeric meaning.",
                        f"Use '{col}' for GROUP BY or as a join key instead.",
                        f"If you need a row count, use COUNT(*) rather than SUM('{col}').",
                    ],
                    severity="info",
                    affected_column=col,
                ))

        # ── Duplicate values in presumed-unique column ──
        col_lower = col.lower()
        if any(h in col_lower for h in ["id", "invoice", "order", "ticket", "ref"]):
            dup_count = int(series.duplicated(keep=False).sum())
            if 0 < dup_count < total_rows * 0.5:  # Not every row — only partial dups
                warnings.append(_make_error(
                    code="DUPLICATE_ID_VALUES",
                    title=f"Duplicate values in '{col}'",
                    message=(
                        f"Column '{col}' has {dup_count:,} duplicate values. "
                        f"If this is an ID/key column, duplicates may indicate data export issues "
                        f"or one-to-many joins."
                    ),
                    suggestions=[
                        f"Run a GROUP BY '{col}' query to find which IDs appear multiple times.",
                        f"Check if the source system has a de-duplication step.",
                        f"If intentional (one-to-many), exclude '{col}' from COUNT DISTINCT metrics.",
                    ],
                    severity="warning",
                    affected_column=col,
                ))

        # ── Date column stored as text ──
        if pd.api.types.is_object_dtype(series) and any(
            h in col.lower() for h in ["date", "time", "created", "updated", "year", "month"]
        ):
            non_null = series.dropna().head(50)
            if len(non_null) > 0:
                parsed = pd.to_datetime(non_null, errors="coerce").notna().sum()
                if parsed / len(non_null) > 0.8 and not pd.api.types.is_datetime64_any_dtype(series):
                    sample = non_null.iloc[0] if len(non_null) > 0 else "2023-01-15"
                    warnings.append(_make_error(
                        code="DATE_AS_TEXT",
                        title=f"Date column stored as text: '{col}'",
                        message=(
                            f"Column '{col}' contains date-like values (e.g. '{sample}') "
                            f"but is stored as plain text. Date sorting and range filters will not work correctly."
                        ),
                        suggestions=[
                            f"Convert '{col}' to datetime using the transform engine.",
                            f"Use ISO 8601 format (YYYY-MM-DD) for best compatibility.",
                            f"Ensure consistent date formats throughout the column.",
                        ],
                        severity="warning",
                        affected_column=col,
                    ))

    # ── Duplicate rows ──
    dup_rows = int(df.duplicated().sum())
    if dup_rows > 0:
        warnings.append(_make_error(
            code="DUPLICATE_ROWS",
            title=f"{dup_rows:,} duplicate row(s) detected",
            message=(
                f"'{filename}' contains {dup_rows:,} rows that are exact duplicates of other rows "
                f"({round(dup_rows / total_rows * 100, 1)}% of the dataset)."
            ),
            suggestions=[
                "Run the 'Clean Data' agent to remove duplicates automatically.",
                "Check if the source export has a de-duplication option.",
                "If duplicates are intentional, ignore this warning.",
            ],
            severity="warning",
        ))

    return warnings


# ── SQL error diagnostics ──────────────────────────────────────────────────────

def diagnose_sql_error(
    exc: Exception,
    sql: str,
    df: pd.DataFrame | None = None,
    file_record: Any = None,
) -> dict:
    """
    Convert a DuckDB / SQL execution error into a human-readable diagnostic.
    Uses fuzzy column matching to suggest fixes for typos.
    """
    msg = str(exc)
    msg_lower = msg.lower()

    available_cols = list(df.columns) if df is not None else []

    # ── Table not found ──
    if "table" in msg_lower and ("not found" in msg_lower or "does not exist" in msg_lower):
        return _make_error(
            code="TABLE_NOT_FOUND",
            title="Dataset no longer in memory",
            message=(
                "The data table could not be found. This usually happens after a server restart "
                "when in-memory data was cleared."
            ),
            suggestions=[
                "Re-upload your file — the data is not persisted between server restarts.",
                "Refresh the page and re-upload to restore your session.",
            ],
            severity="error",
        )

    # ── Column not found ──
    col_match = re.search(
        r'(?:column|field|attribute)\s+["\']?([A-Za-z0-9_\s\-]+)["\']?\s+(?:not found|does not exist|unknown)',
        msg, re.IGNORECASE
    )
    if not col_match:
        # Also match: Referenced column "XYZ" not found
        col_match = re.search(r'"([^"]+)"\s+(?:not found|does not exist)', msg, re.IGNORECASE)

    if col_match:
        bad_col = col_match.group(1).strip()
        close = difflib.get_close_matches(bad_col, available_cols, n=3, cutoff=0.6)
        suggestion_text = (
            f"Did you mean: **{close[0]}**?" if close
            else f"Available columns: {', '.join(available_cols[:8]) or 'none'}"
        )

        suggestions = [
            f"Replace '{bad_col}' with '{close[0]}' in your query." if close else "Check column names in the Data Preview tab.",
            "Column names are case-sensitive in SQL — check for capitalisation differences.",
            f"Available columns: {', '.join(available_cols[:10])}.",
        ]

        # Check for missing values in referenced columns to suggest cleanups
        if df is not None:
            referenced_nulls = [c for c in available_cols if c in sql and df[c].isnull().any()]
            for c in referenced_nulls[:2]:
                null_pct = df[c].isnull().mean()
                suggestions.append(
                    f"Column '{c}' contains {round(null_pct * 100, 1)}% missing values. "
                    f"Consider cleaning it first or using COALESCE."
                )

        # Cross-sheet column search for automatic Excel sheet suggestion
        recovery = None
        if file_record is not None and file_record.path.suffix.lower() in {".xlsx", ".xls"}:
            sheet_names = file_record.metadata.get("sheet_names", [])
            active_sheet = file_record.metadata.get("active_sheet")
            for sheet in sheet_names:
                if sheet == active_sheet:
                    continue
                try:
                    engine = "openpyxl" if file_record.path.suffix.lower() == ".xlsx" else "xlrd"
                    sheet_df = pd.read_excel(file_record.path, sheet_name=sheet, nrows=0, engine=engine)
                    if bad_col in sheet_df.columns or difflib.get_close_matches(bad_col, list(sheet_df.columns), cutoff=0.8):
                        err = _make_error(
                            code="COLUMN_NOT_FOUND",
                            title=f"Column '{bad_col}' not found",
                            message=(
                                f"Column '{bad_col}' was not found in the active sheet '{active_sheet}', "
                                f"but it exists in sheet '{sheet}'."
                            ),
                            suggestions=[
                                f"Switch to sheet '{sheet}' to analyze this column.",
                                "Verify you are querying the correct sheet.",
                            ],
                            severity="error",
                            affected_column=bad_col,
                            recovery={
                                "type": "switch_sheet",
                                "sheet": sheet,
                                "file_id": file_record.file_id,
                                "label": f"Switch to sheet '{sheet}' and retry"
                            }
                        )
                        return err
                except Exception as scan_err:
                    logger.warning(f"Failed to scan sheet '{sheet}' for column '{bad_col}': {scan_err}")

        return _make_error(
            code="COLUMN_NOT_FOUND",
            title=f"Column '{bad_col}' not found",
            message=(
                f"The query references column '{bad_col}' which does not exist in this dataset. "
                + suggestion_text
            ),
            suggestions=suggestions,
            severity="error",
            affected_column=bad_col,
            recovery=recovery,
        )

    # ── Division by zero ──
    if "division by zero" in msg_lower or "divide by zero" in msg_lower:
        return _make_error(
            code="DIVISION_BY_ZERO",
            title="Division by zero in query",
            message="The query attempted to divide by zero. This happens when a denominator column contains 0 or null values.",
            suggestions=[
                "Wrap the denominator with NULLIF(column, 0) to skip zero values.",
                "Add a WHERE clause to exclude rows where the denominator is 0.",
            ],
            severity="error",
        )

    # ── Type mismatch ──
    if "type" in msg_lower and ("mismatch" in msg_lower or "cannot cast" in msg_lower or "conversion" in msg_lower):
        return _make_error(
            code="TYPE_MISMATCH",
            title="Data type mismatch in query",
            message=(
                f"The query is comparing or combining incompatible data types. "
                f"This often happens when a numeric column contains text values, or a date "
                f"column is stored as plain text. Detail: {msg[:120]}"
            ),
            suggestions=[
                "Use CAST(column AS DOUBLE) to explicitly convert text to numeric.",
                "Use TRY_CAST() to safely attempt conversion and return NULL on failure.",
                "Run the 'Clean Data' agent to detect and fix type mismatches before querying.",
            ],
            severity="error",
        )

    # ── Syntax error ──
    if "syntax" in msg_lower or "parser" in msg_lower or "unexpected" in msg_lower:
        # Extract the problematic token
        token_match = re.search(r'near\s+"([^"]+)"', msg)
        token = f" near '{token_match.group(1)}'" if token_match else ""
        return _make_error(
            code="SQL_SYNTAX_ERROR",
            title="SQL syntax error",
            message=f"The generated query has a syntax error{token}. This may be caused by an unusual question phrasing.",
            suggestions=[
                "Try rephrasing your question more simply.",
                "Use column names exactly as shown in the Data Preview tab.",
                "Avoid special characters or punctuation in your question.",
            ],
            severity="error",
        )

    # ── Generic fallback ──
    return _make_error(
        code="SQL_ERROR",
        title="Query execution failed",
        message=f"The analysis query could not be completed: {msg[:200]}",
        suggestions=[
            "Try a simpler version of your question.",
            "Check the Data Preview tab to confirm the column names and data types.",
            "Switch to a different AI provider if the issue persists.",
        ],
        severity="error",
    )


# ── Empty result diagnostics ───────────────────────────────────────────────────

def diagnose_empty_result(sql: str, df: pd.DataFrame | None = None, query: str = "") -> dict:
    """
    Build a diagnostic when a SQL query returns 0 rows, explaining possible causes
    using the actual data ranges available in the DataFrame.
    """
    context_lines = []

    if df is not None:
        # Detect date range from any datetime column
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                try:
                    min_d = df[col].min().strftime("%Y-%m-%d")
                    max_d = df[col].max().strftime("%Y-%m-%d")
                    context_lines.append(f"Data date range: {min_d} → {max_d}.")
                    break
                except Exception:
                    pass
            elif any(h in col.lower() for h in ["date", "time", "year"]) and pd.api.types.is_object_dtype(df[col]):
                try:
                    parsed = pd.to_datetime(df[col], errors="coerce").dropna()
                    if len(parsed) > 0:
                        min_d = parsed.min().strftime("%Y-%m-%d")
                        max_d = parsed.max().strftime("%Y-%m-%d")
                        context_lines.append(f"Data date range: {min_d} → {max_d}.")
                        break
                except Exception:
                    pass

        # Check for WHERE clause with likely filter values
        where_match = re.search(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            where_clause = where_match.group(1).strip()
            # Extract quoted string filter values
            str_values = re.findall(r"'([^']+)'", where_clause)
            for val in str_values[:2]:
                # Check if this value exists in any column
                found_in = []
                for col in df.select_dtypes(include="object").columns[:10]:
                    if val.lower() in df[col].astype(str).str.lower().values:
                        found_in.append(col)
                if not found_in:
                    context_lines.append(
                        f"Filter value '{val}' was not found in any column. "
                        f"Check spelling and capitalisation."
                    )

    context_str = " ".join(context_lines)
    return _make_error(
        code="EMPTY_DATASET",
        title="Empty dataset",
        message=(
            f"The analysis query returned 0 rows, resulting in an empty dataset. {context_str}"
        ).strip(),
        suggestions=[
            "Remove or relax the date filter if one was applied.",
            "Check that column values match exactly (case-sensitive in most cases).",
            "Use the Data Preview tab to explore actual values in the dataset.",
            "Try a broader question without specific filters to verify data exists.",
        ],
        severity="info",
    )


# ── Agent error diagnostics ────────────────────────────────────────────────────

def diagnose_agent_error(
    exc: Exception,
    agent_type: str,
    df: pd.DataFrame | None = None,
    query: str = "",
) -> dict:
    """
    Convert an agent timeout or crash into a helpful diagnostic with context
    from the actual DataFrame (row count, column count).
    """
    msg = str(exc).lower()
    row_count = len(df) if df is not None else 0
    col_count = len(df.columns) if df is not None else 0

    agent_labels = {
        "insight": "Data Query",
        "forecast": "Forecasting",
        "clean": "Data Cleaning",
        "summary": "Summary",
        "visualize": "Visualization",
        "report": "Report",
        "crossfile": "Cross-file Analysis",
    }
    label = agent_labels.get(agent_type, agent_type.title())

    # ── Timeout ──
    if "timeout" in msg or "timed out" in msg:
        size_note = ""
        if row_count > 100_000:
            size_note = (
                f" The dataset has {row_count:,} rows, which may cause slower processing "
                f"for complex aggregations."
            )
        return _make_error(
            code="AGENT_TIMEOUT",
            title=f"{label} is taking longer than expected",
            message=(
                f"The {label} analysis did not complete within the time limit.{size_note}"
            ),
            suggestions=[
                "Try a more specific question targeting fewer columns or a date range.",
                f"Filter the dataset to a smaller subset before running {label}.",
                "Switch to a faster AI provider (e.g. Gemini Flash) in the provider selector.",
                "For very large files, consider splitting by year or category first.",
            ],
            severity="warning",
        )

    # ── LLM quota / API error ──
    if any(k in msg for k in ("quota", "rate limit", "429", "api key", "unauthorized", "forbidden")):
        from core.llm_client import get_active_provider
        active_prov = "gemini"
        try:
            active_prov = get_active_provider()
        except Exception:
            pass
        next_prov = "ollama" if active_prov != "ollama" else "gemini"
        next_label = "local Ollama (Unlimited)" if next_prov == "ollama" else "Gemini"
        
        return _make_error(
            code="LLM_QUOTA_ERROR",
            title="AI provider rate limit reached",
            message=(
                "The AI provider returned an error — your API quota may be exhausted "
                "or the API key is invalid."
            ),
            suggestions=[
                "Switch to a different AI provider in the provider selector (top-left).",
                "Wait a few minutes before retrying if using a free-tier API key.",
                "Check your API key in the .env file under the backend directory.",
                "Use Ollama for unlimited local processing without API keys.",
            ],
            severity="warning",
            recovery={
                "type": "switch_provider",
                "provider": next_prov,
                "label": f"Switch to {next_label} and retry"
            }
        )

    # ── No file loaded ──
    if "no file" in msg or "not found" in msg:
        return _make_error(
            code="NO_FILE_LOADED",
            title="No dataset loaded",
            message="There is no data file loaded for this analysis. Please upload a CSV or Excel file first.",
            suggestions=[
                "Drag and drop a file onto the upload area in the left sidebar.",
                "Accepted formats: .csv, .xlsx, .xls (up to 50 MB).",
            ],
            severity="info",
        )

    # ── Generic agent crash ──
    return _make_error(
        code="AGENT_ERROR",
        title=f"{label} analysis failed",
        message=(
            f"An unexpected error occurred during {label} analysis. "
            f"Dataset: {row_count:,} rows × {col_count} columns."
        ),
        suggestions=[
            "Try rephrasing your question.",
            "Check that your file contains the relevant data for this analysis.",
            "Switch to a different AI provider if the issue persists.",
        ],
        severity="error",
    )


# ── Transform error diagnostics ────────────────────────────────────────────────

def diagnose_transform_error(exc: Exception, action: dict, df: pd.DataFrame | None = None) -> dict:
    """Convert a pandas transformation failure into a precise, actionable message."""
    msg = str(exc)
    msg_lower = msg.lower()
    op = action.get("operation", "unknown")
    col = action.get("column", "")
    available = list(df.columns) if df is not None else []

    # ── Column missing ──
    if "column" in msg_lower and ("not found" in msg_lower or "keyerror" in msg_lower):
        bad_col = col or re.search(r"'([^']+)'", msg)
        if hasattr(bad_col, "group"):
            bad_col = bad_col.group(1)
        close = difflib.get_close_matches(str(bad_col), available, n=2, cutoff=0.6)
        return _make_error(
            code="TRANSFORM_COLUMN_MISSING",
            title=f"Column '{bad_col}' not found for transform",
            message=(
                f"The '{op}' transformation targets column '{bad_col}' which does not exist. "
                + (f"Did you mean '{close[0]}'?" if close else "")
            ),
            suggestions=[
                f"Replace '{bad_col}' with '{close[0]}' in the transform settings." if close else
                f"Available columns: {', '.join(available[:8])}.",
                "Check the Data Preview tab to confirm column names.",
            ],
            severity="error",
            affected_column=str(bad_col),
        )

    # ── Invalid date format ──
    if any(k in msg_lower for k in ("date", "time", "datetime", "parse", "strptime")):
        return _make_error(
            code="INVALID_DATE_FORMAT",
            title="Invalid date format",
            message=(
                f"The date conversion failed for column '{col}'. "
                f"The values could not be parsed as standard dates. Detail: {msg[:120]}"
            ),
            suggestions=[
                "Check that the date format is consistent (e.g. YYYY-MM-DD or MM/DD/YYYY).",
                "Remove any non-date text like 'N/A' or 'unknown' before converting.",
                "Specify the format explicitly (e.g., %Y-%m-%d) in the transformation settings.",
            ],
            severity="error",
            affected_column=col,
        )

    # ── Type conversion failure ──
    if "convert" in msg_lower or "cast" in msg_lower or "float" in msg_lower or "int" in msg_lower:
        return _make_error(
            code="TRANSFORM_TYPE_ERROR",
            title=f"Cannot convert '{col}' to numeric",
            message=(
                f"The '{op}' step could not convert column '{col}' to a numeric type. "
                f"The column likely contains text values that cannot be parsed as numbers."
            ),
            suggestions=[
                f"Use the 'Clean Data' agent to identify non-numeric values in '{col}' first.",
                f"Strip currency symbols ($, £, €) and commas before converting.",
                f"Set conversion errors to 'coerce' to replace unparseable values with null.",
            ],
            severity="error",
            affected_column=col,
        )

    # ── Generic transform failure ──
    return _make_error(
        code="TRANSFORM_ERROR",
        title=f"Transformation '{op}' failed",
        message=f"Could not apply the '{op}' transformation: {msg[:200]}",
        suggestions=[
            "Undo the last step and try a different approach.",
            "Check the column data types in the Data Preview tab.",
        ],
        severity="error",
        affected_column=col,
    )


# ── Markdown renderer ──────────────────────────────────────────────────────────

def format_for_user(err: dict) -> str:
    """
    Render an IntelligentError dict as clean markdown for the chat interface.
    Includes title, message, and collapsible suggestions.
    """
    severity_icons = {
        "critical": "🔴",
        "error": "🔴",
        "warning": "🟡",
        "info": "🔵",
    }
    icon = severity_icons.get(err.get("severity", "error"), "🔴")

    lines = [f"{icon} **{err.get('title', 'Error')}**\n"]
    lines.append(err.get("message", "An error occurred."))

    if err.get("affected_rows"):
        r = err["affected_rows"]
        lines.append(f"\n*Affected rows: {r[0]}–{r[1]}*")

    if err.get("suggestions"):
        lines.append("\n\n**Suggested fixes:**")
        for i, sug in enumerate(err["suggestions"], 1):
            lines.append(f"\n{i}. {sug}")

    return "\n".join(lines)
