"""
forecast_agent.py — Time-series forecasting using statsmodels.
Falls back to linear regression if no date column is detected.
"""

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import json

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.forecast")


def _find_date_column(df: pd.DataFrame) -> str | None:
    """Return the first column that looks like a date."""
    for col in df.columns:
        if any(kw in col.lower() for kw in ["date", "time", "month", "year", "week", "period", "day"]):
            try:
                pd.to_datetime(df[col], errors="raise")
                return col
            except Exception:
                pass
    # Try converting any object column
    for col in df.select_dtypes(include="object").columns:
        sample = df[col].dropna().head(20)
        converted = pd.to_datetime(sample, errors="coerce")
        if converted.notna().sum() / max(len(sample), 1) > 0.7:
            return col
    return None


def _find_numeric_column(df: pd.DataFrame, prefer: str | None = None) -> str | None:
    """Return the best numeric column to forecast."""
    num_cols = list(df.select_dtypes(include="number").columns)
    if not num_cols:
        return None
    if prefer and prefer in num_cols:
        return prefer
    # Pick column with most variance
    variances = {c: df[c].var() for c in num_cols}
    return max(variances, key=variances.get)


def _extract_periods(query: str) -> int:
    """Parse how many periods to forecast from the query."""
    import re
    match = re.search(r"(\d+)\s*(month|week|day|quarter|year|period)", query.lower())
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if unit == "quarter":
            return n * 3
        return n
    return 3  # default: 3 periods


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
            return AgentResponse.error_response(
                "No file loaded. Upload a file first.", "forecast"
            )

        df = record.df.copy()
        n_periods = _extract_periods(query)
        date_col = _find_date_column(df)
        value_col = _find_numeric_column(df)

        if not value_col:
            return AgentResponse.error_response(
                "No numeric columns found to forecast.", "forecast"
            )

        warnings: list[str] = []

        # ---- Path A: Time-series with date column ----
        if date_col:
            try:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col, value_col])
                df = df.sort_values(date_col)

                if len(df) < 6:
                    warnings.append("⚠️ Fewer than 6 data points — forecast may be unreliable.")

                # Infer frequency
                ts = df.set_index(date_col)[value_col].resample("ME").sum()
                if len(ts) < 3:
                    ts = df.set_index(date_col)[value_col]

                from statsmodels.tsa.holtwinters import ExponentialSmoothing

                # Fit Holt-Winters (triple exponential smoothing)
                model = ExponentialSmoothing(
                    ts,
                    trend="add",
                    seasonal="add" if len(ts) >= 24 else None,
                    seasonal_periods=12 if len(ts) >= 24 else None,
                )
                fit = model.fit(optimized=True)

                forecast = fit.forecast(n_periods)
                conf_int = fit.simulate(n_periods, repetitions=100, error="add")
                lower = conf_int.min(axis=1)
                upper = conf_int.max(axis=1)

                # Build Plotly figure
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=ts.index.astype(str).tolist(),
                        y=ts.values.tolist(),
                        name="Historical",
                        line=dict(color="#6366f1"),
                    )
                )
                forecast_dates = [str(d) for d in forecast.index]
                fig.add_trace(
                    go.Scatter(
                        x=forecast_dates,
                        y=forecast.values.tolist(),
                        name=f"Forecast (+{n_periods})",
                        line=dict(color="#f59e0b", dash="dash"),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=forecast_dates + forecast_dates[::-1],
                        y=upper.values.tolist() + lower.values.tolist()[::-1],
                        fill="toself",
                        fillcolor="rgba(245,158,11,0.15)",
                        line=dict(color="rgba(0,0,0,0)"),
                        name="Confidence Interval",
                    )
                )
                fig.update_layout(
                    title=f"Forecast: {value_col} (next {n_periods} periods)",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Inter, sans-serif"),
                    margin=dict(l=40, r=20, t=60, b=40),
                )
                plotly_spec = json.loads(fig.to_json())

                last_val = float(ts.iloc[-1])
                next_val = float(forecast.iloc[0])
                pct_change = ((next_val - last_val) / abs(last_val) * 100) if last_val != 0 else 0

                content = (
                    f"📈 **Forecast: {value_col}** (next {n_periods} month(s))\n\n"
                    f"- **Last known value:** {last_val:,.2f}\n"
                    f"- **Next period forecast:** {next_val:,.2f} ({'+' if pct_change >= 0 else ''}{pct_change:.1f}%)\n"
                    f"- **Method:** Holt-Winters Exponential Smoothing\n"
                )
                if warnings:
                    content += "\n" + "\n".join(warnings)

                return AgentResponse(
                    type="forecast",
                    content=content,
                    chart_data=plotly_spec,
                    metadata={
                        "method": "holt_winters",
                        "date_column": date_col,
                        "value_column": value_col,
                        "n_periods": n_periods,
                        "forecast_values": forecast.values.tolist(),
                    },
                )
            except Exception as e:
                logger.warning(f"Time-series forecast failed: {e} — falling back to linear regression")
                warnings.append(f"⚠️ Time-series model failed ({e}), using linear regression.")

        # ---- Path B: Linear regression fallback ----
        try:
            from sklearn.linear_model import LinearRegression

            y = df[value_col].dropna().values
            x = np.arange(len(y)).reshape(-1, 1)

            lr = LinearRegression()
            lr.fit(x, y)

            future_x = np.arange(len(y), len(y) + n_periods).reshape(-1, 1)
            future_y = lr.predict(future_x)

            # Simple confidence band: ±std of residuals
            residuals = y - lr.predict(x)
            std = residuals.std()

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(x=list(range(len(y))), y=y.tolist(), name="Historical", line=dict(color="#6366f1"))
            )
            fig.add_trace(
                go.Scatter(
                    x=list(range(len(y), len(y) + n_periods)),
                    y=future_y.tolist(),
                    name=f"Forecast (+{n_periods})",
                    line=dict(color="#f59e0b", dash="dash"),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=list(range(len(y), len(y) + n_periods)) + list(range(len(y) + n_periods - 1, len(y) - 1, -1)),
                    y=(future_y + std).tolist() + (future_y - std).tolist()[::-1],
                    fill="toself",
                    fillcolor="rgba(245,158,11,0.15)",
                    line=dict(color="rgba(0,0,0,0)"),
                    name="±1σ band",
                )
            )
            fig.update_layout(
                title=f"Linear Trend: {value_col} (next {n_periods} points)",
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif"),
                margin=dict(l=40, r=20, t=60, b=40),
            )
            plotly_spec = json.loads(fig.to_json())

            r2 = float(lr.score(x, y))
            pct_change = ((future_y[-1] - y[-1]) / abs(y[-1]) * 100) if y[-1] != 0 else 0

            content = (
                f"📈 **Linear Trend Forecast: {value_col}**\n\n"
                f"- **R² score:** {r2:.3f} ({'good fit' if r2 > 0.7 else 'weak fit — treat with caution'})\n"
                f"- **Predicted value in {n_periods} steps:** {future_y[-1]:,.2f} ({'+' if pct_change >= 0 else ''}{pct_change:.1f}%)\n"
                f"- **Method:** Linear Regression (no date column found)\n"
            )
            if warnings:
                content += "\n" + "\n".join(warnings)
            if not date_col:
                content += "\n\n> 💡 *Tip: Add a date/time column for more accurate time-series forecasting.*"

            return AgentResponse(
                type="forecast",
                content=content,
                chart_data=plotly_spec,
                metadata={
                    "method": "linear_regression",
                    "value_column": value_col,
                    "r2": r2,
                    "n_periods": n_periods,
                },
            )
        except Exception as e:
            return AgentResponse.error_response(
                f"Forecasting failed: {e}", "forecast"
            )
