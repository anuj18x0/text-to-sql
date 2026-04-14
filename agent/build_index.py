#!/usr/bin/env python3
"""
build_index.py — One-time script to embed the semantic schema into ChromaDB.
"""

import os
import logging
from db.chroma_client import get_chroma_client, get_embedding_function
from agent.semantic_layer import SEMANTIC_SCHEMA

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

COLLECTION_NAME = "schema_index"

def serialize_table(table: dict) -> str:
    """Serialize a single table entry from SEMANTIC_SCHEMA to a plain-text string."""
    lines = [
        f"Table: {table['table_name']}",
        f"Description: {table['description']}",
        "Columns:",
    ]
    for col in table["columns"]:
        lines.append(f"  - {col['name']}: {col['description']}")
    return "\n".join(lines)

def build_index() -> None:
    """Embed every table in SEMANTIC_SCHEMA and persist vectors to ChromaDB."""
    client = get_chroma_client()
    embedding_fn = get_embedding_function()

    # Delete existing collection to allow clean re-indexing
    try:
        client.delete_collection(COLLECTION_NAME)
        logger.info("Deleted existing collection '%s'", COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for table in SEMANTIC_SCHEMA:
        text = serialize_table(table)
        documents.append(text)
        metadatas.append({"table_name": table["table_name"]})
        ids.append(table["table_name"])
        logger.info("Prepared embedding for table: %s", table["table_name"])

    logger.info("Upserting %d documents into ChromaDB...", len(documents))
    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    logger.info("Index build complete. %d tables indexed.", len(documents))

if __name__ == "__main__":
    build_index()
