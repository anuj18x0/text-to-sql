"""
reasoning.py — Query Decomposition Engine.

Breaks complex multi-part questions into ordered sub-queries that can
each be executed independently and then synthesized into a unified answer.

Example:
  "Why did revenue drop last month?"
  → sub-queries:
    1. "What was total revenue this month?"
    2. "What was total revenue last month?"
    3. "Revenue by category comparison: this month vs last month"

Only triggered when the intent classifier tags a question as "complex".
Simple aggregation, comparison, trend, and lookup queries bypass decomposition
entirely and go through the standard single-query pipeline.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from services.llm_service import get_fast_llm

logger = logging.getLogger(__name__)


@dataclass
class SubQuery:
    """A single sub-query in a decomposed query plan."""
    id: int
    question: str
    purpose: str  # Why this sub-query is needed


@dataclass
class QueryPlan:
    """An ordered plan of sub-queries to answer a complex question."""
    original_question: str
    sub_queries: list[SubQuery] = field(default_factory=list)
    is_decomposed: bool = False

    @property
    def count(self) -> int:
        return len(self.sub_queries)


DECOMPOSITION_PROMPT = """You are a data analysis strategist for an e-commerce database.

A user asked a complex question that requires multiple SQL queries to answer properly.
Break it into 2-4 simpler, independent sub-queries that together answer the original question.

Rules:
1. Each sub-query must be answerable by a single SQL SELECT statement.
2. Order sub-queries logically (dependencies first).
3. Keep each sub-query focused on ONE metric or comparison.
4. Maximum 4 sub-queries — don't over-decompose.
5. If the question is actually simple, return just 1 sub-query.

Original Question: {question}

Return valid JSON ONLY:
{{
  "sub_queries": [
    {{"id": 1, "question": "...", "purpose": "..."}},
    {{"id": 2, "question": "...", "purpose": "..."}}
  ]
}}"""


SYNTHESIS_PROMPT = """You are a data analyst. Synthesize the results of multiple SQL sub-queries
into a concise, unified insight that answers the user's original question.

Original Question: {question}

Sub-query Results:
{sub_results}

Provide a clear, data-driven answer in 3-5 sentences. Include specific numbers.
Do NOT mention "sub-queries" or the analysis process — just present the findings naturally."""


async def decompose_question(question: str) -> QueryPlan:
    """Decompose a complex question into ordered sub-queries.

    Args:
        question: The user's complex natural-language question.

    Returns:
        A QueryPlan with sub-queries. On failure, returns a plan with
        the original question as the sole sub-query (graceful fallback).
    """
    try:
        llm = get_fast_llm()
        prompt = ChatPromptTemplate.from_template(DECOMPOSITION_PROMPT)
        chain = prompt | llm | StrOutputParser()

        response = await chain.ainvoke({"question": question})
        json_str = re.sub(r"```json\n?|\n?```", "", response).strip()
        data = json.loads(json_str)

        sub_queries = [
            SubQuery(
                id=sq["id"],
                question=sq["question"],
                purpose=sq.get("purpose", ""),
            )
            for sq in data.get("sub_queries", [])
        ]

        if not sub_queries:
            raise ValueError("No sub-queries returned")

        plan = QueryPlan(
            original_question=question,
            sub_queries=sub_queries,
            is_decomposed=len(sub_queries) > 1,
        )
        logger.info(
            "Decomposed '%s' into %d sub-queries: %s",
            question[:60], plan.count,
            [sq.question[:50] for sq in plan.sub_queries],
        )
        return plan

    except Exception as e:
        logger.warning("Query decomposition failed: %s — using original question.", e)
        return QueryPlan(
            original_question=question,
            sub_queries=[SubQuery(id=1, question=question, purpose="Direct query")],
            is_decomposed=False,
        )


async def synthesize_results(
    question: str,
    sub_results: list[dict[str, Any]],
) -> str:
    """Synthesize multiple sub-query results into a unified natural-language answer.

    Args:
        question: The user's original question.
        sub_results: List of dicts with keys "question", "sql", "results" for each sub-query.

    Returns:
        A synthesized insight string.
    """
    try:
        llm = get_fast_llm()
        prompt = ChatPromptTemplate.from_template(SYNTHESIS_PROMPT)
        chain = prompt | llm | StrOutputParser()

        # Format sub-results for the prompt
        formatted = []
        for i, sr in enumerate(sub_results, 1):
            preview = json.dumps(sr.get("results", [])[:5], default=str)
            formatted.append(
                f"Query {i}: {sr['question']}\n"
                f"SQL: {sr.get('sql', 'N/A')}\n"
                f"Results: {preview}\n"
            )

        response = await chain.ainvoke({
            "question": question,
            "sub_results": "\n".join(formatted),
        })
        return response.strip()

    except Exception as e:
        logger.warning("Result synthesis failed: %s", e)
        return ""
