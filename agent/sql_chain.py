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
    """Uses LLM to suggest the best chart type for the given query."""
    try:
        llm = _get_llm(temperature=0)
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

async def _expand_query(question: str, history: list[HumanMessage | AIMessage]) -> str:
    """Uses LLM to turn conversational questions into descriptive search queries for RAG."""
    try:
        llm = _get_llm(temperature=0)
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
    """
    overall_start = time.monotonic()
    
    # 1. Cache Check
    history_str = str(history)
    normalized_q = f"{question.strip().lower()}|{history_str}"
    if normalized_q in _response_cache:
        cached = _response_cache[normalized_q]
        if time.monotonic() < cached["expires_at"]:
            logger.info("Streaming cached response for: %s", normalized_q)
            resp = cached["response"].copy()
            resp["latency_ms"] = int((time.monotonic() - overall_start) * 1000)
            resp["timing"] = {"retrieval_ms": 0, "llm_ms": 0, "execution_ms": 0}
            yield f"data: {json.dumps({'event': 'final_result', 'data': resp}, default=json_serializable)}\n\n"
            return
    
    timing = {"retrieval_ms": 0, "llm_ms": 0, "execution_ms": 0}
    generated_sql_chunks = []
    
    try:
        # --- QUERY EXPANSION (commented out for latency — saves ~3-4s) ---
        # yield f"data: {json.dumps({'event': 'status', 'data': 'Interpreting question...'}, default=json_serializable)}\n\n"
        # expansion_start = time.monotonic()
        # formatted_history = []
        # for turn in history:
        #     formatted_history.append(HumanMessage(content=turn["question"]))
        #     formatted_history.append(AIMessage(content=turn["sql"]))
        # expanded_q = await _expand_query(question, formatted_history)
        # --- END QUERY EXPANSION ---
        
        # 2. Retrieval (using raw question directly)
        yield f"data: {json.dumps({'event': 'status', 'data': 'Analyzing database schema...'}, default=json_serializable)}\n\n"
        retrieval_start = time.monotonic()
        schema_context = get_relevant_schema(question, k=3)
        timing["retrieval_ms"] = int((time.monotonic() - retrieval_start) * 1000)
        
        # 3. LLM Streaming
        few_shot = _load_few_shot_examples()
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("human", USER_PROMPT),
        ])
        
        formatted_history = []
        for turn in history:
            formatted_history.append(HumanMessage(content=turn["question"]))
            formatted_history.append(AIMessage(content=turn["sql"]))
            
        llm = _get_llm()
        chain = prompt | llm
        
        llm_start = time.monotonic()
        first_chunk = True
        
        async for chunk in chain.astream({
            "schema": schema_context,
            "examples": few_shot,
            "history": formatted_history,
            "question": question,
        }):
            if first_chunk:
                yield f"data: {json.dumps({'event': 'status', 'data': 'Generating SQL...'}, default=json_serializable)}\n\n"
                first_chunk = False
            
            content = chunk.content
            generated_sql_chunks.append(content)
            yield f"data: {json.dumps({'event': 'sql_chunk', 'data': content}, default=json_serializable)}\n\n"
            
        timing["llm_ms"] = int((time.monotonic() - llm_start) * 1000)
        
        # 4. Finalize SQL and Check HITL
        full_raw_sql = "".join(generated_sql_chunks)
        generated_sql = _extract_sql(full_raw_sql)
        tables_used = _extract_table_names(generated_sql)
        
        guard_result = check_sql(generated_sql)
        current_latency = int((time.monotonic() - overall_start) * 1000)
        
        if guard_result["requires_approval"]:
            final_resp = {
                "sql": generated_sql,
                "results": [],
                "tables_used": tables_used,
                "requires_approval": True,
                "approval_reason": guard_result.get("reason", ""),
                "latency_ms": current_latency,
                "timing": timing
            }
            _log_query(question, generated_sql, current_latency, tables_used, error=None)
            yield f"data: {json.dumps({'event': 'final_result', 'data': final_resp}, default=json_serializable)}\n\n"
            return
            
        # 5. Execution
        yield f"data: {json.dumps({'event': 'status', 'data': 'Executing query...'}, default=json_serializable)}\n\n"
        execution_start = time.monotonic()
        results = await asyncio.to_thread(_execute_sql, generated_sql)
        timing["execution_ms"] = int((time.monotonic() - execution_start) * 1000)
        
        overall_latency = int((time.monotonic() - overall_start) * 1000)
        _log_query(question, generated_sql, overall_latency, tables_used, error=None)
        
        # --- VISUALIZATION SUGGESTION (commented out for latency — saves ~3-4s) ---
        # viz_suggestion = await _suggest_visualization(question, generated_sql)
        # --- END VISUALIZATION ---
        
        final_response = {
            "sql": generated_sql,
            "results": results,
            "tables_used": tables_used,
            "requires_approval": False,
            "latency_ms": overall_latency,
            "timing": timing,
            # "visualization": viz_suggestion  # Re-enable when using Flash model
        }
        
        # Save to Cache
        _response_cache[normalized_q] = {
            "response": final_response,
            "expires_at": time.monotonic() + 3600
        }
        
        yield f"data: {json.dumps({'event': 'final_result', 'data': final_response}, default=json_serializable)}\n\n"

    except Exception as exc:
        overall_latency = int((time.monotonic() - overall_start) * 1000)
        logger.error("stream_query failed: %s", exc, exc_info=True)
        yield f"data: {json.dumps({'event': 'error', 'data': str(exc)}, default=json_serializable)}\n\n"

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

--- RELEVANT SCHEMA ---
{schema}

--- FEW-SHOT EXAMPLES ---
{examples}
"""

USER_PROMPT = "Question: {question}\n\nSQL:"


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





async def run_query(question: str, history: list[dict[str, str]] = []) -> dict[str, Any]:
    """
    Full LCEL pipeline: natural-language question → SQL → executed results.
    Includes a 1-hour local semantic cache and multi-turn context support.

    Args:
        question: User's natural language question.
        history: List of previous interaction turns: [{"question": str, "sql": str}, ...]
    """
    overall_start = time.monotonic()
    
    # Cache Check (Include history in the key to ensure contextual variations are separate)
    history_str = str(history)
    normalized_q = f"{question.strip().lower()}|{history_str}"
    if normalized_q in _response_cache:
        cached = _response_cache[normalized_q]
        if time.monotonic() < cached["expires_at"]:
            logger.info("Serving cached response for: %s", normalized_q)
            resp = cached["response"].copy()
            resp["latency_ms"] = int((time.monotonic() - overall_start) * 1000)
            resp["timing"] = {"retrieval_ms": 0, "llm_ms": 0, "execution_ms": 0}
            return resp
        else:
            del _response_cache[normalized_q]

    generated_sql = ""
    tables_used: list[str] = []
    error_msg: str | None = None
    timing = {
        "retrieval_ms": 0,
        "llm_ms": 0,
        "execution_ms": 0
    }

    try:
        # --- QUERY EXPANSION (commented out for latency — saves ~3-4s) ---
        # formatted_history = []
        # for turn in history:
        #     formatted_history.append(HumanMessage(content=turn["question"]))
        #     formatted_history.append(AIMessage(content=turn["sql"]))
        # expanded_q = await _expand_query(question, formatted_history)
        # --- END QUERY EXPANSION ---

        # Step 1: Retrieve relevant schema snippets via RAG
        retrieval_start = time.monotonic()
        schema_context = get_relevant_schema(question, k=3)
        timing["retrieval_ms"] = int((time.monotonic() - retrieval_start) * 1000)

        # Step 2: Load few-shot examples
        few_shot = _load_few_shot_examples()

        # Step 3: Build prompt with History
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="history"),
                ("human", USER_PROMPT),
            ]
        )

        # Step 4: Format History into ChatMessages
        formatted_history = []
        for turn in history:
            formatted_history.append(HumanMessage(content=turn["question"]))
            formatted_history.append(AIMessage(content=turn["sql"]))

        # Step 5: Get LLM and invoke
        llm = _get_llm()
        chain = prompt | llm

        llm_start = time.monotonic()
        response = await chain.ainvoke(
            {
                "schema": schema_context,
                "examples": few_shot,
                "history": formatted_history,
                "question": question,
            }
        )
        timing["llm_ms"] = int((time.monotonic() - llm_start) * 1000)

        generated_sql = _extract_sql(response.content)
        tables_used = _extract_table_names(generated_sql)

        # Step 6: HITL safety check
        guard_result = check_sql(generated_sql)
        current_latency = int((time.monotonic() - overall_start) * 1000)

        if guard_result["requires_approval"]:
            _log_query(question, generated_sql, current_latency, tables_used, error=None)
            return {
                "sql": generated_sql,
                "results": [],
                "tables_used": tables_used,
                "requires_approval": True,
                "approval_reason": guard_result.get("reason", ""),
                "latency_ms": current_latency,
                "timing": timing
            }

        # Step 7: Execute the SQL
        execution_start = time.monotonic()
        results = await asyncio.to_thread(_execute_sql, generated_sql)
        timing["execution_ms"] = int((time.monotonic() - execution_start) * 1000)

        overall_latency = int((time.monotonic() - overall_start) * 1000)

        # Step 8: Log to query_log
        _log_query(question, generated_sql, overall_latency, tables_used, error=None)
        
        # Extract token usage
        usage = response.usage_metadata or {}
        p_tokens = usage.get("input_tokens", 0)
        c_tokens = usage.get("output_tokens", 0)
        _update_token_log(p_tokens, c_tokens)

        # --- VISUALIZATION SUGGESTION (commented out for latency — saves ~3-4s) ---
        # viz_suggestion = await _suggest_visualization(question, generated_sql)
        # --- END VISUALIZATION ---

        final_response = {
            "sql": generated_sql,
            "results": results,
            "tables_used": tables_used,
            "requires_approval": False,
            "latency_ms": overall_latency,
            "timing": timing,
            # "visualization": viz_suggestion  # Re-enable when using Flash model
        }

        # Save to Cache (1 hour expiration)
        _response_cache[normalized_q] = {
            "response": final_response,
            "expires_at": time.monotonic() + 3600
        }

        return final_response

    except Exception as exc:
        overall_latency = int((time.monotonic() - overall_start) * 1000)
        error_msg = str(exc)
        logger.error("run_query failed: %s", exc, exc_info=True)
        _log_query(question, generated_sql, overall_latency, tables_used, error=error_msg)
        raise
