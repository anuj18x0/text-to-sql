"""
sql_chain.py — LangChain LCEL pipeline: question → SQL → results.

# NOTE: LCEL chain composition explained
# LangChain Expression Language (LCEL) lets you compose chains using the pipe
# operator (|). Each component receives the output of the previous one as input.
# Our pipeline:
#   1. Retrieve relevant schema (RAG)     → inject into prompt context
#   2. Load few-shot YAML examples        → inject into prompt for in-context learning
#   3. Build ChatPromptTemplate           → structured system + user messages
#   4. Call LLM (temperature=0)           → deterministic, no creativity in SQL
#   5. Parse SQL from response            → extract the raw SQL string
#   6. HITL check                         → flag writes for human approval
#   7. Execute if approved (SELECT only)  → run against SQLite/PostgreSQL
#   8. Log to query_log                   → observability + debugging
#
# temperature=0 is critical: we want the most deterministic SQL possible.
# Any creativity in SQL generation leads to incorrect queries.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy import text

from agent.hitl_guard import check_sql
from agent.insight_engine import generate_insight
from agent.intent import classify_intent
from agent.memory import recall_similar, store_query, format_memory_examples
from agent.retriever import get_relevant_schema
from model.database import get_engine, get_session
from model.schema import Base, QueryLog

load_dotenv()

logger = logging.getLogger(__name__)

# Module-level caches
_llm_sql: ChatGoogleGenerativeAI | None = None
_llm_fast: ChatGoogleGenerativeAI | None = None
_cached_examples: str | None = None
_response_cache: dict[str, dict[str, Any]] = {}  # {normalized_question: {"response": dict, "expires_at": float}}


def _get_llm(temperature: float = 0) -> ChatGoogleGenerativeAI:
    """Return a cached LLM instance. Uses module-level singleton."""
    global _llm_sql
    if _llm_sql is None:
        _llm_sql = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL"),
            temperature=temperature,
            api_key=os.getenv("GEMINI_API_KEY", ""),
        )
    return _llm_sql


def json_serializable(obj):
    """Helper for json.dumps to handle non-serializable types like Decimal and datetime."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


VISUALIZATION_PROMPT = """You are a data visualization expert. Analyze the SQL query and the user's question to suggest the best way to visualize the data. 
Available types: 'bar', 'line', 'pie', 'none'.

Rules:
1. 'line' is for time-series (dates/months).
2. 'bar' is for comparing categories or numerical values.
3. 'pie' is for parts-of-a-whole (only if categories < 10).
4. 'none' if the result is just a single number, a long list of text, or not suitable for charts.

Question: {question}
SQL: {sql}

Return valid JSON ONLY:
{{
  "type": "bar" | "line" | "pie" | "none",
  "x": "column_name_to_use_for_x_axis",
  "y": "column_name_to_use_for_y_axis",
  "title": "A short descriptive title"
}}"""

async def _suggest_visualization(question: str, sql: str) -> dict[str, Any]:
    """Uses fast LLM to suggest the best chart type for the given query."""
    try:
        llm = _get_fast_llm()
        prompt = ChatPromptTemplate.from_template(VISUALIZATION_PROMPT)
        chain = prompt | llm | StrOutputParser()
        
        response = await chain.ainvoke({"question": question, "sql": sql})
        # Extract JSON if LLM returned it in markdown blocks
        json_str = re.sub(r"```json\n?|\n?```", "", response).strip()
        data = json.loads(json_str)
        return data
    except Exception as e:
        logger.warning("Failed to suggest visualization: %s", e)
        return {"type": "none"}


QUERY_EXPANSION_PROMPT = """You are a SQL data assistant. Transform the user's conversational question into a detailed, technical search query focused on database entities (tables/columns) and metrics. 

Rules:
1. If the question is already specific, keep it mostly as is.
2. If the question is vague (e.g., 'How is business?'), expand it to include key metrics like total revenue, order count, and customer satisfaction.
3. Use the conversation history to resolve pronouns or context.

History: {history}
Question: {question}

Expanded Query:"""

# Secondary fast LLM for auxiliary tasks (expansion, visualization, insights)
_llm_fast_instance: ChatGoogleGenerativeAI | None = None
FAST_MODEL = "gemini-3.1-flash-lite-preview"

def _get_fast_llm() -> ChatGoogleGenerativeAI:
    """Return a cached fast LLM for auxiliary tasks (expansion, viz, insight)."""
    global _llm_fast_instance
    if _llm_fast_instance is None:
        _llm_fast_instance = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_FAST_MODEL", FAST_MODEL),
            temperature=0.3,
            api_key=os.getenv("GEMINI_API_KEY", ""),
        )
    return _llm_fast_instance


async def _expand_query(question: str, history: list[HumanMessage | AIMessage]) -> str:
    """Uses fast LLM to turn conversational questions into descriptive search queries for RAG."""
    try:
        llm = _get_fast_llm()
        prompt = ChatPromptTemplate.from_template(QUERY_EXPANSION_PROMPT)
        chain = prompt | llm | StrOutputParser()
        
        # Format history for expansion prompt
        history_str = "\n".join([f"{msg.__class__.__name__}: {msg.content}" for msg in history[-3:]])
        expanded = await chain.ainvoke({"question": question, "history": history_str})
        logger.info("Expanded query: '%s' -> '%s'", question, expanded)
        return expanded
    except Exception as e:
        logger.warning("Query expansion failed: %s", e)
        return question

async def stream_query(question: str, history: list[dict[str, str]] = []):
    """
    Async generator for real-time SQL streaming.
    Yields JSON-encoded chunks for Server-Sent Events (SSE).
    
    Delegates to the orchestrator pipeline which handles:
    - Intent classification + query expansion (parallel)
    - Memory recall + schema retrieval
    - Query decomposition for complex questions
    - SQL generation with streaming
    - Self-healing retry loop
    - Visualization + insight generation (parallel)
    - Memory storage
    """
    from agent.orchestrator import orchestrate_query
    
    async for event in orchestrate_query(question, history):
        yield event

SYSTEM_PROMPT = """You are an expert PostgreSQL analyst for the Olist Brazilian E-Commerce database.

Your task: Given a natural-language question, write a single, correct SQL SELECT query.

Rules:
1. Output ONLY the SQL query — no explanation, no markdown fences, no commentary.
2. Use only tables and columns present in the schema context below.
3. Use table aliases (e.g. fo for fact_orders, dp for dim_products).
4. Always qualify column names with table aliases.
5. NEVER use SELECT aliases in WHERE, GROUP BY, or HAVING clauses. Repeat the full aggregate expression instead (e.g., HAVING AVG(col) > 1).
6. For date operations, use PostgreSQL syntax (e.g., EXTRACT, AGE, or INTERVAL math). Avoid SQLite-specific functions like strftime.
7. Limit results to 1000 rows unless the question asks for all rows.
8. Never generate INSERT, UPDATE, DELETE, or DROP statements.

{intent}

--- RELEVANT SCHEMA ---
{schema}

--- FEW-SHOT EXAMPLES ---
{examples}
"""

USER_PROMPT = "Question: {question}\n\nSQL:"

SQL_FIX_PROMPT = """You are an expert PostgreSQL debugger. The following SQL query failed with an error.
Fix the query so it runs correctly. Output ONLY the corrected SQL — no explanation.

Original Question: {question}
Failed SQL: {sql}
Error: {error}

--- RELEVANT SCHEMA ---
{schema}

Corrected SQL:"""

MAX_RETRIES = 2  # Maximum number of self-healing attempts


async def _fix_sql(question: str, failed_sql: str, error: str, schema_context: str) -> str:
    """Ask the LLM to fix a broken SQL query using the error message."""
    llm = _get_llm()
    prompt = ChatPromptTemplate.from_template(SQL_FIX_PROMPT)
    chain = prompt | llm | StrOutputParser()
    
    response = await chain.ainvoke({
        "question": question,
        "sql": failed_sql,
        "error": error,
        "schema": schema_context,
    })
    return _extract_sql(response)


def _load_few_shot_examples() -> str:
    """Load and format few-shot examples from the YAML file (cached)."""
    global _cached_examples
    if _cached_examples is not None:
        return _cached_examples

    try:
        yaml_path = os.path.join(os.path.dirname(__file__), "few_shot_examples.yaml")
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


def _extract_sql(raw_response: str) -> str:
    """Strip markdown code fences and whitespace from the LLM response."""
    # Remove ```sql ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"```(?:sql)?", "", raw_response, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()
    # Remove any leading "SQL:" label the model might add
    cleaned = re.sub(r"^SQL:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _extract_table_names(sql: str) -> list[str]:
    """Heuristically extract table names referenced in a SQL query."""
    known_tables = {
        "fact_orders",
        "dim_users",
        "dim_products",
        "dim_sellers",
        "dim_geography",
        "dim_reviews",
    }
    sql_upper = sql.upper()
    found = [t for t in known_tables if t.upper() in sql_upper]
    return found


def _ensure_schema_exists() -> None:
    """Create all tables (including query_log) if they don't exist yet."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def _log_query(
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


def _execute_sql(sql: str) -> list[dict[str, Any]]:
    """Run a SQL query and return results as a list of dicts.

    Only single-statement SELECT or WITH (CTE) queries are permitted.
    Any other statement type, or a multi-statement payload, raises ValueError
    so callers receive a clear error instead of executing unexpected SQL.

    A LIMIT clause is injected for SELECT queries so that the response stays
    manageable.
    """
    _MAX_ROWS = 150
    normalised = sql.strip()

    # Reject multi-statement payloads: strip one trailing semicolon then check
    # for any remaining semicolons which would indicate a second statement.
    if ";" in normalised.rstrip(";"):
        raise ValueError("Multi-statement SQL is not allowed")

    # Allowlist: only SELECT and WITH (CTEs that start WITH … SELECT) are safe
    # read-only operations.  Everything else (PRAGMA, ATTACH, INSERT, …) is
    # rejected here regardless of what upstream guards may have passed.
    first_token = normalised.split()[0].upper() if normalised.split() else ""
    if first_token not in {"SELECT", "WITH"}:
        raise ValueError(
            f"Only SELECT/WITH queries are permitted; got: {first_token!r}"
        )

    normalised_upper = normalised.upper()
    if first_token == "SELECT" and "LIMIT" not in normalised_upper:
        sql = normalised.rstrip(";").rstrip() + f" LIMIT {_MAX_ROWS}"
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]


TOKEN_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token_usage.txt")


def _update_token_log(prompt_tokens: int, completion_tokens: int):
    """Updates the cumulative token counts in a local text file."""
    total_input = 0
    total_output = 0

    # Read existing totals if the file exists
    if os.path.exists(TOKEN_LOG_PATH):
        try:
            with open(TOKEN_LOG_PATH, "r") as f:
                content = f.read()
                for line in content.strip().split("\n"):
                    if "input_tokens=" in line:
                        total_input = int(line.split("=")[1])
                    elif "output_tokens=" in line:
                        total_output = int(line.split("=")[1])
        except (ValueError, IndexError, Exception):
            pass  # Fallback to zero if file is missing or malformed

    total_input += prompt_tokens
    total_output += completion_tokens

    with open(TOKEN_LOG_PATH, "w") as f:
        f.write(f"input_tokens={total_input}\n")
        f.write(f"output_tokens={total_output}\n")

