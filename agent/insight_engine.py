"""
insight_engine.py — Generate natural-language insights from SQL query results.

Uses a fast LLM model to convert raw data into concise, human-readable
summaries. Called in parallel with visualization suggestion after SQL execution,
so it doesn't add to the critical-path latency.
"""

import json
import logging
import os
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from services.llm_service import get_fast_llm

logger = logging.getLogger(__name__)

# Module-level singleton for the fast insight model
_llm_insight: ChatGoogleGenerativeAI | None = None

FAST_MODEL = "gemini-3.1-flash-lite-preview"


# def _get_fast_llm() -> ChatGoogleGenerativeAI:
#     """Return a cached fast LLM instance optimised for auxiliary tasks."""
#     global _llm_insight
#     if _llm_insight is None:
#         _llm_insight = ChatGoogleGenerativeAI(
#             model=os.getenv("GEMINI_FAST_MODEL", FAST_MODEL),
#             temperature=0.3,
#             api_key=os.getenv("GEMINI_API_KEY", ""),
#         )
#     return _llm_insight


INSIGHT_PROMPT = """You are a concise data analyst. Given a user's question and the SQL query results, write a brief 2-3 sentence insight.

Rules:
1. Lead with the most important finding.
2. Include specific numbers from the data.
3. If the data shows a clear trend or outlier, mention it.
4. Keep it under 50 words.
5. Do NOT repeat the question or say "Based on the results".

Question: {question}
SQL: {sql}
Results (first 10 rows): {results}

Insight:"""


async def generate_insight(
    question: str,
    sql: str,
    results: list[dict[str, Any]],
) -> str:
    """Generate a brief natural-language insight from query results.

    Args:
        question: The user's original question.
        sql: The executed SQL query.
        results: The query result rows (list of dicts).

    Returns:
        A short insight string, or an empty string on failure.
    """
    if not results:
        return "The query returned no results."

    try:
        llm = get_fast_llm()
        prompt = ChatPromptTemplate.from_template(INSIGHT_PROMPT)
        chain = prompt | llm | StrOutputParser()

        # Limit rows sent to the LLM to keep the payload small
        preview = json.dumps(results[:10], default=str)

        insight = await chain.ainvoke({
            "question": question,
            "sql": sql,
            "results": preview,
        })
        return insight.strip()
    except Exception as e:
        logger.warning("Insight generation failed: %s", e)
        return ""
