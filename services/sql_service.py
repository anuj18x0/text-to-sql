"""
services/sql_service.py — SQL execution, validation, and self-healing.

Extracted from sql_chain.py to be independently testable and reusable
by both the single-query pipeline and the multi-query orchestrator.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import text

from model.database import get_engine, get_session
from model.schema import Base, QueryLog
from services.llm_service import get_sql_llm

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

SQL_FIX_PROMPT = """You are an expert PostgreSQL debugger. The following SQL query failed with an error.
Fix the query so it runs correctly. Output ONLY the corrected SQL — no explanation.

Original Question: {question}
Failed SQL: {sql}
Error: {error}

--- RELEVANT SCHEMA ---
{schema}

Corrected SQL:"""


def extract_sql(raw_response: str) -> str:
    """Strip markdown code fences and whitespace from the LLM response."""
    cleaned = re.sub(r"```(?:sql)?", "", raw_response, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()
    cleaned = re.sub(r"^SQL:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def extract_table_names(sql: str) -> list[str]:
    """Heuristically extract table names referenced in a SQL query."""
    known_tables = {
        "fact_orders", "dim_users", "dim_products",
        "dim_sellers", "dim_geography", "dim_reviews",
    }
    sql_upper = sql.upper()
    return [t for t in known_tables if t.upper() in sql_upper]


def execute_sql(sql: str) -> list[dict[str, Any]]:
    """Run a SQL query and return results as a list of dicts.

    Only single-statement SELECT or WITH (CTE) queries are permitted.
    A LIMIT clause is injected for SELECT queries.
    """
    _MAX_ROWS = 150
    normalised = sql.strip()

    if ";" in normalised.rstrip(";"):
        raise ValueError("Multi-statement SQL is not allowed")

    first_token = normalised.split()[0].upper() if normalised.split() else ""
    if first_token not in {"SELECT", "WITH"}:
        raise ValueError(f"Only SELECT/WITH queries are permitted; got: {first_token!r}")

    normalised_upper = normalised.upper()
    if first_token == "SELECT" and "LIMIT" not in normalised_upper:
        sql = normalised.rstrip(";").rstrip() + f" LIMIT {_MAX_ROWS}"

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]


async def fix_sql(question: str, failed_sql: str, error: str, schema_context: str) -> str:
    """Ask the LLM to fix a broken SQL query using the error message."""
    llm = get_sql_llm()
    prompt = ChatPromptTemplate.from_template(SQL_FIX_PROMPT)
    chain = prompt | llm | StrOutputParser()

    response = await chain.ainvoke({
        "question": question,
        "sql": failed_sql,
        "error": error,
        "schema": schema_context,
    })
    return extract_sql(response)


async def execute_with_retry(
    sql: str,
    question: str,
    schema_context: str,
    max_retries: int = MAX_RETRIES,
) -> tuple[str, list[dict[str, Any]], int]:
    """Execute SQL with self-healing retry loop.

    Returns:
        (final_sql, results, retry_count)
    """
    current_sql = sql
    retry_count = 0

    for attempt in range(1 + max_retries):
        try:
            results = await asyncio.to_thread(execute_sql, current_sql)
            return current_sql, results, retry_count
        except Exception as exec_err:
            retry_count = attempt + 1
            if attempt < max_retries:
                logger.warning(
                    "SQL execution failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, str(exec_err),
                )
                current_sql = await fix_sql(question, current_sql, str(exec_err), schema_context)
                logger.info("Self-healed SQL: %s", current_sql)
            else:
                raise exec_err

    # Should never reach here, but satisfy type checker
    return current_sql, [], retry_count


def log_query(
    question: str,
    generated_sql: str,
    latency_ms: int,
    tables_used: list[str],
    error: str | None,
    retry_count: int = 0,
    success: bool = True,
) -> None:
    """Persist a query execution record to the query_log table."""
    try:
        with get_session() as session:
            log_entry = QueryLog(
                question=question,
                generated_sql=generated_sql,
                latency_ms=latency_ms,
                tables_used=",".join(tables_used),
                error=error,
                retry_count=retry_count,
                success=success,
                created_at=datetime.utcnow(),
            )
            session.add(log_entry)
            session.commit()
    except Exception as exc:
        logger.error("Failed to write to query_log: %s", exc)


def ensure_schema_exists() -> None:
    """Create all tables (including query_log) if they don't exist yet."""
    engine = get_engine()
    Base.metadata.create_all(engine)
