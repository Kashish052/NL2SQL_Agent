from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import re
import sqlite3
import threading
import time

import pandas as pd
import plotly.io as pio
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from agent import build_agent_graph, load_llm_client
from retriever import build_index, extract_schema
from setup_db import DB_PATH, create_database
from visualizer import generate_plotly_chart, generate_summary, select_chart_type


load_dotenv()

APP_TITLE = "NL2SQL Studio"
DEFAULT_COLLECTION_NAME = "enterprise_schema_demo"
STATUS_MESSAGES = {
    "retrieve_schema": "Retrieving relevant schemas...",
    "generate_sql": "Generating SQL query...",
    "execute_sql": "Executing SQL...",
    "self_correct": "Error detected. Self-correcting...",
    "generate_visual_and_summary": "Query successful. Generating output...",
    "graceful_failure": "Maximum retries reached. Could not generate a valid query.",
}

FORBIDDEN_SQL_PATTERN = re.compile(r"\b(drop|delete|update|insert)\b", re.IGNORECASE)
SQL_OVERRIDE_START_PATTERN = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
SQL_OVERRIDE_FORBIDDEN_PATTERN = re.compile(
    r"\b(attach|detach|pragma|alter|create|drop|update|insert|delete|replace|vacuum|reindex|analyze|truncate)\b",
    re.IGNORECASE,
)
SQL_STRING_LITERAL_PATTERN = re.compile(r"'(?:''|[^'])*'")


def _sanitize_sql_override(sql_query: str) -> str:
    cleaned = sql_query.strip()
    if not cleaned:
        raise ValueError("SQL override is empty")
    if not SQL_OVERRIDE_START_PATTERN.match(cleaned):
        raise ValueError("SQL override must start with SELECT or WITH")

    without_literals = SQL_STRING_LITERAL_PATTERN.sub("''", cleaned)
    if SQL_OVERRIDE_FORBIDDEN_PATTERN.search(without_literals):
        raise ValueError("Forbidden SQL operation detected")
    if "--" in without_literals or "/*" in without_literals:
        raise ValueError("SQL comments are not allowed in overrides")

    normalized = without_literals.strip()
    if ";" in normalized:
        if not normalized.endswith(";") or normalized.count(";") > 1:
            raise ValueError("Multiple SQL statements are not allowed")
        cleaned = cleaned.rstrip().rstrip(";")

    return cleaned


app = Flask(__name__, static_folder="web", static_url_path="/static")
_assets_lock = threading.Lock()
_assets_ready = False


def prepare_demo_assets(db_path: str, collection_name: str) -> None:
    db_file = Path(db_path)
    if not db_file.exists():
        create_database(db_file)

    schema_docs = extract_schema(db_path)
    build_index(schema_docs, collection_name)


def _ensure_assets_ready() -> None:
    global _assets_ready
    if _assets_ready:
        return
    with _assets_lock:
        if _assets_ready:
            return
        prepare_demo_assets(str(DB_PATH), DEFAULT_COLLECTION_NAME)
        _assets_ready = True


def _make_unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique_columns: list[str] = []

    for column in columns:
        count = seen.get(column, 0)
        if count == 0:
            unique_columns.append(column)
        else:
            unique_columns.append(f"{column}_{count + 1}")
        seen[column] = count + 1

    return unique_columns


def _normalize_dataframe_for_display(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None:
        return None

    normalized_df = df.copy()
    normalized_df.columns = _make_unique_columns([str(column) for column in normalized_df.columns])
    return normalized_df


def _read_only_uri(db_path: str) -> str:
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


def _execute_sql_direct(db_path: str, sql_query: str) -> pd.DataFrame:
    sql_query = _sanitize_sql_override(sql_query)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_read_only_uri(db_path), uri=True)
        return pd.read_sql_query(sql_query, connection)
    finally:
        if connection is not None:
            connection.close()


# --- Prompt Guardrails ---

PII_PATTERNS = {
    "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "PHONE": re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
}

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"\bignore\b.*\binstructions\b", re.IGNORECASE),
    re.compile(r"\byou are now\b", re.IGNORECASE),
    re.compile(r"\bnew set of instructions\b", re.IGNORECASE),
]

def is_prompt_safe(prompt: str) -> tuple[bool, str]:
    """
    Checks if a user prompt is safe from basic attacks.
    """
    # Check for forbidden SQL keywords
    if FORBIDDEN_SQL_PATTERN.search(prompt):
        return False, "Potential SQL injection attempt detected."

    # Check for PII
    for pii_type, pattern in PII_PATTERNS.items():
        if pattern.search(prompt):
            return False, f"Potential {pii_type} detected. Please remove personal information."

    # Check for prompt injection
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(prompt):
            return False, "Potential prompt injection attempt detected."

    return True, ""


def _format_result_df(df: pd.DataFrame | None, limit: int = 200) -> dict[str, Any] | None:
    if df is None:
        return None

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    df = _normalize_dataframe_for_display(df)
    if df is None:
        return None

    preview_df = df.head(limit)
    return {
        "columns": [str(column) for column in preview_df.columns],
        "rows": preview_df.values.tolist(),
        "row_count": int(len(df)),
    }


def _serialize_figure(figure: Any) -> dict[str, Any] | None:
    if figure is None:
        return None
    try:
        return json.loads(pio.to_json(figure, validate=False))
    except Exception:
        return None


def _serialize_all_figures(df: pd.DataFrame | None, question: str) -> dict[str, Any]:
    """Generate and serialize Plotly figures for every applicable chart type."""
    if df is None or df.empty:
        return {}

    chart_types = ["bar", "line", "pie", "histogram", "table", "metric"]
    figures: dict[str, Any] = {}
    for chart_type in chart_types:
        try:
            fig = generate_plotly_chart(df, chart_type, question)
            serialized = _serialize_figure(fig)
            if serialized:
                figures[chart_type] = serialized
        except Exception:
            pass
    return figures


def _truncate_schema(schema_context: str, limit: int = 6000) -> str:
    if len(schema_context) <= limit:
        return schema_context
    return schema_context[:limit] + "\n...truncated..."


def _run_query(
    question: str,
    provider: str,
    api_key: str | None,
    top_k: int,
    collection_name: str,
) -> dict[str, Any]:
    start_time = time.perf_counter()

    is_safe, message = is_prompt_safe(question)
    if not is_safe:
        return {
            "query": question,
            "sql_query": "",
            "db_result": None,
            "summary": None,
            "figure": None,
            "final_message": message,
            "status": "failed",
            "error_trace": "Prompt safety check failed",
            "status_updates": [],
        }

    try:
        llm_client = load_llm_client(provider=provider, api_key=api_key)
        graph = build_agent_graph(db_path=str(DB_PATH), collection_name=collection_name, llm_client=llm_client, top_k=top_k)
    except Exception as exc:
        return {
            "query": question,
            "sql_query": "",
            "db_result": None,
            "summary": None,
            "figure": None,
            "final_message": str(exc),
            "status": "failed",
            "error_trace": str(exc),
            "status_updates": [],
        }

    state: dict[str, Any] = {
        "query": question,
        "schema_context": "",
        "sql_query": "",
        "db_result": None,
        "error_trace": "",
        "retry_count": 0,
        "status": "initialized",
    }

    final_state = state.copy()
    status_updates: list[dict[str, str]] = []

    try:
        for update in graph.stream(state, stream_mode="updates"):
            if not update:
                continue

            node_name = next(iter(update))
            payload = update[node_name]
            if isinstance(payload, dict):
                final_state.update(payload)

            if node_name == "self_correct":
                retry_count = int(final_state.get("retry_count", 0))
                message = f"Error detected. Self-correcting (attempt {retry_count}/3)..."
            else:
                message = STATUS_MESSAGES.get(node_name)

            if message:
                elapsed_s = round(time.perf_counter() - start_time, 2)
                status_updates.append({
                    "node": node_name,
                    "message": message,
                    "elapsed_s": elapsed_s,
                })

        final_state["status_updates"] = status_updates
        return final_state
    except Exception as exc:
        return {
            "query": question,
            "sql_query": "",
            "db_result": None,
            "summary": None,
            "figure": None,
            "final_message": f"Unable to run the query: {exc}",
            "status": "failed",
            "error_trace": str(exc),
            "status_updates": status_updates,
        }


def _run_sql_override(
    question: str,
    sql_override: str,
    provider: str,
    api_key: str | None,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    status_updates: list[dict[str, str]] = []

    try:
        llm_client = load_llm_client(provider=provider, api_key=api_key)
        result_df = _execute_sql_direct(str(DB_PATH), sql_override)
        elapsed_s = round(time.perf_counter() - start_time, 2)
        status_updates.append({
            "node": "execute_sql",
            "message": STATUS_MESSAGES["execute_sql"],
            "elapsed_s": elapsed_s,
        })

        chart_type = select_chart_type(result_df)
        figure = generate_plotly_chart(result_df, chart_type, question)
        summary = generate_summary(result_df, question, llm_client)
        elapsed_s = round(time.perf_counter() - start_time, 2)
        status_updates.append({
            "node": "generate_visual_and_summary",
            "message": STATUS_MESSAGES["generate_visual_and_summary"],
            "elapsed_s": elapsed_s,
        })

        return {
            "query": question,
            "sql_query": sql_override,
            "db_result": result_df,
            "summary": summary,
            "figure": figure,
            "status": "completed",
            "schema_context": "",
            "status_updates": status_updates,
        }
    except Exception as exc:
        return {
            "query": question,
            "sql_query": sql_override,
            "db_result": None,
            "summary": None,
            "figure": None,
            "final_message": f"Unable to run the query: {exc}",
            "status": "failed",
            "error_trace": str(exc),
            "status_updates": status_updates,
        }


def _classify_error(
    status: str,
    error_trace: str | None,
    db_result: dict[str, Any] | None,
) -> dict[str, str] | None:
    if db_result and db_result.get("row_count") == 0:
        return {
            "error_type": "empty_result",
            "error_message": "No rows were returned for this query.",
        }

    if status != "failed":
        return None

    trace_text = (error_trace or "").lower()
    if "timeout" in trace_text:
        return {
            "error_type": "db_timeout",
            "error_message": "Database connection timed out.",
        }
    if "generated sql is empty" in trace_text or "sql generation" in trace_text or "parse" in trace_text:
        return {
            "error_type": "llm_parse_error",
            "error_message": "The AI could not produce a valid SQL query.",
        }
    if "sqlite" in trace_text or "no such" in trace_text or "syntax" in trace_text or "forbidden" in trace_text:
        return {
            "error_type": "sql_execution_failure",
            "error_message": "The SQL could not be executed on the database.",
        }

    return {
        "error_type": "unknown_error",
        "error_message": "Something went wrong while running the query.",
    }


@app.route("/")
def index() -> Any:
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/query", methods=["POST"])
def api_query() -> Any:
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Question is required."}), 400

    provider = str(payload.get("provider", "gemini")).strip().lower()
    api_key = payload.get("api_key") or None
    try:
        top_k = int(payload.get("top_k", 3))
    except (TypeError, ValueError):
        top_k = 3

    raw_override = payload.get("sql_override")
    if raw_override is None:
        sql_override = None
    elif isinstance(raw_override, str):
        sql_override = raw_override.strip() or None
    else:
        sql_override = str(raw_override).strip() or None

    _ensure_assets_ready()
    if sql_override:
        result = _run_sql_override(question, sql_override, provider, api_key)
    else:
        result = _run_query(question, provider, api_key, top_k, DEFAULT_COLLECTION_NAME)

    raw_df = result.get("db_result")
    if raw_df is not None and not isinstance(raw_df, pd.DataFrame):
        raw_df = pd.DataFrame(raw_df)
    db_result = _format_result_df(raw_df)
    figure_json = _serialize_figure(result.get("figure"))
    figures_all = _serialize_all_figures(raw_df, question)
    summary = result.get("summary") or result.get("final_message") or ""
    schema_context = _truncate_schema(str(result.get("schema_context", "")))
    status = result.get("status", "")
    error_trace = result.get("error_trace") or result.get("final_message")
    error_payload = _classify_error(status, error_trace, db_result)
    status_updates = result.get("status_updates", [])
    status_meta = ""
    if status_updates:
        status_meta = str(status_updates[-1].get("message", ""))

    response = {
        "status": status,
        "sql_query": result.get("sql_query", ""),
        "summary": summary,
        "db_result": db_result,
        "figure": figure_json,
        "figures": figures_all,
        "chart_type_auto": result.get("chart_type", "table"),
        "status_updates": status_updates,
        "schema_context": schema_context,
        "status_meta": status_meta,
    }

    if error_payload:
        response.update(error_payload)
    return jsonify(response)


@app.route("/api/query/stream", methods=["POST"])
def api_query_stream() -> Any:
    """SSE endpoint — streams LangGraph node updates as they happen."""
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Question is required."}), 400

    provider = str(payload.get("provider", "gemini")).strip().lower()
    api_key = payload.get("api_key") or None
    try:
        top_k = int(payload.get("top_k", 3))
    except (TypeError, ValueError):
        top_k = 3

    sql_override: str | None = None

    _ensure_assets_ready()

    def generate():
        start_time = time.perf_counter()

        if sql_override:
            # SQL override path — single event stream
            try:
                llm_client = load_llm_client(provider=provider, api_key=api_key)
                result_df = _execute_sql_direct(str(DB_PATH), sql_override)
                elapsed_s = round(time.perf_counter() - start_time, 2)
                yield f"data: {json.dumps({'type': 'node_update', 'node': 'execute_sql', 'message': STATUS_MESSAGES['execute_sql'], 'elapsed_s': elapsed_s, 'retry_count': 0})}\n\n"

                chart_type = select_chart_type(result_df)
                figure = generate_plotly_chart(result_df, chart_type, question)
                summary = generate_summary(result_df, question, llm_client)
                elapsed_s = round(time.perf_counter() - start_time, 2)
                yield f"data: {json.dumps({'type': 'node_update', 'node': 'generate_visual_and_summary', 'message': STATUS_MESSAGES['generate_visual_and_summary'], 'elapsed_s': elapsed_s, 'retry_count': 0})}\n\n"

                db_result = _format_result_df(result_df)
                figures_all = _serialize_all_figures(result_df, question)
                status_updates = [
                    {"node": "execute_sql", "message": STATUS_MESSAGES["execute_sql"], "elapsed_s": elapsed_s},
                    {"node": "generate_visual_and_summary", "message": STATUS_MESSAGES["generate_visual_and_summary"], "elapsed_s": elapsed_s},
                ]
                done_event: dict[str, Any] = {
                    "type": "done",
                    "status": "completed",
                    "sql_query": sql_override,
                    "summary": summary,
                    "db_result": db_result,
                    "figure": _serialize_figure(figure),
                    "figures": figures_all,
                    "chart_type_auto": chart_type,
                    "status_updates": status_updates,
                    "schema_context": "",
                    "status_meta": STATUS_MESSAGES["generate_visual_and_summary"],
                }
                yield f"data: {json.dumps(done_event)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        # Agent path — stream each LangGraph node update
        try:
            llm_client = load_llm_client(provider=provider, api_key=api_key)
            graph = build_agent_graph(
                db_path=str(DB_PATH),
                collection_name=DEFAULT_COLLECTION_NAME,
                llm_client=llm_client,
                top_k=top_k,
            )
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        state: dict[str, Any] = {
            "query": question,
            "schema_context": "",
            "sql_query": "",
            "db_result": None,
            "error_trace": "",
            "retry_count": 0,
            "status": "initialized",
        }
        final_state: dict[str, Any] = state.copy()
        status_updates_list: list[dict[str, Any]] = []

        try:
            for update in graph.stream(state, stream_mode="updates"):
                if not update:
                    continue
                node_name = next(iter(update))
                node_payload = update[node_name]
                if isinstance(node_payload, dict):
                    final_state.update(node_payload)

                if node_name == "self_correct":
                    retry_count = int(final_state.get("retry_count", 0))
                    message = f"Error detected. Self-correcting (attempt {retry_count}/3)..."
                else:
                    message = STATUS_MESSAGES.get(node_name)

                if message:
                    elapsed_s = round(time.perf_counter() - start_time, 2)
                    step_event = {
                        "type": "node_update",
                        "node": node_name,
                        "message": message,
                        "elapsed_s": elapsed_s,
                        "retry_count": int(final_state.get("retry_count", 0)),
                    }
                    status_updates_list.append({"node": node_name, "message": message, "elapsed_s": elapsed_s})
                    yield f"data: {json.dumps(step_event)}\n\n"

            raw_df = final_state.get("db_result")
            if raw_df is not None and not isinstance(raw_df, pd.DataFrame):
                raw_df = pd.DataFrame(raw_df)
            db_result = _format_result_df(raw_df)
            figure_json = _serialize_figure(final_state.get("figure"))
            figures_all = _serialize_all_figures(raw_df, question)
            summary = final_state.get("summary") or final_state.get("final_message") or ""
            schema_context = _truncate_schema(str(final_state.get("schema_context", "")))
            status = final_state.get("status", "")
            error_trace = final_state.get("error_trace") or final_state.get("final_message")
            error_payload = _classify_error(status, error_trace, db_result)
            status_meta = str(status_updates_list[-1].get("message", "")) if status_updates_list else ""

            done_event = {
                "type": "done",
                "status": status,
                "sql_query": final_state.get("sql_query", ""),
                "summary": summary,
                "db_result": db_result,
                "figure": figure_json,
                "figures": figures_all,
                "chart_type_auto": final_state.get("chart_type", "table"),
                "status_updates": status_updates_list,
                "schema_context": schema_context,
                "status_meta": status_meta,
            }
            if error_payload:
                done_event.update(error_payload)
            yield f"data: {json.dumps(done_event)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Unable to run the query: {exc}'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/static/<path:filename>")
def static_files(filename: str) -> Any:
    return send_from_directory(app.static_folder, filename)


if __name__ == "__main__":
    _ensure_assets_ready()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
