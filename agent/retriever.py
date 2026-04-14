"""
retriever.py — RAG-based schema retrieval from ChromaDB.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv
import chromadb

from db.chroma_client import get_chroma_client, get_embedding_function

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = "schema_index"
_client: Optional[chromadb.ClientAPI] = None
_collection: Optional[chromadb.Collection] = None


def _get_collection() -> chromadb.Collection:
    """Lazily initialise and cache the ChromaDB collection."""
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = get_chroma_client()
    embedding_fn = get_embedding_function()
    
    _collection = _client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    return _collection


def get_relevant_schema(query: str, k: int = 3) -> str:
    """
    Embed *query*, similarity-search ChromaDB, and return a formatted
    table+column block suitable for injection into an LLM prompt.

    Args:
        query: The user's natural-language question.
        k:     Number of most relevant tables to retrieve.

    Returns:
        A newline-delimited schema block string.
    """
    try:
        collection = _get_collection()
        
        # Performance Note: We removed collection.count() because it adds a 
        # synchronous network round-trip to Chroma Cloud on every query.
        results = collection.query(query_texts=[query], n_results=k)
        
        documents: list[str] = results["documents"][0] if results["documents"] else []  # type: ignore[index]
        logger.debug("Retrieved %d schema snippets for query: %s", len(documents), query)
        return "\n\n---\n\n".join(documents)
    except Exception as exc:
        logger.warning("Schema retrieval failed: %s — falling back to empty context.", exc)
        return ""
