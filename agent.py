from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

import pandas as pd
from langgraph.graph import END, StateGraph

from retriever import retrieve_relevant_schemas
from visualizer import generate_plotly_chart, generate_summary, select_chart_type


logger = logging.getLogger("AGENT")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

FORBIDDEN_SQL_PATTERN = re.compile(r"\b(drop|delete|update|insert)\b", re.IGNORECASE)
SQL_CLEANUP_PATTERN = re.compile(r"```(?:sql)?|```", re.IGNORECASE)
SQL_START_PATTERN = re.compile(r"(?:with|select)\b", re.IGNORECASE | re.DOTALL)


class AgentState(TypedDict):
    query: str
    schema_context: str
    schema_confidence: float
    sql_query: str
    db_result: Any
    error_trace: str
    retry_count: int
    status: str
    figure: NotRequired[Any]
    chart_type: NotRequired[str]
    summary: NotRequired[str]
    final_message: NotRequired[str]


class BaseLLMClient:
    def generate_text(self, prompt: str) -> str:  # pragma: no cover - interface only
        raise NotImplementedError


def _extract_sql_text(text: str) -> str:
    cleaned = text.strip()

    fenced_match = re.search(r"```(?:sql)?\s*(.*?)```", cleaned, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    sql_blocks: list[str] = []
    current_block: list[str] = []
    capturing = False
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not capturing:
            if line.lower().startswith(("select", "with")):
                capturing = True
                current_block = [line]
            continue

        if not line:
            if current_block:
                sql_blocks.append("\n".join(current_block).strip())
            capturing = False
            current_block = []
            continue

        current_block.append(line)

    if capturing and current_block:
        sql_blocks.append("\n".join(current_block).strip())

    if sql_blocks:
        cleaned = sql_blocks[-1]

    cleaned = cleaned.strip().strip("`").strip()
    return cleaned


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


class GeminiLLMClient(BaseLLMClient):
    def __init__(self, api_key: str, model_name: str | None = None) -> None:
        from google import genai  # type: ignore

        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    def generate_text(self, prompt: str) -> str:
        response = self._client.models.generate_content(model=self._model_name, contents=prompt)
        return getattr(response, "text", "") or ""


class GroqLLMClient(BaseLLMClient):
    def __init__(self, api_key: str, model_name: str | None = None) -> None:
        from groq import Groq  # type: ignore

        self._client = Groq(api_key=api_key)
        self._model_name = model_name or os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    def generate_text(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": "Return only the requested text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content or ""


def load_llm_client(provider: str | None = None, api_key: str | None = None) -> BaseLLMClient:
    selected_provider = (provider or os.getenv("NL2SQL_LLM_PROVIDER", "gemini")).strip().lower()

    if selected_provider not in {"gemini", "groq"}:
        raise ValueError("NL2SQL_LLM_PROVIDER must be either 'gemini' or 'groq'")

    if selected_provider == "gemini":
        selected_api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not selected_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when NL2SQL_LLM_PROVIDER=gemini")
        return GeminiLLMClient(api_key=selected_api_key)

    selected_api_key = api_key or os.getenv("GROQ_API_KEY")
    if not selected_api_key:
        raise RuntimeError("GROQ_API_KEY is required when NL2SQL_LLM_PROVIDER=groq")
    return GroqLLMClient(api_key=selected_api_key)


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"{re.escape(heading)}\s*:\s*(.+?)(?:\n[A-Z][^:\n]*:|\Z)", re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _read_only_uri(db_path: str) -> str:
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


def _sanitize_sql(sql_text: str) -> str:
    cleaned = SQL_CLEANUP_PATTERN.sub("", sql_text).strip()
    cleaned = _extract_sql_text(cleaned)
    if cleaned.lower().startswith(("select", "with")):
        cleaned = cleaned.rstrip(";")
        return cleaned

    match = SQL_START_PATTERN.search(cleaned)
    if match:
        cleaned = cleaned[match.start() :]

    return cleaned.strip().rstrip(";")


def _is_forbidden_sql(sql_text: str) -> bool:
    return bool(FORBIDDEN_SQL_PATTERN.search(sql_text))


def _build_sql_prompt(query: str, schema_context: str) -> str:
    return (
        "You are an expert SQL generator for a read-only SQLite database. "
        "Use only the provided schema context and return SQL only, with no explanation.\n\n"
        f"Schema context:\n{schema_context}\n\n"
        f"User question: {query}\n\n"
        "Return SQL only."
    )


def _build_correction_prompt(query: str, schema_context: str, failed_sql: str, error_trace: str) -> str:
    return (
        "You are correcting an SQL query for a read-only SQLite database. "
        "Use the schema context, the original user question, and the execution error to fix the query. "
        "Return corrected SQL only, with no explanation.\n\n"
        f"Original question: {query}\n\n"
        f"Schema context:\n{schema_context}\n\n"
        f"Failed SQL:\n{failed_sql}\n\n"
        f"Error trace:\n{error_trace}\n\n"
        "Return corrected SQL only."
    )


def _build_fallback_prompt(query: str) -> str:
    return (
        "You are a helpful assistant. The user's query could not be answered based on the available data context. "
        "Politely inform the user that their query does not seem to match the available data and that they should "
        "try rephrasing their question. Keep the response concise and helpful.\n\n"
        f"User question: {query}"
    )


def _execute_sql_read_only(db_path: str, sql_query: str) -> pd.DataFrame:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_read_only_uri(db_path), uri=True)
        result_df = pd.read_sql_query(sql_query, connection)
        result_df.columns = _make_unique_columns([str(column) for column in result_df.columns])
        return result_df
    finally:
        if connection is not None:
            connection.close()


def _log_transition(node_name: str, state: AgentState, outcome: str) -> None:
    logger.info(
        "[%s] retry_count=%s status=%s outcome=%s",
        node_name,
        state.get("retry_count", 0),
        state.get("status", ""),
        outcome,
    )


def build_agent_graph(
    db_path: str,
    collection_name: str,
    llm_client: BaseLLMClient,
    top_k: int = 3,
    confidence_threshold: float = 0.5,
) -> Any:
    def retrieve_schema(state: AgentState) -> dict[str, Any]:
        logger.info("[RETRIEVE_SCHEMA] Starting schema retrieval")
        try:
            schema_context, schema_confidence = retrieve_relevant_schemas(
                query=state["query"],
                collection_name=collection_name,
                top_k=top_k,
            )
            _log_transition("RETRIEVE_SCHEMA", state, "success")
            return {
                "schema_context": schema_context,
                "schema_confidence": schema_confidence,
                "status": "retrieving_schema",
            }
        except Exception as exc:
            logger.error("[RETRIEVE_SCHEMA] %s", exc)
            return {"error_trace": str(exc), "status": "schema_retrieval_failed"}

    def route_after_retrieval(state: AgentState) -> Literal["generate_sql", "fallback_message"]:
        """Decide whether to proceed with SQL generation or fallback."""
        if state.get("schema_confidence", 0.0) >= confidence_threshold:
            return "generate_sql"
        return "fallback_message"

    def generate_sql(state: AgentState) -> dict[str, Any]:
        logger.info("[GENERATE_SQL] Generating SQL")
        try:
            prompt = _build_sql_prompt(state["query"], state.get("schema_context", ""))
            sql_query = _sanitize_sql(llm_client.generate_text(prompt))
            _log_transition("GENERATE_SQL", state, "success")
            return {"sql_query": sql_query, "status": "sql_generated", "error_trace": ""}
        except Exception as exc:
            logger.error("[GENERATE_SQL] %s", exc)
            return {"error_trace": str(exc), "status": "sql_generation_failed"}

    def execute_sql(state: AgentState) -> dict[str, Any]:
        logger.info("[EXECUTE_SQL] Executing SQL")
        try:
            sql_query = _sanitize_sql(state.get("sql_query", ""))
            if not sql_query:
                raise ValueError("Generated SQL is empty")
            if _is_forbidden_sql(sql_query):
                raise ValueError("Forbidden SQL operation detected")
            result_df = _execute_sql_read_only(db_path, sql_query)
            _log_transition("EXECUTE_SQL", state, "success")
            return {"db_result": result_df, "status": "sql_executed", "error_trace": ""}
        except Exception as exc:
            logger.error("[EXECUTE_SQL] %s", exc)
            return {"db_result": None, "error_trace": str(exc), "status": "sql_execution_failed"}

    def evaluate_result(state: AgentState) -> dict[str, Any]:
        logger.info("[EVALUATE_RESULT] Evaluating execution result")
        _log_transition("EVALUATE_RESULT", state, "success" if state.get("db_result") is not None else "failure")
        return {"status": "evaluated"}

    def route_after_execution(state: AgentState) -> Literal["generate_visual_and_summary", "self_correct", "graceful_failure"]:
        if state.get("db_result") is not None:
            return "generate_visual_and_summary"
        if state.get("retry_count", 0) >= 3:
            return "graceful_failure"
        return "self_correct"

    def self_correct(state: AgentState) -> dict[str, Any]:
        current_retry = int(state.get("retry_count", 0))
        logger.info("[SELF_CORRECT] Attempt %d/3", current_retry + 1)
        try:
            prompt = _build_correction_prompt(
                query=state["query"],
                schema_context=state.get("schema_context", ""),
                failed_sql=state.get("sql_query", ""),
                error_trace=state.get("error_trace", ""),
            )
            corrected_sql = _sanitize_sql(llm_client.generate_text(prompt))
            _log_transition("SELF_CORRECT", state, "success")
            return {
                "sql_query": corrected_sql,
                "retry_count": current_retry + 1,
                "status": f"self_correcting_{current_retry + 1}",
            }
        except Exception as exc:
            logger.error("[SELF_CORRECT] %s", exc)
            return {
                "error_trace": str(exc),
                "retry_count": current_retry + 1,
                "status": f"self_correction_failed_{current_retry + 1}",
            }

    def generate_visual_and_summary(state: AgentState) -> dict[str, Any]:
        logger.info("[GENERATE_VISUAL_AND_SUMMARY] Preparing output")
        try:
            result_df = state.get("db_result")
            if not isinstance(result_df, pd.DataFrame):
                result_df = pd.DataFrame(result_df)
            chart_type = select_chart_type(result_df)
            figure = generate_plotly_chart(result_df, chart_type, state["query"])
            summary = generate_summary(result_df, state["query"], llm_client)
            _log_transition("GENERATE_VISUAL_AND_SUMMARY", state, "success")
            return {
                "db_result": result_df,
                "chart_type": chart_type,
                "figure": figure,
                "summary": summary,
                "status": "completed",
            }
        except Exception as exc:
            logger.error("[GENERATE_VISUAL_AND_SUMMARY] %s", exc)
            return {"error_trace": str(exc), "status": "output_generation_failed"}

    def graceful_failure(state: AgentState) -> dict[str, Any]:
        logger.info("[GRACEFUL_FAILURE] Returning friendly failure message")
        _log_transition("GRACEFUL_FAILURE", state, "failure")
        return {
            "db_result": None,
            "figure": None,
            "summary": None,
            "final_message": "Could not generate a valid SQL query after multiple correction attempts.",
            "status": "failed",
        }

    def fallback_message(state: AgentState) -> dict[str, Any]:
        """Generate a message when the query doesn't match the context."""
        logger.info("[FALLBACK_MESSAGE] Query does not match context, generating fallback.")
        try:
            prompt = _build_fallback_prompt(state["query"])
            message = llm_client.generate_text(prompt)
            return {
                "db_result": None,
                "figure": None,
                "summary": None,
                "final_message": message,
                "status": "fallback",
            }
        except Exception as exc:
            logger.error("[FALLBACK_MESSAGE] %s", exc)
            return {
                "final_message": "I'm sorry, but I couldn't understand your request based on the available data. Please try rephrasing your question.",
                "status": "fallback_failed",
            }

    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve_schema", retrieve_schema)
    workflow.add_node("generate_sql", generate_sql)
    workflow.add_node("execute_sql", execute_sql)
    workflow.add_node("evaluate_result", evaluate_result)
    workflow.add_node("self_correct", self_correct)
    workflow.add_node("generate_visual_and_summary", generate_visual_and_summary)
    workflow.add_node("graceful_failure", graceful_failure)
    workflow.add_node("fallback_message", fallback_message)

    workflow.set_entry_point("retrieve_schema")
    workflow.add_conditional_edges(
        "retrieve_schema",
        route_after_retrieval,
        {"generate_sql": "generate_sql", "fallback_message": "fallback_message"},
    )
    workflow.add_edge("generate_sql", "execute_sql")
    workflow.add_edge("execute_sql", "evaluate_result")
    workflow.add_conditional_edges(
        "evaluate_result",
        route_after_execution,
        {
            "generate_visual_and_summary": "generate_visual_and_summary",
            "self_correct": "self_correct",
            "graceful_failure": "graceful_failure",
        },
    )
    workflow.add_edge("self_correct", "execute_sql")
    workflow.add_edge("generate_visual_and_summary", END)
    workflow.add_edge("graceful_failure", END)
    workflow.add_edge("fallback_message", END)

    return workflow.compile()


def run_agent(
    question: str,
    db_path: str,
    collection_name: str,
    llm_client: BaseLLMClient | None = None,
    top_k: int = 3,
) -> AgentState:
    if llm_client is None:
        llm_client = load_llm_client()

    graph = build_agent_graph(
        db_path=db_path,
        collection_name=collection_name,
        llm_client=llm_client,
        top_k=top_k,
    )

    initial_state: AgentState = {
        "query": question,
        "schema_context": "",
        "schema_confidence": 0.0,
        "sql_query": "",
        "db_result": None,
        "error_trace": "",
        "retry_count": 0,
        "status": "initialized",
    }
    final_state = graph.invoke(initial_state)

    # Add confidence to the final output dictionary, separate from the graph state
    output = dict(final_state)
    output["schema_confidence"] = final_state.get("schema_confidence", 0.0)
    return output
