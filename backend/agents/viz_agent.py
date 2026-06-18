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
) -> dict:
    """Build a structured explainability block for the chart response."""
    sections = []
    ctype = chart_info.get("chart_type", "bar")
    x_col = chart_info.get("x_column")
    y_col = chart_info.get("y_column")
    title = chart_info.get("title", "Chart")
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

    return {
        "type": "chart",
        "chart_type": ctype,
        "sections": sections
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


def _build_plotly_spec(chart_info: dict, df: pd.DataFrame) -> dict:
    """Build Plotly JSON-serializable figure spec."""
    ctype = chart_info.get("chart_type", "bar")
    x_col = chart_info.get("x_column")
    y_col = chart_info.get("y_column")
    color_col = chart_info.get("color_column")
    title = chart_info.get("title", "Chart")

    # Validate columns exist
    def safe_col(col):
        return col if col and col in df.columns else None

    x_col = safe_col(x_col)
    y_col = safe_col(y_col)
    color_col = safe_col(color_col)

    # Aggregate for bar chart if needed (group by x, sum y)
    plot_df = df.copy()
    if ctype == "bar" and x_col and y_col and pd.api.types.is_numeric_dtype(df[y_col]):
        plot_df = df.groupby(x_col, as_index=False)[y_col].sum()
        plot_df = plot_df.sort_values(y_col, ascending=False).head(20)

    # Limit pie to 8 slices
    if ctype == "pie" and x_col:
        top_cats = df[x_col].value_counts().head(8).index
        plot_df = df[df[x_col].isin(top_cats)]

    TEMPLATE = "plotly_dark"

    try:
        if ctype == "bar":
            fig = px.bar(plot_df, x=x_col, y=y_col, color=color_col, title=title, template=TEMPLATE)
        elif ctype == "line":
            fig = px.line(plot_df.head(500), x=x_col, y=y_col, color=color_col, title=title, template=TEMPLATE, markers=True)
        elif ctype == "scatter":
            fig = px.scatter(plot_df.head(1000), x=x_col, y=y_col, color=color_col, title=title, template=TEMPLATE)
        elif ctype == "histogram":
            fig = px.histogram(plot_df, x=x_col, title=title, template=TEMPLATE, nbins=30)
        elif ctype == "pie":
            fig = px.pie(plot_df, names=x_col, values=y_col, title=title, template=TEMPLATE)
        elif ctype == "box":
            fig = px.box(plot_df, x=x_col, y=y_col, color=color_col, title=title, template=TEMPLATE)
        else:
            fig = px.bar(plot_df, x=x_col, y=y_col, title=title, template=TEMPLATE)

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", size=13),
            margin=dict(l=40, r=20, t=60, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        return json.loads(fig.to_json())
    except Exception as e:
        logger.error(f"Plotly build error: {e}")
        raise


class VizAgent(BaseAgent):
    agent_type = "visualize"

    async def _execute(
        self,
        query: str,
        file_ids: list[str],
        context: list[dict],
    ) -> AgentResponse:
        file_id, record = self._get_primary_file(file_ids)
        if not record:
            return AgentResponse.error_response(
                "No file loaded. Upload a file first.", "visualize"
            )

        df = record.df

        # Step 1: Fast keyword detection
        chart_info = _auto_detect_chart(query, df)

        # Step 2: If Ollama/LLM available, refine with LLM for better accuracy
        if self.llm:
            columns_meta = record.metadata.get("semantic_map", {})
            cols_with_semantics = []
            for col in df.columns:
                meta = columns_meta.get(str(col))
                if meta:
                    desc = f"- {col} (Label: '{meta.get('label')}', Type: {meta.get('semantic_type')}, Meaning: '{meta.get('inferred_meaning')}', Aliases: {meta.get('aliases', [])})"
                else:
                    desc = f"- {col}"
                cols_with_semantics.append(desc)

            sample = df.head(3).to_dict(orient="records")
            prompt = (
                f"User query: {query}\n"
                f"Available columns with semantic business intelligence mappings:\n" + "\n".join(cols_with_semantics) + "\n\n"
                f"Data sample: {sample}\n"
                f"Row count: {len(df)}"
            )
            raw = await self.llm.generate(prompt, system=VIZ_SYSTEM, json_mode=True)
            try:
                parsed = json.loads(raw)
                if "chart_type" in parsed:
                    chart_info = parsed
                    logger.info(f"LLM refined chart: {chart_info['chart_type']}")
            except (json.JSONDecodeError, TypeError):
                logger.debug("LLM chart refinement failed, using keyword detection")

        # Build Plotly JSON spec
        try:
            plotly_spec = _build_plotly_spec(chart_info, df)
        except Exception as e:
            return AgentResponse.error_response(
                f"Could not generate chart: {e}", "visualize"
            )

        content = (
            f"📊 **{chart_info.get('title', 'Chart')}** ({chart_info.get('chart_type', 'bar')} chart)\n\n"
            f"*Showing {chart_info.get('x_column', '?')} vs {chart_info.get('y_column', 'count')}*"
        )
        if "reasoning" in chart_info:
            content += f"\n\n{chart_info['reasoning']}"

        detection_method = "llm" if self.llm and "reasoning" in chart_info else "keyword"
        explain = _build_chart_explain(chart_info, df, detection_method)

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
                "explain": explain,
            },
        )
