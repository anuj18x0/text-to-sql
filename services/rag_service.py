"""
services/rag_service.py — Unified RAG context assembly.

Combines three context sources into a single enriched prompt payload:
  1. Schema retrieval (ChromaDB vector search)
  2. Memory recall (past query→SQL pairs)
  3. Static few-shot examples (YAML)

The orchestrator calls `get_context()` once and receives everything it needs
to build the SQL generation prompt.
"""

import logging
import os
from typing import Any

import yaml

from agent.memory import recall_similar, format_memory_examples
from agent.retriever import get_relevant_schema

logger = logging.getLogger(__name__)

# Module-level cache for YAML few-shot examples
_cached_examples: str | None = None


def _load_few_shot_examples() -> str:
    """Load and format few-shot examples from the YAML file (cached)."""
    global _cached_examples
    if _cached_examples is not None:
        return _cached_examples

    try:
        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "agent", "few_shot_examples.yaml"
        )
        with open(yaml_path, "r") as fh:
            data = yaml.safe_load(fh)
        lines: list[str] = []
        for ex in data.get("examples", []):
            lines.append(f"Q: {ex['question']}")
            lines.append(f"SQL: {ex['sql'].strip()}")
            lines.append("")
        _cached_examples = "\n".join(lines)
        return _cached_examples
    except Exception as exc:
        logger.warning("Failed to load few-shot examples: %s", exc)
        return ""


import concurrent.futures

def get_context(question: str, expanded_question: str | None = None, k: int = 3) -> dict[str, str]:
    """Assemble all RAG context for the SQL generation prompt.

    Args:
        question: The user's original question (used for memory recall).
        expanded_question: The query-expanded version (used for schema retrieval).
                          Falls back to the original question if not provided.
        k: Number of schema tables and memory examples to retrieve.

    Returns:
        A dict with keys:
          - "schema": Relevant table definitions from ChromaDB
          - "examples": Combined static + dynamic few-shot examples
    """
    search_query = expanded_question or question

    # 1 & 2. Parallel Schema retrieval and Memory recall
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        schema_future = executor.submit(get_relevant_schema, search_query, k)
        memory_future = executor.submit(recall_similar, question, k)
        
        schema_context = schema_future.result()
        memory_examples = memory_future.result()

    memory_context = format_memory_examples(memory_examples)

    # 3. Static few-shot examples
    few_shot = _load_few_shot_examples()

    # Combine static + dynamic examples
    combined_examples = few_shot
    if memory_context:
        combined_examples = few_shot + "\n\n" + memory_context

    return {
        "schema": schema_context,
        "examples": combined_examples,
    }
