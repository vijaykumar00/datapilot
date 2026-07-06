"""
forecast_agent.py — Time-series forecasting using statsmodels.
Falls back to linear regression if no date column is detected or data is too small.
"""

import json
import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.forecast")


def _build_forecast_explain(
    method: str,
    value_col: str,
    date_col: str | None,
    n_periods: int,
    n_points: int,
    r2: float | None,
    last_val: float,
    next_val: float,
    pct_change: float,
    resample_freq: str | None,
    warnings: list[str],
    filename: str = "N/A",
    sheet: str = "N/A"
) -> dict:
    """Build a structured explainability block for the forecast response."""
    sections = []

    # 1. Method selected + rationale
    if method == "holt_winters":
        method_label = "Holt-Winters Exponential Smoothing"
        method_desc = (
            f"Selected because {n_points} monthly data points were available (minimum 8 required). "
            "This method captures level, trend, and seasonal components for accurate short-term projections."
        )
    else:
        method_label = "Linear Regression (Fallback)"
        reason = "no date column was detected" if not date_col else f"only {n_points} data points available (need 8+ for time-series)"
        method_desc = (
            f"Fallback method selected because {reason}. "
            "Fits a straight-line trend to the numeric series. "
            f"R² = {r2:.3f} {'(good fit)' if r2 and r2 > 0.7 else '(weak fit — interpret carefully)'}." if r2 is not None else ""
        )
    sections.append({
        "label": "Method Selected",
        "icon": "🧪",
        "content": [method_label, method_desc]
    })

    # 2. Data basis
    basis_lines = [f"Column forecasted: `{value_col}`", f"Historical data points used: {n_points}"]
    if date_col:
        basis_lines.append(f"Date column detected: `{date_col}`")
        if resample_freq:
            basis_lines.append(f"Resampled to monthly frequency (ME) for time-series alignment")
    else:
        basis_lines.append("No date column found — using row index as time axis")
    basis_lines.append(f"Forecasting {n_periods} period(s) forward")
    sections.append({
        "label": "Data Basis",
        "icon": "📊",
        "content": basis_lines
    })

    # 3. Trend direction
    direction = "⬆️ Rising" if pct_change > 1 else ("⬇️ Declining" if pct_change < -1 else "➡️ Flat")
    trend_text = (
        f"{direction} — last value was {last_val:,.2f}, next forecast period is {next_val:,.2f} "
        f"({'+'  if pct_change >= 0 else ''}{pct_change:.1f}%)"
    )
    sections.append({
        "label": "Detected Trend",
        "icon": "📈",
        "content": trend_text
    })

    # 4. Confidence interpretation
    if method == "holt_winters":
        conf_text = (
            "The shaded band represents the 95% confidence interval, computed from the model’s "
            "residual standard deviation (±1.96σ). Values are expected to fall within this range "
            "with 95% probability under stable conditions."
        )
    else:
        conf_text = (
            "The shaded band represents ±1 standard deviation from the residuals of the linear fit. "
            "A wider band indicates higher uncertainty. Consider adding a date column for more reliable forecasts."
        )
    sections.append({
        "label": "Confidence Interpretation",
        "icon": "🛡️",
        "content": conf_text
    })

    # 5. Warnings if any
    if warnings:
        sections.append({
            "label": "Notices",
            "icon": "⚠️",
            "content": warnings
        })

    columns = [value_col]
    if date_col:
        columns.append(date_col)

    calcs = [
        f"Historical data points: {n_points}",
        f"Forecast periods: {n_periods}",
        f"R² coefficient: {r2:.3f}" if r2 is not None else "No R² fit statistics available"
    ]

    return {
        "type": "forecast",
        "sections": sections,
        "data_source": filename,
        "sheet": sheet,
        "columns": columns,
        "filters": "None",
        "sql": "N/A",
        "intermediate_calculations": calcs,
        "confidence_score": 0.95 if method == "holt_winters" else (min(0.90, max(0.50, r2)) if r2 is not None else 0.80),
        "reasoning_summary": f"Computed short-term forecasts using the {method} method on '{value_col}'."
    }


def _find_date_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if any(kw in col.lower() for kw in ["date", "time", "month", "year", "week", "period", "day"]):
            try:
                pd.to_datetime(df[col], errors="raise")
                return col
            except Exception:
                pass
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(20)
        converted = pd.to_datetime(sample, errors="coerce")
        if converted.notna().sum() / max(len(sample), 1) > 0.7:
            return col
    return None


def _find_numeric_column(df: pd.DataFrame) -> str | None:
    num_cols = list(df.select_dtypes(include="number").columns)
    if not num_cols:
        return None
    variances = {c: df[c].var() for c in num_cols}
    return max(variances, key=variances.get)


def _extract_periods(query: str) -> int:
    import re
    match = re.search(r"(\d+)\s*(month|week|day|quarter|year|period)", query.lower())
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        return n * 3 if unit == "quarter" else n
    return 3


class ForecastAgent(BaseAgent):
    agent_type = "forecast"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response("No file loaded. Upload a file first.", "forecast")

        df = record.df.copy()
        n_periods = _extract_periods(query)
        date_col = _find_date_column(df)
        value_col = _find_numeric_column(df)

        if not value_col:
            return AgentResponse.error_response("No numeric columns found to forecast.", "forecast")

        warnings: list[str] = []

        # ── Path A: Time-series with date column ─────────────────────────────
        if date_col:
            try:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col, value_col])
                df = df.sort_values(date_col)

                # Resample to monthly
                ts = df.set_index(date_col)[value_col].resample("ME").sum()
                if len(ts) < 3:
                    ts = df.set_index(date_col)[value_col]

                # Need >= 8 points for reliable Holt-Winters
                if len(ts) < 8:
                    warnings.append(f"Only {len(ts)} monthly data points — using linear regression.")
                    raise ValueError("Too few points for Holt-Winters")

                from statsmodels.tsa.holtwinters import ExponentialSmoothing

                model = ExponentialSmoothing(
                    ts,
                    trend="add",
                    seasonal="add" if len(ts) >= 24 else None,
                    seasonal_periods=12 if len(ts) >= 24 else None,
                )
                fit = model.fit(optimized=True)
                forecast = fit.forecast(n_periods)

                # Fast analytical 95% CI using residual std (no simulation)
                resid_std = float(fit.resid.std())
                z = 1.96
                lower_vals = forecast.values - z * resid_std
                upper_vals = forecast.values + z * resid_std
                forecast_dates = [str(d) for d in forecast.index]

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=ts.index.astype(str).tolist(), y=ts.values.tolist(),
                    name="Historical", line=dict(color="#6366f1", width=2)
                ))
                fig.add_trace(go.Scatter(
                    x=forecast_dates, y=forecast.values.tolist(),
                    name=f"Forecast (+{n_periods})",
                    line=dict(color="#f59e0b", dash="dash", width=2)
                ))
                fig.add_trace(go.Scatter(
                    x=forecast_dates + forecast_dates[::-1],
                    y=upper_vals.tolist() + lower_vals.tolist()[::-1],
                    fill="toself", fillcolor="rgba(245,158,11,0.12)",
                    line=dict(color="rgba(0,0,0,0)"), name="95% CI"
                ))
                fig.update_layout(
                    title=f"Forecast: {value_col} (next {n_periods} period(s))",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Inter, sans-serif"),
                    margin=dict(l=40, r=20, t=60, b=40),
                )
                plotly_spec = json.loads(fig.to_json())

                last_val = float(ts.iloc[-1])
                next_val = float(forecast.iloc[0])
                pct = ((next_val - last_val) / abs(last_val) * 100) if last_val != 0 else 0

                content = (
                    f"**Forecast: {value_col}** (next {n_periods} month(s))\n\n"
                    f"- **Last value:** {last_val:,.2f}\n"
                    f"- **Next period:** {next_val:,.2f} ({'+' if pct >= 0 else ''}{pct:.1f}%)\n"
                    f"- **Method:** Holt-Winters Exponential Smoothing\n"
                    f"- **Confidence:** 95% interval shown\n"
                )
                if warnings:
                    content += "\n" + "\n".join(warnings)

                filename = record.filename if record else "N/A"
                sheet = record.metadata.get("active_sheet") or "Sheet1" if record else "N/A"
                explain = _build_forecast_explain(
                    method="holt_winters",
                    value_col=value_col,
                    date_col=date_col,
                    n_periods=n_periods,
                    n_points=len(ts),
                    r2=None,
                    last_val=last_val,
                    next_val=next_val,
                    pct_change=pct,
                    resample_freq="ME",
                    warnings=warnings,
                    filename=filename,
                    sheet=sheet
                )

                return AgentResponse(
                    type="forecast", content=content, chart_data=plotly_spec,
                    metadata={
                        "method": "holt_winters", "date_column": date_col,
                        "value_column": value_col, "n_periods": n_periods,
                        "forecast_values": forecast.values.tolist(),
                        "explain": explain,
                    },
                )
            except Exception as e:
                logger.warning(f"Time-series forecast failed: {e} — falling back to linear regression")
                if not warnings:
                    warnings.append(f"Time-series model unavailable, using linear regression.")

        # ── Path B: Linear regression fallback ───────────────────────────────
        try:
            from sklearn.linear_model import LinearRegression

            y = df[value_col].dropna().values
            x = np.arange(len(y)).reshape(-1, 1)

            lr = LinearRegression()
            lr.fit(x, y)

            future_x = np.arange(len(y), len(y) + n_periods).reshape(-1, 1)
            future_y = lr.predict(future_x)

            residuals = y - lr.predict(x)
            std = residuals.std()

            hist_x = list(range(len(y)))
            fore_x = list(range(len(y), len(y) + n_periods))

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_x, y=y.tolist(), name="Historical",
                line=dict(color="#6366f1", width=2)
            ))
            fig.add_trace(go.Scatter(
                x=fore_x, y=future_y.tolist(),
                name=f"Forecast (+{n_periods})",
                line=dict(color="#f59e0b", dash="dash", width=2)
            ))
            fig.add_trace(go.Scatter(
                x=fore_x + fore_x[::-1],
                y=(future_y + std).tolist() + (future_y - std).tolist()[::-1],
                fill="toself", fillcolor="rgba(245,158,11,0.12)",
                line=dict(color="rgba(0,0,0,0)"), name="±1σ band"
            ))
            fig.update_layout(
                title=f"Linear Trend: {value_col} (next {n_periods} steps)",
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif"),
                margin=dict(l=40, r=20, t=60, b=40),
            )
            plotly_spec = json.loads(fig.to_json())

            r2 = float(lr.score(x, y))
            pct = ((future_y[-1] - y[-1]) / abs(y[-1]) * 100) if y[-1] != 0 else 0

            content = (
                f"**Linear Trend Forecast: {value_col}**\n\n"
                f"- **R² score:** {r2:.3f} ({'good fit' if r2 > 0.7 else 'weak fit — interpret carefully'})\n"
                f"- **In {n_periods} steps:** {future_y[-1]:,.2f} ({'+' if pct >= 0 else ''}{pct:.1f}%)\n"
                f"- **Method:** Linear Regression\n"
            )
            if warnings:
                content += "\n" + "\n".join(warnings)
            if not date_col:
                content += "\n\n> Tip: Add a date/time column for better time-series forecasting."

            filename = record.filename if record else "N/A"
            sheet = record.metadata.get("active_sheet") or "Sheet1" if record else "N/A"
            explain = _build_forecast_explain(
                method="linear_regression",
                value_col=value_col,
                date_col=date_col,
                n_periods=n_periods,
                n_points=len(y),
                r2=r2,
                last_val=float(y[-1]),
                next_val=float(future_y[-1]),
                pct_change=pct,
                resample_freq=None,
                warnings=warnings,
                filename=filename,
                sheet=sheet
            )

            return AgentResponse(
                type="forecast", content=content, chart_data=plotly_spec,
                metadata={
                    "method": "linear_regression", "value_column": value_col,
                    "r2": r2, "n_periods": n_periods,
                    "explain": explain,
                },
            )
        except Exception as e:
            return AgentResponse.error_response(f"Forecasting failed: {e}", "forecast")
