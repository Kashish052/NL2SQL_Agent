from __future__ import annotations

import os
import json
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from rank_bm25 import BM25Okapi


os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")


logger = logging.getLogger("RETRIEVER")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = "chroma_store"
MAX_JOIN_PATH_LENGTH = 4
MAX_INTERMEDIATE_TABLES = 6
MAX_JOIN_HINTS = 8

_FK_GRAPH_CACHE: dict[str, dict[str, list[dict[str, str]]]] = {}


def _read_only_uri(db_path: str) -> str:
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


@lru_cache(maxsize=1)
def _get_embedding_model() -> Any:
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", EMBEDDING_MODEL_NAME)
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _format_table_document(schema_doc: dict[str, Any]) -> str:
    columns = schema_doc.get("columns", [])
    foreign_keys = schema_doc.get("foreign_keys", [])
    sample_rows = schema_doc.get("sample_rows", [])

    column_lines = [
        f"- {column['name']} ({column['type']})" + (" [PK]" if column.get("primary_key") else "")
        for column in columns
    ]
    fk_lines = [
        f"- {item['from']} -> {item['table']}.{item['to']}"
        for item in foreign_keys
    ] or ["- None"]

    sample_text = json.dumps(sample_rows, indent=2, ensure_ascii=False)
    return (
        f"Table: {schema_doc['table_name']}\n"
        f"Columns:\n{chr(10).join(column_lines)}\n"
        f"Foreign Keys:\n{chr(10).join(fk_lines)}\n"
        f"Sample Rows:\n{sample_text}"
    )


def extract_schema(db_path: str) -> list[dict[str, Any]]:
    logger.info("Extracting schema from %s", db_path)
    schema_docs: list[dict[str, Any]] = []
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_read_only_uri(db_path), uri=True)
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        table_names = [row[0] for row in cursor.fetchall()]

        for table_name in table_names:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "default": row[4],
                    "primary_key": bool(row[5]),
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(f"PRAGMA foreign_key_list({table_name})")
            foreign_keys = [
                {
                    "id": row[0],
                    "seq": row[1],
                    "table": row[2],
                    "from": row[3],
                    "to": row[4],
                    "on_update": row[5],
                    "on_delete": row[6],
                    "match": row[7],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            sample_rows = [dict(row) for row in cursor.fetchall()]
            schema_doc = {
                "table_name": table_name,
                "columns": columns,
                "primary_key": [column["name"] for column in columns if column["primary_key"]],
                "foreign_keys": foreign_keys,
                "sample_rows": sample_rows,
            }
            schema_doc["document"] = _format_table_document(schema_doc)
            schema_docs.append(schema_doc)
    except sqlite3.Error as exc:
        logger.error("Failed to extract schema: %s", exc)
        raise
    finally:
        if connection is not None:
            connection.close()

    logger.info("Extracted %d schema documents", len(schema_docs))
    return schema_docs


def build_index(
    schema_docs: list[dict[str, Any]],
    collection_name: str,
    persist_directory: str = DEFAULT_PERSIST_DIR,
) -> None:
    if not schema_docs:
        raise ValueError("schema_docs cannot be empty")

    if collection_name in _FK_GRAPH_CACHE:
        logger.info("Invalidating cached schema graph for %s", collection_name)
        _FK_GRAPH_CACHE.pop(collection_name, None)

    logger.info("Building ChromaDB index in %s for collection %s", persist_directory, collection_name)
    persist_path = Path(persist_directory)
    persist_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_path))
    collection = client.get_or_create_collection(name=collection_name)
    model = _get_embedding_model()

    documents = [schema_doc["document"] for schema_doc in schema_docs]
    embeddings = model.encode(documents, normalize_embeddings=True).tolist()
    metadatas = [
        {
            "table_name": schema_doc["table_name"],
            "primary_key": ",".join(schema_doc.get("primary_key", [])),
            "column_count": len(schema_doc.get("columns", [])),
            "foreign_keys": json.dumps([
                {"from": fk["from"], "table": fk["table"], "to": fk["to"]}
                for fk in schema_doc.get("foreign_keys", [])
            ]),
        }
        for schema_doc in schema_docs
    ]
    ids = [schema_doc["table_name"] for schema_doc in schema_docs]

    try:
        collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to build Chroma index: %s", exc)
        raise

    logger.info("Indexed %d schema documents", len(schema_docs))


def _build_fk_graph(metadatas: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    graph: dict[str, list[dict[str, str]]] = {}
    for metadata in metadatas:
        if not isinstance(metadata, dict):
            continue
        table_name = metadata.get("table_name")
        if not table_name:
            continue
        if table_name not in graph:
            graph[table_name] = []

        fk_str = metadata.get("foreign_keys", "[]")
        try:
            fk_list = json.loads(fk_str)
        except Exception:
            fk_list = []

        for fk in fk_list:
            target_table = fk.get("table")
            from_col = fk.get("from")
            to_col = fk.get("to")
            if not target_table or not from_col or not to_col:
                continue

            if target_table not in graph:
                graph[target_table] = []

            # Add undirected edge A -> B
            graph[table_name].append({
                "to_table": target_table,
                "from_col": from_col,
                "to_col": to_col,
            })
            # Add reverse edge B -> A
            graph[target_table].append({
                "to_table": table_name,
                "from_col": to_col,
                "to_col": from_col,
            })
    return graph


def _find_shortest_path(
    graph: dict[str, list[dict[str, str]]],
    start: str,
    end: str,
) -> list[dict[str, str]] | None:
    if start == end:
        return []

    from collections import deque
    queue = deque([(start, [])])
    visited = {start}

    while queue:
        current, path = queue.popleft()
        if current == end:
            return path

        for edge in graph.get(current, []):
            neighbor = edge["to_table"]
            if neighbor not in visited:
                visited.add(neighbor)
                step = {
                    "from_table": current,
                    "from_col": edge["from_col"],
                    "to_table": neighbor,
                    "to_col": edge["to_col"],
                }
                queue.append((neighbor, path + [step]))

    return None


def retrieve_relevant_schemas(
    query: str,
    collection_name: str,
    top_k: int = 3,
    persist_directory: str = DEFAULT_PERSIST_DIR,
) -> tuple[str, float]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    logger.info("Retrieving relevant schemas for query: %s", query)
    client = chromadb.PersistentClient(path=persist_directory)
    collection = client.get_or_create_collection(name=collection_name)
    model = _get_embedding_model()
    query_embedding = model.encode([query], normalize_embeddings=True).tolist()

    # --- 1. Semantic Search (ChromaDB) ---
    try:
        semantic_results = collection.query(
            query_embeddings=query_embedding,
            n_results=top_k * 2,  # Retrieve more to allow for reranking
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.error("Schema retrieval failed: %s", exc)
        raise

    # --- 2. Keyword Search (BM25) ---
    all_docs_from_db = collection.get(include=["documents"])
    corpus = all_docs_from_db.get("documents", [])
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    
    tokenized_query = query.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)
    
    # Get top-k results for BM25
    top_bm25_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k * 2]
    
    bm25_results = {
        "ids": [[all_docs_from_db["ids"][i] for i in top_bm25_indices]],
        "scores": [[bm25_scores[i] for i in top_bm25_indices]]
    }

    # --- 3. Reranking with Reciprocal Rank Fusion (RRF) ---
    ranked_list = {}
    k = 60  # RRF constant

    # Process semantic results
    if semantic_results["ids"]:
        for rank, doc_id in enumerate(semantic_results["ids"][0]):
            if doc_id not in ranked_list:
                ranked_list[doc_id] = 0
            ranked_list[doc_id] += 1 / (k + rank + 1)

    # Process keyword results
    if bm25_results["ids"]:
        for rank, doc_id in enumerate(bm25_results["ids"][0]):
            if doc_id not in ranked_list:
                ranked_list[doc_id] = 0
            ranked_list[doc_id] += 1 / (k + rank + 1)
            
    sorted_fused_results = sorted(ranked_list.keys(), key=lambda x: ranked_list[x], reverse=True)
    
    top_fused_ids = sorted_fused_results[:top_k]

    if not top_fused_ids:
        return "No relevant schema documents found.", 0.0

    # --- 4. Retrieve final documents for processing ---
    try:
        final_results = collection.get(ids=top_fused_ids, include=["documents", "metadatas"])
    except Exception as exc:
        logger.error("Failed to retrieve final documents after reranking: %s", exc)
        raise

    documents = final_results.get("documents", [])
    metadatas = final_results.get("metadatas", [])
    if not documents:
        return "No schema documents were returned from ChromaDB after reranking.", 0.0

    # Calculate average confidence score from RRF
    # Normalize the RRF scores to a 0-1 range for a confidence value
    max_score = max(ranked_list.values()) if ranked_list else 1.0
    top_scores = [ranked_list[doc_id] for doc_id in top_fused_ids]
    avg_confidence = (sum(top_scores) / len(top_scores)) / max_score if top_scores else 0.0
    
    # Join path awareness
    retrieved_tables = [
        m.get("table_name")
        for m in metadatas
        if isinstance(m, dict) and m.get("table_name")
    ]
    
    # Retrieve all metadatas to build the full schema graph
    try:
        all_elements = collection.get(include=["metadatas"])
        all_metadatas = all_elements.get("metadatas", [])
    except Exception as exc:
        logger.warning("Could not fetch all metadatas for schema graph: %s", exc)
        all_metadatas = []

    all_metadatas = [m for m in all_metadatas if isinstance(m, dict)]
    if not all_metadatas:
        all_metadatas = [m for m in metadatas if isinstance(m, dict)]

    graph = _FK_GRAPH_CACHE.get(collection_name)
    if graph is None:
        graph = _build_fk_graph(all_metadatas)
        _FK_GRAPH_CACHE[collection_name] = graph
    
    path_tables: set[str] = set()
    suggested_joins: set[str] = set()

    for i in range(len(retrieved_tables)):
        for j in range(i + 1, len(retrieved_tables)):
            t1 = retrieved_tables[i]
            t2 = retrieved_tables[j]
            path = _find_shortest_path(graph, t1, t2)
            if path and len(path) <= MAX_JOIN_PATH_LENGTH:
                for step in path:
                    path_tables.add(step["from_table"])
                    path_tables.add(step["to_table"])
                    # Standardize order to avoid duplicates like A = B and B = A
                    t_a, c_a, t_b, c_b = step["from_table"], step["from_col"], step["to_table"], step["to_col"]
                    if t_a < t_b:
                        join_desc = f"{t_a}.{c_a} = {t_b}.{c_b}"
                    else:
                        join_desc = f"{t_b}.{c_b} = {t_a}.{c_a}"
                    suggested_joins.add(join_desc)

    intermediate_tables = path_tables - set(retrieved_tables)
    if len(intermediate_tables) > MAX_INTERMEDIATE_TABLES:
        logger.info(
            "Trimming intermediate tables from %d to %d",
            len(intermediate_tables),
            MAX_INTERMEDIATE_TABLES,
        )
        intermediate_tables = set(sorted(intermediate_tables)[:MAX_INTERMEDIATE_TABLES])
    
    int_docs: list[str] = []
    int_metadatas: list[dict[str, Any]] = []
    if intermediate_tables:
        logger.info("Retrieving schemas for intermediate join-path tables: %s", list(intermediate_tables))
        try:
            res = collection.get(ids=list(intermediate_tables), include=["documents", "metadatas"])
            int_docs = res.get("documents", []) or []
            int_metadatas = res.get("metadatas", []) or []
        except Exception as exc:
            logger.error("Failed to retrieve intermediate schemas: %s", exc)

    chunks: list[str] = []
    # Original retrieved tables
    for index, document in enumerate(documents, start=1):
        metadata = metadatas[index - 1] if index - 1 < len(metadatas) else {}
        table_name = metadata.get("table_name", f"table_{index}")
        chunks.append(f"[Schema {index}] {table_name}\n{document}\n")

    # Intermediate tables
    for idx, int_doc in enumerate(int_docs, start=len(documents) + 1):
        int_meta = int_metadatas[idx - len(documents) - 1] if idx - len(documents) - 1 < len(int_metadatas) else {}
        table_name = int_meta.get("table_name", f"table_{idx}")
        chunks.append(f"[Schema {idx} - Intermediate Join Path Table] {table_name}\n{int_doc}\n")

    context = "\n".join(chunks)
    
    if suggested_joins:
        if len(suggested_joins) > MAX_JOIN_HINTS:
            logger.info(
                "Trimming suggested join hints from %d to %d",
                len(suggested_joins),
                MAX_JOIN_HINTS,
            )
            suggested_joins = set(sorted(list(suggested_joins))[:MAX_JOIN_HINTS])
        suggested_join_paths_str = (
            "\nSuggested Join Paths:\n" +
            "\n".join(f"- {j}" for j in sorted(list(suggested_joins))) +
            "\n"
        )
        context += "\n" + suggested_join_paths_str

    logger.info("Retrieved %d relevant schema documents (original: %d, intermediate: %d)",
                len(documents) + len(int_docs), len(documents), len(int_docs))
    return context, avg_confidence
