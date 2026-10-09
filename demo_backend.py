from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from agent import load_llm_client, run_agent
from retriever import build_index, extract_schema
from setup_db import DB_PATH, create_database

load_dotenv()


COLLECTION_NAME = "enterprise_schema_demo"


def _ensure_database() -> None:
    if not DB_PATH.exists():
        create_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the backend-only NL2SQL demo.")
    parser.add_argument(
        "question",
        nargs="?",
        default="List the top 5 employees with the highest-rated performance reviews. Show their name, job title, and rating.",
        help="Natural language question to send through the agent.",
    )
    parser.add_argument("--top-k", type=int, default=3, help="How many schema documents to retrieve.")
    parser.add_argument(
        "--provider",
        choices=["gemini", "groq"],
        default=None,
        help="LLM provider to use. Defaults to NL2SQL_LLM_PROVIDER if set, otherwise gemini.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override the API key passed to the selected provider. Otherwise uses the provider environment variable.",
    )
    args = parser.parse_args()

    _ensure_database()
    schema_docs = extract_schema(str(DB_PATH))
    build_index(schema_docs, COLLECTION_NAME)

    llm_client = load_llm_client(provider=args.provider, api_key=args.api_key)
    result = run_agent(question=args.question, db_path=str(DB_PATH), collection_name=COLLECTION_NAME, llm_client=llm_client, top_k=args.top_k)

    print("Status:", result.get("status"))
    print("SQL:", result.get("sql_query", ""))
    print("Summary:", result.get("summary", result.get("final_message", "")))
    db_result = result.get("db_result")
    if hasattr(db_result, "head"):
        print("Preview:")
        print(db_result.head().to_string(index=False))


if __name__ == "__main__":
    main()
