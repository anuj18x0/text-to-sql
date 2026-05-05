"""
intent.py — Lightweight intent classifier for natural-language queries.

Extracts structured metadata from the user's question before SQL generation:
  - entities: database concepts mentioned (tables, columns, business terms)
  - metrics: what to measure (total, average, trend, count, etc.)
  - filters: conditions (time ranges, status, geography)
  - intent_type: classification of the query complexity

This metadata serves two purposes:
  1. Improves RAG retrieval — entity names guide which schema tables to fetch
  2. Enriches the SQL prompt — the LLM knows the user wants a "trend" vs "lookup"

Uses the fast LLM model to keep latency under ~1s.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from services.llm_service import get_fast_llm

logger = logging.getLogger(__name__)

# Re-use the same fast model singleton pattern
_llm_intent: ChatGoogleGenerativeAI | None = None
FAST_MODEL = "gemini-3.1-flash-lite-preview"


# def _get_fast_llm() -> ChatGoogleGenerativeAI:
#     """Return a cached fast LLM for intent classification."""
#     global _llm_intent
#     if _llm_intent is None:
#         _llm_intent = ChatGoogleGenerativeAI(
#             model=os.getenv("GEMINI_FAST_MODEL", FAST_MODEL),
#             temperature=0,
#             api_key=os.getenv("GEMINI_API_KEY", ""),
#         )
#     return _llm_intent


@dataclass
class QueryIntent:
    """Structured representation of a user's query intent."""
    entities: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    intent_type: str = "lookup"  # aggregation | comparison | trend | lookup | complex

    def to_prompt_context(self) -> str:
        """Format as a block for injection into the SQL generation prompt."""
        lines = ["--- QUERY INTENT ---"]
        lines.append(f"Type: {self.intent_type}")
        if self.entities:
            lines.append(f"Entities: {', '.join(self.entities)}")
        if self.metrics:
            lines.append(f"Metrics: {', '.join(self.metrics)}")
        if self.filters:
            lines.append(f"Filters: {', '.join(self.filters)}")
        return "\n".join(lines)


INTENT_PROMPT = """You are a database query intent classifier for an e-commerce analytics database.

Analyze the user's question and extract structured metadata.

Available tables: fact_orders, dim_users, dim_products, dim_sellers, dim_geography, dim_reviews
Available intent types:
- "aggregation": SUM, COUNT, AVG over data (e.g. "total revenue", "how many orders")
- "comparison": comparing two or more groups (e.g. "which state has more", "top 10 sellers")
- "trend": time-series analysis (e.g. "monthly revenue", "growth over time")
- "lookup": simple data retrieval (e.g. "show me orders from SP", "list products")
- "complex": multi-step reasoning needed (e.g. "why did revenue drop", "correlation between X and Y")

Question: {question}

Return valid JSON ONLY:
{{
  "entities": ["list of database entities/business concepts mentioned"],
  "metrics": ["list of measurements: total, average, count, rate, trend, etc."],
  "filters": ["list of conditions: time ranges, statuses, locations, etc."],
  "intent_type": "aggregation" | "comparison" | "trend" | "lookup" | "complex"
}}"""


async def classify_intent(question: str) -> QueryIntent:
    """Classify a user's question into structured intent metadata.

    Args:
        question: The user's natural-language question.

    Returns:
        QueryIntent dataclass with extracted entities, metrics, filters, and type.
        Returns a sensible default on failure (never raises).
    """
    try:
        llm = get_fast_llm()
        prompt = ChatPromptTemplate.from_template(INTENT_PROMPT)
        chain = prompt | llm | StrOutputParser()

        response = await chain.ainvoke({"question": question})

        # Extract JSON from potential markdown wrapping
        json_str = re.sub(r"```json\n?|\n?```", "", response).strip()
        data = json.loads(json_str)

        intent = QueryIntent(
            entities=data.get("entities", []),
            metrics=data.get("metrics", []),
            filters=data.get("filters", []),
            intent_type=data.get("intent_type", "lookup"),
        )
        logger.info(
            "Intent classified: type=%s, entities=%s, metrics=%s",
            intent.intent_type, intent.entities, intent.metrics
        )
        return intent

    except Exception as e:
        logger.warning("Intent classification failed: %s — using default.", e)
        return QueryIntent()
