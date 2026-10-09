from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import plotly.graph_objects as go


logger = logging.getLogger("VISUALIZER")


def _is_datetime_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return False

    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    valid_ratio = parsed.notna().mean() if len(parsed) else 0.0
    return valid_ratio >= 0.8


def _call_llm_text(llm_client: Any, prompt: str) -> str:
    if llm_client is None:
        raise ValueError("llm_client is required for summary generation")

    if hasattr(llm_client, "generate_text"):
        return str(llm_client.generate_text(prompt))
    if hasattr(llm_client, "invoke"):
        response = llm_client.invoke(prompt)
        return str(getattr(response, "content", response))
    if hasattr(llm_client, "complete"):
        return str(llm_client.complete(prompt))

    raise TypeError("Unsupported LLM client interface")


def select_chart_type(df: pd.DataFrame) -> str:
    if df.empty or df.shape == (1, 1):
        return "metric"

    numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    datetime_columns = [column for column in df.columns if _is_datetime_like(df[column])]
    categorical_columns = [column for column in df.columns if column not in numeric_columns and column not in datetime_columns]

    if len(df.columns) == 1 and len(numeric_columns) == 1 and len(df) > 1:
        return "histogram"

    if numeric_columns and categorical_columns and not datetime_columns:
        return "bar"

    if numeric_columns and datetime_columns and len(numeric_columns) == 1:
        return "line"

    if len(df.columns) == 2 and len(numeric_columns) == 1:
        numeric_column = numeric_columns[0]
        other_column = [column for column in df.columns if column != numeric_column][0]

        if other_column in datetime_columns:
            return "line"
        if other_column in categorical_columns:
            unique_count = df[other_column].nunique(dropna=True)
            if unique_count <= 6:
                return "pie"
            return "bar"

        return "histogram"

    if len(numeric_columns) == 1 and len(df) > 1:
        return "histogram"

    return "table"


def generate_plotly_chart(df: pd.DataFrame, chart_type: str, question: str) -> go.Figure:
    title = f"{question.strip()}" if question.strip() else "Query Results"

    if df.empty:
        figure = go.Figure()
        figure.add_annotation(text="No data returned", x=0.5, y=0.5, showarrow=False)
        figure.update_layout(title=title, template="plotly_white")
        return figure

    if chart_type == "metric":
        value = df.iloc[0, 0]
        figure = go.Figure(
            go.Indicator(
                mode="number",
                value=float(value) if isinstance(value, (int, float)) else 0.0,
                title={"text": title},
            )
        )
    elif chart_type == "bar":
        numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
        category_candidates = [column for column in df.columns if column not in numeric_columns and not _is_datetime_like(df[column])]
        category_column = category_candidates[0] if category_candidates else next(column for column in df.columns if column not in numeric_columns)

        figure = go.Figure()
        palette = ["#2F80ED", "#0F9D58", "#F2994A", "#9B51E0", "#EB5757", "#6C5CE7"]

        for index, numeric_column in enumerate(numeric_columns):
            figure.add_trace(
                go.Bar(
                    x=df[category_column].astype(str),
                    y=df[numeric_column],
                    name=numeric_column,
                    marker_color=palette[index % len(palette)],
                )
            )

        figure.update_layout(xaxis_title=category_column, yaxis_title="Value", barmode="group")
    elif chart_type == "histogram":
        numeric_column = next(column for column in df.columns if pd.api.types.is_numeric_dtype(df[column]))
        figure = go.Figure(
            data=[
                go.Histogram(
                    x=df[numeric_column],
                    marker_color="#6C5CE7",
                    nbinsx=min(max(len(df) // 2, 10), 30),
                )
            ]
        )
        figure.update_layout(xaxis_title=numeric_column, yaxis_title="Count")
    elif chart_type == "line":
        numeric_column = next(column for column in df.columns if pd.api.types.is_numeric_dtype(df[column]))
        date_column = next(column for column in df.columns if _is_datetime_like(df[column]))
        sorted_df = df.copy()
        sorted_df[date_column] = pd.to_datetime(sorted_df[date_column], errors="coerce", format="mixed")
        sorted_df = sorted_df.sort_values(date_column)
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=sorted_df[date_column],
                    y=sorted_df[numeric_column],
                    mode="lines+markers",
                    line=dict(color="#0F9D58", width=3),
                )
            ]
        )
        figure.update_layout(xaxis_title=date_column, yaxis_title=numeric_column)
    elif chart_type == "pie":
        numeric_column = next(column for column in df.columns if pd.api.types.is_numeric_dtype(df[column]))
        category_column = next(column for column in df.columns if column != numeric_column)
        figure = go.Figure(
            data=[
                go.Pie(
                    labels=df[category_column].astype(str),
                    values=df[numeric_column],
                    hole=0.25,
                )
            ]
        )
    else:
        figure = go.Figure(
            data=[
                go.Table(
                    header=dict(values=list(df.columns), fill_color="#1F4E79", font=dict(color="white")),
                    cells=dict(values=[df[column].astype(str) for column in df.columns]),
                )
            ]
        )

    figure.update_layout(title=title, template="plotly_white")
    return figure


def _fallback_summary(df: pd.DataFrame, question: str) -> str:
    if df.empty:
        return f"No rows were returned for the question: {question}."

    if df.shape == (1, 1):
        value = df.iloc[0, 0]
        return f"The query returns a single value of {value}."

    preview_columns = ", ".join(df.columns[:4])
    return (
        f"The result set contains {len(df)} rows and {len(df.columns)} columns, with key fields such as {preview_columns}. "
        "The pattern suggests a concise business answer that can be reviewed in the table or chart."
    )


def generate_summary(df: pd.DataFrame, question: str, llm_client: Any) -> str:
    preview_text = df.head(5).to_string(index=False)
    prompt = (
        "You are a business analyst writing for non-technical enterprise users. "
        "Write a concise 2-3 sentence summary of the query result.\n\n"
        f"Question: {question}\n"
        f"Rows: {len(df)}\n"
        f"Columns: {list(df.columns)}\n"
        f"Preview:\n{preview_text}\n\n"
        "Return only the summary text."
    )

    try:
        response = _call_llm_text(llm_client, prompt).strip()
        return response or _fallback_summary(df, question)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Summary generation failed: %s", exc)
        return _fallback_summary(df, question)
