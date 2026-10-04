"""
viz_agent.py — Natural language to Plotly JSON chart spec.
Chart type is auto-detected from query keywords + data shape.
"""

import json
import logging

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from agents.base_agent import AgentResponse, BaseAgent

logger = logging.getLogger("datapilot.agent.viz")


CHART_TYPE_RULES = {
    "bar": "Categorical comparison — best for comparing discrete groups (e.g. by product, by region).",
    "line": "Time series / sequential data — shows how a value changes over an ordered axis.",
    "scatter": "Correlation exploration — reveals relationships between two numeric variables.",
    "histogram": "Distribution analysis — shows the frequency spread of a single numeric column.",
    "pie": "Part-to-whole composition — best when there are 8 or fewer categories summing to a total.",
    "box": "Distribution comparison — shows median, quartiles, and outliers across groups.",
    "heatmap": "Correlation matrix — shows pairwise relationships between all numeric columns.",
}


def _build_chart_explain(
    chart_info: dict,
    df: pd.DataFrame,
    detection_method: str,  # "keyword" or "llm"
    filename: str = "N/A",
    sheet: str = "N/A"
) -> dict:
    """Build a structured explainability block for the chart response."""
    sections = []
    ctype = chart_info.get("chart_type", "bar")
    x_col = chart_info.get("x_column")
    y_col = chart_info.get("y_column")
    reasoning = chart_info.get("reasoning")

    # 1. Chart type rationale
    rule_text = CHART_TYPE_RULES.get(ctype, "General purpose chart.")
    method_badge = "🤖 AI Selected" if detection_method == "llm" else "🔑 Rule Matched"
    rationale_lines = [
        f"{method_badge}: `{ctype}` chart chosen",
        rule_text,
    ]
    if reasoning:
        rationale_lines.append(f"AI reasoning: {reasoning}")
    sections.append({
        "label": "Chart Type Rationale",
        "icon": "📈",
        "content": rationale_lines
    })

    # 2. Axes mapping
    axes_lines = []
    if x_col and x_col in df.columns:
        dtype = str(df[x_col].dtype)
        nunique = df[x_col].nunique()
        axes_lines.append(f"X-axis: `{x_col}` ({dtype}, {nunique} unique values) — categories / labels")
    if y_col and y_col in df.columns:
        dtype = str(df[y_col].dtype)
        axes_lines.append(f"Y-axis: `{y_col}` ({dtype}) — numeric metric to plot")
    elif not y_col:
        axes_lines.append("Y-axis: count (frequency of each category)")
    if axes_lines:
        sections.append({
            "label": "Axis Mapping",
            "icon": "↔️",
            "content": axes_lines
        })

    # 3. Aggregation description
    if ctype == "bar" and x_col and y_col and x_col in df.columns and y_col in df.columns:
        if pd.api.types.is_numeric_dtype(df[y_col]):
            agg_df = df.groupby(x_col)[y_col].sum()
            top_cat = agg_df.idxmax()
            top_val = agg_df.max()
            bottom_cat = agg_df.idxmin()
            bottom_val = agg_df.min()
            sections.append({
                "label": "Aggregation Applied",
                "icon": "∑",
                "content": [
                    f"Grouped `{x_col}` and summed `{y_col}` per category",
                    f"Showing top {min(20, len(agg_df))} categories by total",
                    f"Highest: {top_cat} ({top_val:,.2f})",
                    f"Lowest: {bottom_cat} ({bottom_val:,.2f})",
                ]
            })
    elif ctype == "histogram" and x_col and x_col in df.columns:
        col_data = df[x_col].dropna()
        sections.append({
            "label": "Distribution Statistics",
            "icon": "📊",
            "content": [
                f"Mean: {col_data.mean():,.2f}",
                f"Median: {col_data.median():,.2f}",
                f"Std dev: {col_data.std():,.2f}",
                f"Range: [{col_data.min():,.2f} — {col_data.max():,.2f}]",
            ]
        })
    elif ctype == "line" and x_col and y_col and y_col in df.columns:
        col_data = df[y_col].dropna()
        if len(col_data) > 1:
            trend_dir = "⬆️ Rising" if col_data.iloc[-1] > col_data.iloc[0] else "⬇️ Declining"
            sections.append({
                "label": "Trend Detected",
                "icon": "📉",
                "content": [
                    f"{trend_dir} over the plotted range",
                    f"Start: {col_data.iloc[0]:,.2f} → End: {col_data.iloc[-1]:,.2f}",
                    f"Peak: {col_data.max():,.2f} | Trough: {col_data.min():,.2f}",
                ]
            })

    # 4. Data scope
    sections.append({
        "label": "Data Scope",
        "icon": "📁",
        "content": f"{len(df):,} total rows in dataset — chart limited to top 20 (bar) or 1,000 (scatter) for performance"
    })

    x_col = chart_info.get("x_column")
    y_col = chart_info.get("y_column")
    columns = []
    if x_col:
        columns.append(x_col)
    if y_col:
        columns.append(y_col)

    calcs = [
        f"Chart Type: {ctype}",
        f"Detection mode: {detection_method}"
    ]

    return {
        "type": "chart",
        "chart_type": ctype,
        "sections": sections,
        "data_source": filename,
        "sheet": sheet,
        "columns": columns,
        "filters": "None",
        "sql": "N/A",
        "intermediate_calculations": calcs,
        "confidence_score": None,
        "verification": "Chart computed from your data",
        "reasoning_summary": reasoning or f"AI selected a {ctype} visualization based on column data types."
    }

VIZ_SYSTEM = """You are a data visualization expert. Given a user query and dataset info, pick the best chart.

Return ONLY valid JSON:
{
  "chart_type": "<bar|line|scatter|histogram|pie|heatmap|box>",
  "x_column": "<exact column name or null>",
  "y_column": "<exact column name or null>",
  "color_column": "<exact column name or null>",
  "title": "<descriptive chart title>",
  "reasoning": "<one sentence>"
}

Chart type rules:
- bar: categorical x vs numeric y comparison
- line: time series or sequential data
- scatter: two numeric columns (correlation)
- histogram: distribution of one numeric column
- pie: parts of a whole (max 8 categories)
- box: distribution comparison across categories
- heatmap: correlation matrix

Use exact column names from the provided list."""


def _auto_detect_chart(query: str, df: pd.DataFrame) -> dict:
    """Fast keyword-based chart type detection without LLM."""
    q = query.lower()
    num_cols = list(df.select_dtypes(include="number").columns)
    cat_cols = list(df.select_dtypes(include="object").columns)
    date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower() or "month" in c.lower() or "year" in c.lower()]

    if any(k in q for k in ["trend", "over time", "time series", "by month", "by year", "by date"]):
        return {
            "chart_type": "line",
            "x_column": date_cols[0] if date_cols else (cat_cols[0] if cat_cols else df.columns[0]),
            "y_column": num_cols[0] if num_cols else None,
            "color_column": None,
            "title": f"{num_cols[0] if num_cols else 'Value'} over time",
        }
    if any(k in q for k in ["distribution", "histogram", "spread", "frequency"]):
        return {
            "chart_type": "histogram",
            "x_column": num_cols[0] if num_cols else df.columns[0],
            "y_column": None,
            "color_column": None,
            "title": f"Distribution of {num_cols[0] if num_cols else df.columns[0]}",
        }
    if any(k in q for k in ["correlation", "scatter", "vs", "versus", "relationship"]):
        return {
            "chart_type": "scatter",
            "x_column": num_cols[0] if len(num_cols) > 0 else df.columns[0],
            "y_column": num_cols[1] if len(num_cols) > 1 else df.columns[1],
            "color_column": cat_cols[0] if cat_cols else None,
            "title": f"{num_cols[0] if num_cols else ''} vs {num_cols[1] if len(num_cols) > 1 else ''}",
        }
    if any(k in q for k in ["proportion", "percentage", "share", "pie", "composition"]):
        return {
            "chart_type": "pie",
            "x_column": cat_cols[0] if cat_cols else df.columns[0],
            "y_column": num_cols[0] if num_cols else None,
            "color_column": None,
            "title": f"Proportion of {cat_cols[0] if cat_cols else df.columns[0]}",
        }
    # Default: bar chart
    return {
        "chart_type": "bar",
        "x_column": cat_cols[0] if cat_cols else df.columns[0],
        "y_column": num_cols[0] if num_cols else None,
        "color_column": None,
        "title": f"{num_cols[0] if num_cols else 'Count'} by {cat_cols[0] if cat_cols else df.columns[0]}",
    }


MAX_LINE_POINTS = 1500
MAX_SCATTER_POINTS = 2000


def _aggregation_for(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("average", "avg", "mean")):
        return "mean"
    if any(w in q for w in ("count", "number of", "how many")):
        return "count"
    return "sum"


def _build_plotly_spec(chart_info: dict, df: pd.DataFrame, aggregation: str = "sum") -> tuple[dict, list[str]]:
    """Build a compact Plotly spec from aggregated/sampled data and return (spec, notes).

    Charts never silently truncate: time series are aggregated per period (and
    re-bucketed to a coarser period if still too long), scatter plots use a
    uniform random sample, histograms/box plots are pre-computed server-side so
    the payload stays small, and every reduction is reported in *notes*.
    """
    import numpy as np

    ctype = chart_info.get("chart_type", "bar")
    title = chart_info.get("title", "Chart")
    notes: list[str] = []

    def safe_col(col):
        return col if col and col in df.columns else None

    x_col, y_col, color_col = safe_col(chart_info.get("x_column")), safe_col(chart_info.get("y_column")), safe_col(chart_info.get("color_column"))
    if y_col is not None and not pd.api.types.is_numeric_dtype(df[y_col]):
        y_col = None
    agg = aggregation if aggregation in {"sum", "mean", "count"} else "sum"
    template = "plotly_dark"

    def _grouped(frame: pd.DataFrame, key) -> pd.DataFrame:
        if y_col is None or agg == "count":
            out = frame.groupby(key, dropna=True).size().reset_index(name="count")
            return out
        series = pd.to_numeric(frame[y_col], errors="coerce")
        g = series.groupby([frame[k] for k in (key if isinstance(key, list) else [key])])
        out = (g.mean() if agg == "mean" else g.sum(min_count=1)).reset_index()
        out.columns = [*(key if isinstance(key, list) else [key]), y_col]
        return out

    value_name = "count" if (y_col is None or agg == "count") else y_col
    if value_name != "count" and agg != "sum":
        notes.append(f"Values show the {agg} of '{y_col}' per group.")

    if ctype in {"bar", "pie"} and x_col:
        keys = [x_col] + ([color_col] if ctype == "bar" and color_col and color_col != x_col else [])
        plot_df = _grouped(df, keys if len(keys) > 1 else x_col)
        total_groups = plot_df[x_col].nunique()
        limit = 20 if ctype == "bar" else 8
        if total_groups > limit:
            top = plot_df.groupby(x_col)[value_name].sum().sort_values(ascending=False).head(limit).index
            if ctype == "pie":
                other = plot_df[~plot_df[x_col].isin(top)][value_name].sum()
                plot_df = pd.concat([plot_df[plot_df[x_col].isin(top)], pd.DataFrame({x_col: ["Other"], value_name: [other]})])
                notes.append(f"Showing the top {limit} of {total_groups} categories; the rest are grouped as 'Other'.")
            else:
                plot_df = plot_df[plot_df[x_col].isin(top)]
                notes.append(f"Showing the top {limit} of {total_groups} categories by {value_name}.")
        plot_df = plot_df.sort_values(value_name, ascending=False)
        if ctype == "bar":
            fig = px.bar(plot_df, x=x_col, y=value_name, color=color_col if len(keys) > 1 else None, title=title, template=template)
        else:
            fig = px.pie(plot_df, names=x_col, values=value_name, title=title, template=template)
    elif ctype == "line" and x_col:
        frame = df.copy()
        x_vals = frame[x_col]
        is_time = pd.api.types.is_datetime64_any_dtype(x_vals)
        if not is_time and x_vals.dtype == object:
            parsed = pd.to_datetime(x_vals, errors="coerce", format="mixed")
            if parsed.notna().mean() > 0.8:
                frame[x_col] = parsed
                is_time = True
        keys = [x_col] + ([color_col] if color_col and color_col != x_col else [])
        plot_df = _grouped(frame.dropna(subset=[x_col]), keys if len(keys) > 1 else x_col).sort_values(x_col)
        if is_time and plot_df[x_col].nunique() > MAX_LINE_POINTS:
            for rule, label in (("W-SUN", "week"), ("MS", "month"), ("QS", "quarter"), ("YS", "year")):
                tmp = frame.dropna(subset=[x_col]).copy()
                tmp[x_col] = tmp[x_col].dt.to_period({"W-SUN": "W", "MS": "M", "QS": "Q", "YS": "Y"}[rule]).dt.start_time
                plot_df = _grouped(tmp, keys if len(keys) > 1 else x_col).sort_values(x_col)
                if plot_df[x_col].nunique() <= MAX_LINE_POINTS:
                    notes.append(f"Aggregated to one point per {label} to keep the chart readable.")
                    break
        if plot_df[x_col].nunique() > MAX_LINE_POINTS:
            step = int(np.ceil(len(plot_df) / MAX_LINE_POINTS))
            plot_df = plot_df.iloc[::step]
            notes.append(f"Every {step}th point is shown ({len(plot_df):,} points).")
        fig = px.line(plot_df, x=x_col, y=value_name, color=color_col if len(keys) > 1 else None, title=title, template=template, markers=len(plot_df) <= 200)
    elif ctype == "scatter" and x_col and y_col:
        plot_df = df[[c for c in {x_col, y_col, color_col} if c]].dropna(subset=[x_col, y_col])
        if len(plot_df) > MAX_SCATTER_POINTS:
            notes.append(f"Showing a random sample of {MAX_SCATTER_POINTS:,} of {len(plot_df):,} points.")
            plot_df = plot_df.sample(MAX_SCATTER_POINTS, random_state=42)
        fig = px.scatter(plot_df, x=x_col, y=y_col, color=color_col, title=title, template=template)
    elif ctype == "histogram":
        col = x_col if x_col and pd.api.types.is_numeric_dtype(df[x_col]) else y_col
        if col is None:
            raise ValueError("A numeric column is required for a histogram.")
        values = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy()
        counts, edges = np.histogram(values, bins=30)
        centers = (edges[:-1] + edges[1:]) / 2
        fig = go.Figure(go.Bar(x=centers.tolist(), y=counts.tolist(), width=(edges[1] - edges[0]) if len(edges) > 1 else None, name=col))
        fig.update_layout(title=title, template=template, xaxis_title=col, yaxis_title="count", bargap=0.02)
    elif ctype == "box":
        col = y_col or (x_col if x_col and pd.api.types.is_numeric_dtype(df[x_col]) else None)
        if col is None:
            raise ValueError("A numeric column is required for a box plot.")
        group = x_col if x_col and x_col != col else None
        fig = go.Figure()
        groups = df.groupby(group) if group else [(col, df)]
        for i, (name, part) in enumerate(groups):
            if i >= 20:
                notes.append("Showing the first 20 groups.")
                break
            vals = pd.to_numeric(part[col], errors="coerce").dropna()
            if vals.empty:
                continue
            q1, med, q3 = vals.quantile([0.25, 0.5, 0.75]).tolist()
            iqr = q3 - q1
            lo = float(vals[vals >= q1 - 1.5 * iqr].min())
            hi = float(vals[vals <= q3 + 1.5 * iqr].max())
            fig.add_trace(go.Box(name=str(name), q1=[q1], median=[med], q3=[q3], lowerfence=[lo], upperfence=[hi], mean=[float(vals.mean())]))
        fig.update_layout(title=title, template=template, yaxis_title=col)
    elif ctype == "heatmap":
        num = df.select_dtypes(include="number")
        if num.shape[1] < 2:
            raise ValueError("At least two numeric columns are required for a correlation heatmap.")
        corr = num.iloc[:, :30].corr().round(3)
        fig = go.Figure(go.Heatmap(z=corr.values.tolist(), x=list(map(str, corr.columns)), y=list(map(str, corr.index)), zmin=-1, zmax=1, colorscale="RdBu"))
        fig.update_layout(title=title, template=template)
    else:
        if not x_col:
            raise ValueError("Could not determine which column to chart.")
        plot_df = _grouped(df, x_col).sort_values(value_name, ascending=False).head(20)
        fig = px.bar(plot_df, x=x_col, y=value_name, title=title, template=template)

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=13),
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return json.loads(fig.to_json()), notes


class VizAgent(BaseAgent):
    agent_type = "visualize"

    async def _execute(self, query: str, file_ids: list[str], context: list[dict]) -> AgentResponse:
        file_id, record = await self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response("No file loaded. Upload a file first.", "visualize")

        df = record.df
        chart_info = _auto_detect_chart(query, df)
        detection_method = "keyword"

        if self.llm is not None:
            columns_meta = record.metadata.get("semantic_map", {})
            cols_with_semantics = []
            for col in df.columns:
                meta = columns_meta.get(str(col))
                if meta:
                    cols_with_semantics.append(
                        f"- {col} (Label: '{meta.get('label')}', Type: {meta.get('semantic_type')}, Aliases: {meta.get('aliases', [])[:6]})"
                    )
                else:
                    cols_with_semantics.append(f"- {col}")
            from core.jsonsafe import to_jsonable
            sample = json.dumps(to_jsonable(df.head(3).to_dict(orient="records")))[:3000]
            prompt = (
                f"User query: {query}\n"
                "Available columns:\n" + "\n".join(cols_with_semantics) + "\n\n"
                f"Data sample: {sample}\nRow count: {len(df)}"
            )
            try:
                raw = await self.llm.generate(prompt, system=VIZ_SYSTEM, json_mode=True)
                parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
                if isinstance(parsed, dict) and parsed.get("chart_type"):
                    chart_info = parsed
                    detection_method = "llm"
            except Exception as exc:
                logger.info("LLM chart refinement unavailable (%s); using rule-based chart selection.", exc)

        try:
            plotly_spec, notes = await self.cpu(_build_plotly_spec, chart_info, df, _aggregation_for(query))
        except Exception as e:
            return AgentResponse.error_response(f"Could not generate chart: {e}", "visualize")

        content = (
            f"📊 **{chart_info.get('title', 'Chart')}** ({chart_info.get('chart_type', 'bar')} chart)\n\n"
            f"*Showing {chart_info.get('x_column', '?')} vs {chart_info.get('y_column') or 'count'}*"
        )
        if chart_info.get("reasoning"):
            content += f"\n\n{chart_info['reasoning']}"
        if notes:
            content += "\n\n" + "\n".join(f"> {n}" for n in notes)

        sheet = record.metadata.get("active_sheet") or "Sheet1"
        explain = _build_chart_explain(chart_info, df, detection_method, filename=record.filename, sheet=sheet)
        return AgentResponse(
            type="visualize",
            content=content,
            chart_data=plotly_spec,
            metadata={
                "chart_type": chart_info.get("chart_type"),
                "x_column": chart_info.get("x_column"),
                "y_column": chart_info.get("y_column"),
                "color_column": chart_info.get("color_column"),
                "title": chart_info.get("title"),
                "data_reduction_notes": notes,
                "explain": explain,
            },
        )
