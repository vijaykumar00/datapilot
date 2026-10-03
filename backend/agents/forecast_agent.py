"""
forecast_agent.py — Time-series forecasting that is honest about what it does.

Correctness rules:
* The forecast TARGET comes from the question (column names, labels, semantic
  aliases).  If the question does not identify one and several plausible
  numeric measures exist, the agent asks the user instead of guessing.
  Identifier-like columns (IDs, codes, zip codes) are never forecast.
* The HORIZON is parsed with units (days/weeks/months/quarters/years) and
  converted to the series' frequency; "next year" means 12 months, not 1.
* A date column is required: forecasting row order is not a time series, so
  the old "linear regression on row index" fallback is gone.
* Periods with no data are interpolated (not treated as zero sales) and an
  incomplete final period is dropped so it does not look like a collapse.
* Confidence bands come from the fitted model's residuals; no hard-coded
  confidence scores.
"""

from __future__ import annotations

import json
import logging
import math
import re

import numpy as np
import pandas as pd

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.forecast")

_UNIT_TO_MONTHS = {"day": 1 / 30.4375, "week": 7 / 30.4375, "month": 1, "quarter": 3, "year": 12}
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}
_ID_HINTS = re.compile(r"(?:^|_|\b)(id|key|code|zip|postal|pin|phone|sku|number|no)(?:$|_|\b)", re.IGNORECASE)


def parse_horizon(query: str) -> tuple[int, str]:
    """Return (number_of_units, unit) from the question; default 3 months."""
    q = query.lower()
    m = re.search(r"(\d+|" + "|".join(_WORD_NUMBERS) + r")\s*(day|week|month|quarter|year)s?\b", q)
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
        return max(1, n), m.group(2)
    m = re.search(r"\bnext\s+(day|week|month|quarter|year)\b", q)
    if m:
        return 1, m.group(1)
    return 3, "month"


def horizon_in_periods(n: int, unit: str, freq: str) -> int:
    months = n * _UNIT_TO_MONTHS[unit]
    if freq == "D":
        return max(1, int(round(months * 30.4375)))
    if freq == "W":
        return max(1, int(math.ceil(months * 30.4375 / 7)))
    return max(1, int(math.ceil(months)))


def _is_identifier(col: str, series: pd.Series) -> bool:
    if _ID_HINTS.search(str(col)):
        return True
    clean = series.dropna()
    if len(clean) > 10 and clean.nunique() == len(clean) and pd.api.types.is_integer_dtype(clean.dtype):
        ordered = clean.sort_values()
        if (ordered.diff().dropna() == 1).mean() > 0.9:
            return True
    return False


def _find_date_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col].dtype):
            return col
    for col in df.columns:
        if any(kw in str(col).lower() for kw in ["date", "time", "month", "period", "week", "day", "year"]):
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed") if df[col].dtype == object else None
            if parsed is not None and parsed.notna().mean() > 0.8:
                return col
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(200)
        if len(sample) and pd.to_datetime(sample, errors="coerce", format="mixed").notna().mean() > 0.9:
            return col
    return None


def resolve_target(query: str, df: pd.DataFrame, semantic_map: dict | None) -> tuple[str | None, list[str]]:
    """Return (column, candidates). column is None when ambiguous."""
    candidates = [
        str(c) for c in df.select_dtypes(include="number").columns
        if not _is_identifier(str(c), df[c]) and df[c].nunique(dropna=True) > 1
    ]
    if not candidates:
        return None, []
    q = query.lower()
    scores: dict[str, int] = {}
    for col in candidates:
        meta = (semantic_map or {}).get(col) or {}
        names = {col.lower(), col.lower().replace("_", " "), str(meta.get("label", "")).lower()}
        names |= {str(a).lower() for a in meta.get("aliases", []) if len(str(a)) > 2}
        best = 0
        for name in names:
            if name and re.search(r"\b" + re.escape(name) + r"\b", q):
                best = max(best, len(name))
        if best:
            scores[col] = best
    if scores:
        return max(scores, key=scores.get), candidates
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _infer_freq(dates: pd.Series) -> str:
    span_days = (dates.max() - dates.min()).days
    distinct_days = dates.dt.normalize().nunique()
    if span_days <= 120 and distinct_days >= 20:
        return "D"
    if span_days <= 730 and distinct_days >= 26:
        return "W"
    return "M"


def _build_explain(method, value_col, date_col, freq, n_points, horizon, last_val, next_val, pct,
                   warnings, filename, sheet, aic=None) -> dict:
    freq_label = {"D": "daily", "W": "weekly", "M": "monthly"}[freq]
    sections = [
        {"label": "Method Selected", "icon": "🧪", "content": [method, f"Fitted on {n_points} {freq_label} periods."]},
        {"label": "Data Basis", "icon": "📊", "content": [
            f"Column forecasted: `{value_col}`", f"Date column: `{date_col}`",
            f"Aggregated to {freq_label} totals; empty periods interpolated; incomplete final period excluded.",
            f"Forecasting {horizon} {freq_label} period(s) forward",
        ]},
        {"label": "Detected Trend", "icon": "📈", "content": (
            f"Last complete period {last_val:,.2f}; first forecast period {next_val:,.2f} ({pct:+.1f}%)."
        )},
        {"label": "Confidence Interpretation", "icon": "🛡️", "content": (
            "Shaded band = ±1.96 × residual standard deviation of the fitted model. It reflects past fit "
            "error only and widens with uncertainty; it is not a guarantee."
        )},
    ]
    if warnings:
        sections.append({"label": "Notices", "icon": "⚠️", "content": warnings})
    return {
        "type": "forecast",
        "sections": sections,
        "data_source": filename,
        "sheet": sheet,
        "columns": [value_col, date_col],
        "filters": "None",
        "sql": "N/A",
        "intermediate_calculations": [f"Historical periods: {n_points}", f"Forecast periods: {horizon}"]
        + ([f"Model AIC: {aic:.1f}"] if aic is not None else []),
        "confidence_score": None,
        "verification": "Statistical model fitted to your data",
        "reasoning_summary": f"{method} on {freq_label} totals of '{value_col}'.",
    }


def run_forecast(df: pd.DataFrame, query: str, semantic_map: dict | None, filename: str, sheet: str) -> dict:
    """Pure, blocking forecast computation (runs in a worker/job thread)."""
    import plotly.graph_objects as go

    date_col = _find_date_column(df)
    if not date_col:
        return {"error": "Forecasting needs a date/time column to order observations. "
                         "No date column was detected in this dataset."}
    value_col, candidates = resolve_target(query, df, semantic_map)
    if value_col is None:
        if not candidates:
            return {"error": "No numeric measure suitable for forecasting was found (identifier columns are excluded)."}
        return {"error": "Which column should be forecast? Please mention one of: "
                         + ", ".join(f"'{c}'" for c in candidates[:10]) + "."}

    n_units, unit = parse_horizon(query)
    frame = pd.DataFrame({
        "d": pd.to_datetime(df[date_col], errors="coerce", format="mixed") if df[date_col].dtype == object
        else pd.to_datetime(df[date_col], errors="coerce"),
        "v": pd.to_numeric(df[value_col], errors="coerce"),
    }).dropna()
    if frame.empty:
        return {"error": f"No rows have both a valid date in '{date_col}' and a number in '{value_col}'."}

    warnings: list[str] = []
    freq = _infer_freq(frame["d"])
    rule = {"D": "D", "W": "W-SUN", "M": "MS"}[freq]
    series = frame.set_index("d")["v"].resample(rule).sum(min_count=1)

    last_date = frame["d"].max()
    period_end = {"D": last_date.normalize(), "W": (last_date + pd.offsets.Week(weekday=6)).normalize(),
                  "M": (last_date + pd.offsets.MonthEnd(0)).normalize()}[freq]
    if freq != "D" and last_date.normalize() < period_end and len(series) > 1:
        series = series.iloc[:-1]
        warnings.append("The most recent period is incomplete and was excluded from the model.")
    gaps = int(series.isna().sum())
    if gaps:
        series = series.interpolate(limit_direction="both")
        warnings.append(f"{gaps} period(s) had no data and were interpolated.")

    horizon = horizon_in_periods(n_units, unit, freq)
    if len(series) < 6:
        return {"error": f"Only {len(series)} {'monthly' if freq == 'M' else 'periodic'} data points are available; "
                         "at least 6 are needed for a meaningful forecast."}
    if horizon > len(series):
        warnings.append(f"Forecast horizon ({horizon}) exceeds the history length ({len(series)}); uncertainty is high.")

    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    season = {"D": 7, "W": 52, "M": 12}[freq]
    seasonal = "add" if len(series) >= 2 * season else None
    model = ExponentialSmoothing(series.astype(float), trend="add", seasonal=seasonal,
                                 seasonal_periods=season if seasonal else None, initialization_method="estimated")
    fit = model.fit(optimized=True)
    forecast = fit.forecast(horizon)
    resid_std = float(np.nanstd(fit.resid))
    lower = forecast.values - 1.96 * resid_std
    upper = forecast.values + 1.96 * resid_std
    method = "Holt-Winters exponential smoothing" + (" (seasonal)" if seasonal else " (trend)")
    if not seasonal:
        warnings.append("Not enough history for seasonality; trend-only model used.")

    hist_x = [d.isoformat() for d in series.index]
    fc_x = [d.isoformat() for d in forecast.index]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist_x, y=series.values.tolist(), name="Historical", line=dict(color="#6366f1", width=2)))
    fig.add_trace(go.Scatter(x=fc_x, y=forecast.values.tolist(), name=f"Forecast (+{horizon})",
                             line=dict(color="#f59e0b", dash="dash", width=2)))
    fig.add_trace(go.Scatter(x=fc_x + fc_x[::-1], y=upper.tolist() + lower.tolist()[::-1], fill="toself",
                             fillcolor="rgba(245,158,11,0.12)", line=dict(color="rgba(0,0,0,0)"), name="95% band"))
    freq_label = {"D": "day", "W": "week", "M": "month"}[freq]
    fig.update_layout(title=f"Forecast: {value_col} (next {horizon} {freq_label}s)", template="plotly_dark",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, sans-serif"), margin=dict(l=40, r=20, t=60, b=40))

    last_val = float(series.iloc[-1])
    next_val = float(forecast.iloc[0])
    pct = ((next_val - last_val) / abs(last_val) * 100) if last_val else 0.0
    content = (
        f"**Forecast: {value_col}** — next {horizon} {freq_label}(s)\n\n"
        f"- **Last complete {freq_label}:** {last_val:,.2f}\n"
        f"- **Next {freq_label}:** {next_val:,.2f} ({pct:+.1f}%)\n"
        f"- **End of horizon:** {float(forecast.iloc[-1]):,.2f}\n"
        f"- **Method:** {method}\n"
        f"- **Band:** 95% from residual error (±{1.96 * resid_std:,.2f})\n"
    )
    if warnings:
        content += "\n" + "\n".join(f"> ⚠️ {w}" for w in warnings)

    return {
        "content": content,
        "chart_data": json.loads(fig.to_json()),
        "metadata": {
            "method": "holt_winters",
            "date_column": date_col,
            "value_column": value_col,
            "frequency": freq,
            "n_periods": horizon,
            "forecast_values": forecast.values.tolist(),
            "forecast_index": fc_x,
            "explain": _build_explain(method, value_col, date_col, freq, len(series), horizon, last_val,
                                      next_val, pct, warnings, filename, sheet, getattr(fit, "aic", None)),
        },
    }


class ForecastAgent(BaseAgent):
    agent_type = "forecast"

    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        file_id, record = await self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response("No file loaded. Upload a file first.", "forecast")
        sheet = record.metadata.get("active_sheet") or "Sheet1"
        out = await self.cpu(run_forecast, record.df, query, record.metadata.get("semantic_map"), record.filename, sheet)
        if "error" in out:
            return AgentResponse.error_response(out["error"], "forecast")
        return AgentResponse(type="forecast", content=out["content"], chart_data=out["chart_data"], metadata=out["metadata"])
