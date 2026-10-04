"""
parsing.py — Correct, bounded CSV/XLSX parsing.

Fixes:
* delimiter sniffing (comma, semicolon, tab, pipe) instead of assuming commas;
* encoding detection that actually distinguishes UTF-8 / CP1252 / Latin-1
  (Latin-1 never fails, so it is only the last resort and is flagged);
* numeric text such as "$1,234.50", "1.234,50 €" or "12%" is converted to numbers
  when (almost) every value in the column is numeric, so aggregations work;
  identifier-like columns (leading zeros) are left untouched;
* Excel header-row detection for sheets with title rows above the table;
* parsing runs in a separate, killable process with a hard timeout so a
  pathological file can never pin an API/worker thread forever.
"""

from __future__ import annotations

import csv
import gc
import json
import logging
import multiprocessing as mp
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("datapilot.parsing")

# CSV text is held as Arrow-backed strings while parsing (~5x smaller than Python
# str objects); columns are materialised as plain Python objects one at a time
# for type inference, and remaining text columns are only converted back to the
# classic object dtype at the very end (or never, on the Parquet path).
CSV_READ_CHUNK_ROWS = 50_000
_ARROW_TEXT = "string[pyarrow]"


def _is_arrow_text(series: pd.Series) -> bool:
    return isinstance(series.dtype, pd.StringDtype)


def _release_column_temporaries() -> None:
    """Free the previous column's temporaries now.

    pandas' ``.str`` accessor forms a reference cycle with its Series, so the
    per-column string copies made during inference are only reclaimed by the
    cyclic GC.  String objects do not trigger collections, so without this the
    temporaries of *every* column pile up (measured: ~1 column-worth of strings
    per column, i.e. the parser peak grew with the column count).  A young-
    generation collection costs a few milliseconds.
    """
    gc.collect(1)


def _as_object(series: pd.Series) -> pd.Series:
    """Materialise one column exactly as ``read_csv(dtype=str)`` would: str values, NaN for missing."""
    if not _is_arrow_text(series):
        return series
    return pd.Series(series.to_numpy(dtype=object, na_value=np.nan), index=series.index, name=series.name)

SNIFF_BYTES = 64 * 1024
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]

_NUMERIC_RE = re.compile(
    r"^\s*[\(\-+]?\s*[$€£¥₹]?\s*[\-+]?\d[\d.,'\s]*\s*[$€£¥₹%]?\s*\)?\s*$"
)


class ParseError(ValueError):
    """User-facing parsing failure."""


def detect_encoding(sample: bytes) -> tuple[str, bool]:
    """Return (encoding, is_lossy_guess)."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            sample.decode(enc)
            return enc, False
        except UnicodeDecodeError:
            continue
    return "latin-1", True


def detect_delimiter(text_sample: str) -> str:
    lines = [ln for ln in text_sample.splitlines() if ln.strip()][:50]
    if not lines:
        return ","
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(CANDIDATE_DELIMITERS))
        if dialect.delimiter in CANDIDATE_DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass
    # Fallback: the delimiter with the most consistent, non-zero count per line.
    best, best_score = ",", -1.0
    for delim in CANDIDATE_DELIMITERS:
        counts = [ln.count(delim) for ln in lines]
        if not counts or max(counts) == 0:
            continue
        mode = max(set(counts), key=counts.count)
        consistency = counts.count(mode) / len(counts)
        score = consistency * mode
        if mode > 0 and score > best_score:
            best, best_score = delim, score
    return best


def _parse_number(raw: str, decimal_comma: bool) -> float | None:
    s = raw.strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    s = re.sub(r"[$€£¥₹%\s']", "", s)
    if decimal_comma:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _decimal_comma_votes(sample: pd.Series) -> bool:
    """Decide whether ',' is the decimal separator from unambiguous values only."""
    comma = dot = 0
    for raw in sample:
        digits = re.sub(r"[^\d.,]", "", str(raw))
        idx = max(digits.rfind(","), digits.rfind("."))
        if idx < 0:
            continue
        sep, tail = digits[idx], digits[idx + 1:]
        other = "." if sep == "," else ","
        if len(tail) != 3 or other in digits[:idx]:
            if sep == ",":
                comma += 1
            else:
                dot += 1
    return comma > dot


_LEADING_ZERO_RE = r"^\s*[+-]?0\d+(?:[.,]\d+)?\s*$"


def _looks_identifier(values: pd.Series) -> bool:
    """True when ANY value carries a meaningful leading zero (ZIP codes, account
    numbers, SKUs, phone extensions…).

    Converting such a column to a number silently destroys data ("02134" -> 2134),
    so a single leading-zero value anywhere in the column keeps the whole column
    as text.  Plain zero and decimals below one ("0", "0.5", "0,5") do not count.
    The whole column is scanned — a sample can miss the one value that matters.
    """
    if values is None or len(values) == 0:
        return False
    text = values.dropna()
    if text.empty:
        return False
    if text.dtype != object and not pd.api.types.is_string_dtype(text):
        return False
    text = text.astype(str)
    return bool(text.str.match(_LEADING_ZERO_RE).any())


def coerce_numeric_text(df: pd.DataFrame, threshold: float = 0.97) -> list[dict[str, Any]]:
    """Convert object columns of formatted numbers to floats in-place. Returns a change log."""
    changes: list[dict[str, Any]] = []
    for col in df.columns:
        try:
            change = _coerce_numeric_column(df, col, threshold)
        finally:
            _release_column_temporaries()
        if change:
            changes.append(change)
    return changes


def _coerce_numeric_column(df: pd.DataFrame, col, threshold: float) -> dict[str, Any] | None:
    series = _as_object(df[col])
    if series.dtype != object:
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    as_str = non_null.astype(str)
    if not all(isinstance(v, str) for v in non_null.head(500)):
        return None
    match_ratio = as_str.str.match(_NUMERIC_RE).mean()
    if match_ratio < threshold or _looks_identifier(as_str):
        return None
    decimal_comma = _decimal_comma_votes(as_str.head(1000))
    parsed = series.map(lambda v: _parse_number(str(v), decimal_comma) if pd.notna(v) else None)
    ok_ratio = parsed.notna().sum() / max(len(non_null), 1)
    if ok_ratio < threshold:
        return None
    df[col] = pd.to_numeric(parsed, errors="coerce")
    return {
        "column": str(col),
        "converted_to": "number",
        "percent": bool(as_str.str.contains("%").mean() > 0.5),
        "decimal_comma": bool(decimal_comma),
        "unparsed_values": int(len(non_null) - parsed.notna().sum()),
    }


def infer_text_column_types(df: pd.DataFrame) -> None:
    """Type CSV columns read as text, preserving identifier-like values (leading zeros)."""
    for col in df.columns:
        try:
            _infer_text_column(df, col)
        finally:
            _release_column_temporaries()


def _infer_text_column(df: pd.DataFrame, col) -> None:
    series = _as_object(df[col])
    non_null = series.dropna()
    if non_null.empty:
        return
    stripped = non_null.str.strip()
    if _looks_identifier(stripped):
        return
    lowered = stripped.str.lower()
    if lowered.isin({"true", "false"}).all():
        df[col] = series.map(lambda v: None if pd.isna(v) else str(v).strip().lower() == "true")
        return
    numeric = pd.to_numeric(stripped, errors="coerce")
    if numeric.notna().all():
        df[col] = pd.to_numeric(series.str.strip(), errors="coerce")


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols: list[str] = []
    seen: dict[str, int] = {}
    for i, col in enumerate(df.columns):
        name = str(col).strip() if col is not None and str(col).strip() else f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    df.columns = cols
    return df


def _detect_excel_header(raw: pd.DataFrame) -> int:
    """Return the most plausible header row index (0..9) for a header=None frame."""
    best_row, best_score = 0, -1.0
    width = raw.shape[1] or 1
    for idx in range(min(10, len(raw))):
        row = raw.iloc[idx]
        non_null = row.notna().sum()
        if non_null == 0:
            continue
        str_ratio = sum(isinstance(v, str) for v in row if pd.notna(v)) / non_null
        fill_ratio = non_null / width
        score = fill_ratio * 0.6 + str_ratio * 0.4
        if score > best_score + 0.15 or (best_score < 0):
            best_row, best_score = idx, score
        if fill_ratio >= 0.8 and str_ratio >= 0.8:
            return idx
    return best_row


def _read_csv_text(path: Path, delimiter: str, encoding: str) -> pd.DataFrame:
    """Same parser and options as ``read_csv(dtype=str)``, but chunked into Arrow strings."""
    chunks = []
    reader = pd.read_csv(path, sep=delimiter, encoding=encoding, dtype=str, on_bad_lines="error",
                         chunksize=CSV_READ_CHUNK_ROWS)
    with reader:
        for chunk in reader:
            chunks.append(chunk.astype(_ARROW_TEXT))
    if not chunks:  # header-only file
        return pd.read_csv(path, sep=delimiter, encoding=encoding, dtype=str, on_bad_lines="error").astype(_ARROW_TEXT)
    return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]


def _text_to_object(df: pd.DataFrame) -> None:
    for col in df.columns:
        if _is_arrow_text(df[col]):
            df[col] = _as_object(df[col])


def parse_file(path: str | Path, ext: str, sheet: str | None = None,
               keep_arrow_text: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a CSV/XLS/XLSX file into a DataFrame plus parse metadata.

    Text columns come back as classic object dtype unless *keep_arrow_text* is
    set (the Parquet path), where they stay Arrow-backed to save memory — the
    Parquet file and anything read from it are identical either way.
    """
    path = Path(path)
    ext = ext.lower()
    meta: dict[str, Any] = {}
    if ext == ".csv":
        with open(path, "rb") as fh:
            sample = fh.read(SNIFF_BYTES)
        if not sample.strip():
            raise ParseError("The uploaded CSV file is empty.")
        encoding, lossy = detect_encoding(sample)
        delimiter = detect_delimiter(sample.decode(encoding, errors="replace"))
        try:
            df = _read_csv_text(path, delimiter, encoding)
        except UnicodeDecodeError:
            encoding, lossy = "latin-1", True
            df = _read_csv_text(path, delimiter, encoding)
        except pd.errors.ParserError as exc:
            raise ParseError(f"CSV is malformed (inconsistent number of columns): {exc}") from exc
        meta.update({"encoding": encoding, "encoding_guessed": lossy, "delimiter": delimiter})
        infer_text_column_types(df)
    elif ext in {".xlsx", ".xls"}:
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"
        workbook = pd.ExcelFile(path, engine=engine)
        sheet_names = [str(s) for s in workbook.sheet_names]
        if not sheet_names:
            raise ParseError("The workbook contains no sheets.")
        active = sheet if sheet is not None else sheet_names[0]
        if active not in sheet_names:
            raise ParseError(f"Sheet '{active}' not found.")
        raw = workbook.parse(sheet_name=active, header=None)
        raw = raw.dropna(how="all").dropna(axis=1, how="all")
        if raw.empty:
            df = pd.DataFrame()
            header_row = 0
        else:
            header_row = _detect_excel_header(raw.reset_index(drop=True))
            raw = raw.reset_index(drop=True)
            header = raw.iloc[header_row].tolist()
            df = raw.iloc[header_row + 1:].reset_index(drop=True)
            df.columns = header
            df = df.infer_objects()
        sheet_columns: dict[str, list[str]] = {}
        for name in sheet_names[:25]:
            try:
                head = workbook.parse(sheet_name=name, header=None, nrows=11).dropna(how="all").reset_index(drop=True)
                if not head.empty:
                    row = _detect_excel_header(head)
                    sheet_columns[name] = [str(v) for v in head.iloc[row].tolist() if pd.notna(v)]
            except Exception:
                continue
        meta.update({"sheet_names": sheet_names, "active_sheet": active, "header_row": int(header_row),
                     "sheet_columns": sheet_columns})
    else:
        raise ParseError(f"Unsupported file type '{ext}'.")

    df = _normalise_columns(df)
    meta["numeric_conversions"] = coerce_numeric_text(df)
    if not keep_arrow_text:
        _text_to_object(df)
    return df, meta


def normalise_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Make mixed-type object columns Parquet-safe without losing nulls.

    Returns a *shallow* copy: only the columns that need rewriting get new
    arrays, so the caller's frame is never mutated and untouched columns are not
    duplicated in memory.
    """
    out = df.copy(deep=False)
    out.columns = [str(c) for c in out.columns]
    for col in out.columns:
        series = out[col]
        if series.dtype == object:
            kind = pd.api.types.infer_dtype(series, skipna=True)
            if kind not in {"string", "empty", "boolean", "integer", "floating", "decimal", "date", "datetime", "datetime64"}:
                out[col] = series.map(lambda v: None if pd.isna(v) else str(v)).astype(object)
            elif kind in {"date", "datetime"}:
                try:
                    out[col] = pd.to_datetime(series, errors="raise")
                except Exception:
                    out[col] = series.map(lambda v: None if pd.isna(v) else str(v)).astype(object)
    return out


# ── Parquet I/O (canonical on-disk form of every dataset version) ────────────

def write_parquet(df: pd.DataFrame, path) -> None:
    """Write the canonical Parquet form of *df*.

    Arrow-backed text columns are written zero-copy, but recorded in the pandas
    metadata as plain object columns, so every reader gets exactly the same
    frame as for classic object text columns.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    out = normalise_for_parquet(df)
    table = pa.Table.from_pandas(out, preserve_index=False)
    arrow_text = {str(c) for c in out.columns if _is_arrow_text(out[c])}
    if arrow_text and table.schema.metadata and b"pandas" in table.schema.metadata:
        pandas_meta = json.loads(table.schema.metadata[b"pandas"])
        for column in pandas_meta.get("columns", []):
            if column.get("name") in arrow_text:
                column["numpy_type"] = "object"
                column["metadata"] = None
        table = table.replace_schema_metadata({**table.schema.metadata, b"pandas": json.dumps(pandas_meta).encode()})
    pq.write_table(table, path)


def read_parquet(source) -> pd.DataFrame:
    """Read a dataset version.

    Plain ``pd.read_parquet`` (consolidated blocks) measured best end-to-end:
    Arrow ``split_blocks``/``self_destruct`` lowered the load peak slightly but made
    the next row filter consolidate the whole frame (higher overall peak).
    """
    return pd.read_parquet(source)


# ── Killable subprocess execution ────────────────────────────────────────────

def _child(path: str, ext: str, sheet: str | None, out_path: str, meta_path: str) -> None:  # pragma: no cover - runs in child
    try:
        df, meta = parse_file(path, ext, sheet, keep_arrow_text=True)
        write_parquet(df, out_path)
        del df
        Path(meta_path).write_text(json.dumps({"ok": True, "meta": meta}, default=str))
    except Exception as exc:  # report the error to the parent
        Path(meta_path).write_text(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}))


def _subprocess_enabled() -> bool:
    return os.getenv("PARSE_IN_SUBPROCESS", "true").strip().lower() in {"1", "true", "yes", "on"}


def parse_to_parquet(path: str | Path, ext: str, sheet: str | None, timeout_seconds: int,
                     out_path: str | Path) -> dict[str, Any]:
    """Parse *path* and write the canonical Parquet form to *out_path*; return parse metadata.

    The parsed frame never has to live in the caller's process: the caller reads
    the Parquet file back (canonical types) and can upload the very same file as
    the dataset version, instead of re-serialising it in memory.
    """
    if not _subprocess_enabled():
        df, meta = parse_file(path, ext, sheet, keep_arrow_text=True)
        write_parquet(df, out_path)
        return meta
    return _run_parse_child(path, ext, sheet, timeout_seconds, str(out_path))


def parse_file_bounded(path: str | Path, ext: str, sheet: str | None, timeout_seconds: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse in a child process that is terminated if it exceeds *timeout_seconds*."""
    if not _subprocess_enabled():
        return parse_file(path, ext, sheet)
    with tempfile.TemporaryDirectory(prefix="dp_parse_") as tmp:
        out_path = os.path.join(tmp, "out.parquet")
        meta = _run_parse_child(path, ext, sheet, timeout_seconds, out_path)
        return read_parquet(out_path), meta


def _run_parse_child(path: str | Path, ext: str, sheet: str | None, timeout_seconds: int, out_path: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dp_parse_meta_") as tmp:
        meta_path = os.path.join(tmp, "meta.json")
        ctx = mp.get_context("spawn")
        proc = ctx.Process(target=_child, args=(str(path), ext, sheet, out_path, meta_path), daemon=True)
        proc.start()
        proc.join(timeout_seconds)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
            raise ParseError(f"File parsing timed out after {timeout_seconds} seconds.")
        if not os.path.exists(meta_path):
            raise ParseError("File parser crashed (the file may be corrupt or too large for available memory).")
        result = json.loads(Path(meta_path).read_text())
        if not result.get("ok"):
            if result.get("type") == "ParseError":
                raise ParseError(result.get("error", "Could not parse file."))
            raise ValueError(result.get("error", "Could not parse file."))
        return result["meta"]
