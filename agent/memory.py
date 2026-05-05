"""
memory.py — Persistent query memory using ChromaDB.

Stores successful question→SQL pairs as embeddings in a dedicated ChromaDB
collection (`query_memory`). When a new question arrives, similar past queries
are retrieved and injected into the LLM prompt as dynamic few-shot examples,
improving accuracy for recurring query patterns.

Unlike the in-memory response cache (dict with TTL), this provides:
  - Persistence across restarts
  - Semantic similarity matching (not just exact-match)
  - Cross-question learning (a question about "top sellers" benefits from
    past queries about "best performing sellers")
"""

import logging
from typing import Optional

import chromadb

from db.chroma_client import get_chroma_client, get_embedding_function

logger = logging.getLogger(__name__)

COLLECTION_NAME = "query_memory"
_client: Optional[chromadb.ClientAPI] = None
_collection: Optional[chromadb.Collection] = None


def _get_collection() -> chromadb.Collection:
    """Lazily initialise and cache the query_memory ChromaDB collection."""
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = get_chroma_client()
    embedding_fn = get_embedding_function()

    # get_or_create ensures the collection is created on first use
    # and reused on subsequent calls (including across restarts)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def store_query(question: str, sql: str, results_summary: str = "") -> None:
    """Embed and persist a successful question→SQL pair.

    Args:
        question: The user's original natural-language question.
        sql: The SQL query that successfully executed.
        results_summary: Optional short summary of the results (for context).
    """
    try:
        collection = _get_collection()

        # Use question as the document (embedded), store SQL in metadata
        # ID is a hash of the question to avoid duplicates for the same question
        doc_id = str(hash(question.strip().lower()))

        collection.upsert(
            ids=[doc_id],
            documents=[question],
            metadatas=[{
                "sql": sql,
                "results_summary": results_summary[:500],  # Truncate to keep payload small
            }],
        )
        logger.info("Stored query in memory: '%s'", question[:80])
    except Exception as exc:
        # Memory is a non-critical enhancement — never let it break the pipeline
        logger.warning("Failed to store query in memory: %s", exc)


def recall_similar(question: str, k: int = 3) -> list[dict[str, str]]:
    """Retrieve past queries semantically similar to the given question.

    Args:
        question: The user's current question.
        k: Number of similar past queries to retrieve.

    Returns:
        A list of dicts: [{"question": str, "sql": str}, ...]
        Empty list if no matches found or on error.
    """
    try:
        collection = _get_collection()

        results = collection.query(
            query_texts=[question],
            n_results=k,
        )

        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        # Filter out low-relevance matches (cosine distance > 0.5)
        recalls = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            if dist < 0.5:  # Cosine distance: 0 = identical, 1 = orthogonal
                recalls.append({
                    "question": doc,
                    "sql": meta.get("sql", ""),
                })
                logger.info("Memory recall (dist=%.3f): '%s'", dist, doc[:60])

        return recalls
    except Exception as exc:
        logger.warning("Memory recall failed: %s — continuing without memory.", exc)
        return []


def format_memory_examples(recalls: list[dict[str, str]]) -> str:
    """Format recalled queries as few-shot examples for prompt injection.

    Args:
        recalls: Output from recall_similar().

    Returns:
        A formatted string block, or empty string if no recalls.
    """
    if not recalls:
        return ""

    lines = ["--- SIMILAR PAST QUERIES (from memory) ---"]
    for r in recalls:
        lines.append(f"Q: {r['question']}")
        lines.append(f"SQL: {r['sql']}")
        lines.append("")
    return "\n".join(lines)
