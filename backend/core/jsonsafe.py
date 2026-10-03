"""
jsonsafe.py — Convert analytics results into strict, JSON-serialisable values.

DuckDB, pandas and numpy return datetime/date/Decimal/numpy scalars, NaN/inf and
pandas NA values that the standard ``json`` module rejects (or encodes as invalid
JSON such as ``NaN``).  Every payload that leaves the API (SSE events, persisted
chat history, saved analyses/reports, job results) goes through ``to_jsonable``.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import json
import math
import uuid
from typing import Any

try:  # numpy/pandas are always installed in the backend, but keep this import-safe.
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

try:
    import pandas as _pd
except Exception:  # pragma: no cover
    _pd = None


def _float(value: float) -> float | None:
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def to_jsonable(value: Any) -> Any:
    """Recursively convert *value* into JSON-safe primitives."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    if _pd is not None:
        if value is _pd.NaT or (isinstance(value, type(_pd.NA)) and value is _pd.NA):
            return None
        if isinstance(value, _pd.Timestamp):
            return None if _pd.isna(value) else value.isoformat()
        if isinstance(value, _pd.Timedelta):
            return None if _pd.isna(value) else value.total_seconds()
        if isinstance(value, _pd.Period):
            return str(value)
        if isinstance(value, _pd.Interval):
            return str(value)
    if isinstance(value, decimal.Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return int(value) if value == value.to_integral_value() and abs(value) < 2**53 else float(value)
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if _np is not None:
        if isinstance(value, _np.bool_):
            return bool(value)
        if isinstance(value, _np.integer):
            return int(value)
        if isinstance(value, _np.floating):
            return _float(float(value))
        if isinstance(value, _np.datetime64):
            if _np.isnat(value):
                return None
            return _pd.Timestamp(value).isoformat() if _pd is not None else str(value)
        if isinstance(value, _np.timedelta64):
            return None if _np.isnat(value) else float(value / _np.timedelta64(1, "s"))
        if isinstance(value, _np.ndarray):
            return [to_jsonable(v) for v in value.tolist()]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def dumps(value: Any, **kwargs: Any) -> str:
    """``json.dumps`` that never fails on analytics types and never emits NaN."""
    return json.dumps(to_jsonable(value), allow_nan=False, **kwargs)


def records(df) -> list[dict]:
    """Convert a DataFrame to JSON-safe records."""
    return to_jsonable(df.to_dict(orient="records"))
