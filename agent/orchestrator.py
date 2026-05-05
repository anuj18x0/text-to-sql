"""
orchestrator.py — Agent Pipeline Orchestrator (Custom FSM).

Replaces the monolithic stream_query() function with a staged pipeline:

  CLASSIFY_INTENT → EXPAND_QUERY → RECALL_MEMORY → RETRIEVE_SCHEMA
  → [DECOMPOSE] → GENERATE_SQL → EXECUTE → HEAL → INSIGHT → VISUALIZE → STORE

Each stage is a separate async function, making the pipeline:
  - Testable: each stage can be unit-tested independently
  - Extensible: new stages can be added without modifying existing ones
  - Observable: each stage emits SSE events for real-time frontend updates

For "complex" intent queries, the DECOMPOSE stage breaks the question into
sub-queries and runs each through a simplified sub-pipeline, then synthesizes
the results into a unified response.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent.hitl_guard import check_sql
from agent.insight_engine import generate_insight
from agent.intent import classify_intent, QueryIntent
from agent.memory import recall_similar, store_query, format_memory_examples
from agent.reasoning import decompose_question, synthesize_results
from agent.retriever import get_relevant_schema
from services.llm_service import get_sql_llm, get_fast_llm
from services.sql_service import (
    extract_sql, extract_table_names, execute_sql,
    fix_sql, execute_with_retry, log_query,
)
from services.rag_service import get_context

logger = logging.getLogger(__name__)

# In-memory response cache
_response_cache: dict[str, dict[str, Any]] = {}


def _json_serializable(obj):
    """Helper for json.dumps to handle Decimal and datetime."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _sse(event: str, data: Any) -> str:
    """Format a Server-Sent Event payload."""
    return f"data: {json.dumps({'event': event, 'data': data}, default=_json_serializable)}\n\n"


# ─── Prompt Templates ────────────────────────────────────────────────────────

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

QUERY_EXPANSION_PROMPT = """You are a SQL data assistant. Transform the user's conversational question into a detailed, technical search query focused on database entities (tables/columns) and metrics. 

Rules:
1. If the question is already specific, keep it mostly as is.
2. If the question is vague (e.g., 'How is business?'), expand it to include key metrics like total revenue, order count, and customer satisfaction.
3. Use the conversation history to resolve pronouns or context.

History: {history}
Question: {question}

Expanded Query:"""


# ─── Pipeline Stages ─────────────────────────────────────────────────────────

async def _stage_expand_and_classify(
    question: str,
    history: list[dict[str, str]],
) -> tuple[str, QueryIntent]:
    """Stage 2a: Run query expansion and intent classification in parallel."""
    formatted_history = []
    for turn in history:
        formatted_history.append(HumanMessage(content=turn["question"]))
        formatted_history.append(AIMessage(content=turn["sql"]))

    async def _expand():
        try:
            from langchain_core.output_parsers import StrOutputParser
            llm = get_fast_llm()
            prompt = ChatPromptTemplate.from_template(QUERY_EXPANSION_PROMPT)
            chain = prompt | llm | StrOutputParser()
            history_str = "\n".join(
                [f"{msg.__class__.__name__}: {msg.content}" for msg in formatted_history[-3:]]
            )
            expanded = await chain.ainvoke({"question": question, "history": history_str})
            logger.info("Expanded query: '%s' -> '%s'", question, expanded)
            return expanded
        except Exception as e:
            logger.warning("Query expansion failed: %s", e)
            return question

    expansion_task = asyncio.create_task(_expand())
    intent_task = asyncio.create_task(classify_intent(question))
    expanded_q, intent = await asyncio.gather(expansion_task, intent_task)
    return expanded_q, intent


async def _stage_retrieve_context(
    question: str,
    expanded_question: str,
) -> dict[str, str]:
    """Stage 2b-2c: Memory recall + schema retrieval."""
    return get_context(question, expanded_question, k=3)


async def _stage_generate_sql(
    question: str,
    schema_context: str,
    combined_examples: str,
    intent_context: str,
    history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    """Stage 3: Stream SQL generation from the primary LLM.
    
    Yields raw content chunks (not SSE-formatted).
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="history"),
        ("human", USER_PROMPT),
    ])

    formatted_history = []
    for turn in history:
        formatted_history.append(HumanMessage(content=turn["question"]))
        formatted_history.append(AIMessage(content=turn["sql"]))

    llm = get_sql_llm()
    chain = prompt | llm

    async for chunk in chain.astream({
        "schema": schema_context,
        "examples": combined_examples,
        "intent": intent_context,
        "history": formatted_history,
        "question": question,
    }):
        yield chunk.content


async def _stage_suggest_visualization(question: str, sql: str) -> dict[str, Any]:
    """Stage 6a: Use fast LLM to suggest chart type."""
    try:
        import re
        llm = get_fast_llm()
        from langchain_core.output_parsers import StrOutputParser
        prompt = ChatPromptTemplate.from_template(VISUALIZATION_PROMPT)
        chain = prompt | llm | StrOutputParser()
        response = await chain.ainvoke({"question": question, "sql": sql})
        json_str = re.sub(r"```json\n?|\n?```", "", response).strip()
        return json.loads(json_str)
    except Exception as e:
        logger.warning("Failed to suggest visualization: %s", e)
        return {"type": "none"}


# ─── Sub-pipeline for decomposed queries ─────────────────────────────────────

async def _run_sub_query(
    sub_question: str,
    schema_context: str,
    combined_examples: str,
) -> dict[str, Any]:
    """Run a single sub-query through a simplified pipeline (no streaming)."""
    try:
        # Generate SQL (non-streaming for sub-queries)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", USER_PROMPT),
        ])
        llm = get_sql_llm()
        from langchain_core.output_parsers import StrOutputParser
        chain = prompt | llm | StrOutputParser()

        raw_sql = await chain.ainvoke({
            "schema": schema_context,
            "examples": combined_examples,
            "intent": "",
            "question": sub_question,
        })
        sql = extract_sql(raw_sql)

        # Execute with retry
        final_sql, results, retries = await execute_with_retry(
            sql, sub_question, schema_context, max_retries=1,
        )

        return {
            "question": sub_question,
            "sql": final_sql,
            "results": results,
            "success": True,
        }
    except Exception as e:
        logger.warning("Sub-query failed: '%s' — %s", sub_question[:60], e)
        return {
            "question": sub_question,
            "sql": "",
            "results": [],
            "success": False,
            "error": str(e),
        }


# ─── Main Orchestrator ───────────────────────────────────────────────────────

async def orchestrate_query(
    question: str,
    history: list[dict[str, str]] = [],
) -> AsyncGenerator[str, None]:
    """Full agent pipeline orchestrator — yields SSE events.

    This is the main entry point that replaces stream_query().
    It runs through all stages and handles both simple and complex queries.
    """
    overall_start = time.monotonic()

    # 1. Cache Check
    history_str = str(history)
    normalized_q = f"{question.strip().lower()}|{history_str}"
    if normalized_q in _response_cache:
        cached = _response_cache[normalized_q]
        if time.monotonic() < cached["expires_at"]:
            logger.info("Serving cached response for: %s", normalized_q[:80])
            resp = cached["response"].copy()
            resp["latency_ms"] = int((time.monotonic() - overall_start) * 1000)
            resp["timing"] = {"retrieval_ms": 0, "llm_ms": 0, "execution_ms": 0}
            yield _sse("final_result", resp)
            return

    timing = {"retrieval_ms": 0, "llm_ms": 0, "execution_ms": 0}

    try:
        # 2a. Parallel: Intent Classification + Query Expansion
        yield _sse("status", "Interpreting question...")
        expanded_q, intent = await _stage_expand_and_classify(question, history)

        # 2b-2c. Context retrieval (memory + schema + few-shot)
        yield _sse("status", "Analyzing database schema...")
        retrieval_start = time.monotonic()
        context = await asyncio.to_thread(
            get_context, question, expanded_q, 3
        )
        timing["retrieval_ms"] = int((time.monotonic() - retrieval_start) * 1000)

        schema_context = context["schema"]
        combined_examples = context["examples"]
        intent_context = intent.to_prompt_context()

        # ── COMPLEX QUERY: Decompose and run sub-queries ──
        if intent.intent_type == "complex":
            yield _sse("status", "Decomposing complex question...")
            plan = await decompose_question(question)

            if plan.is_decomposed:
                yield _sse("status", f"Running {plan.count} sub-queries...")

                # Run all sub-queries in parallel
                sub_tasks = [
                    _run_sub_query(sq.question, schema_context, combined_examples)
                    for sq in plan.sub_queries
                ]
                sub_results = await asyncio.gather(*sub_tasks)

                # Synthesize results
                yield _sse("status", "Synthesizing results...")
                synthesis = await synthesize_results(question, sub_results)

                # Collect all SQL and results
                all_sql = "\n\n-- Sub-query separator --\n\n".join(
                    sr["sql"] for sr in sub_results if sr.get("sql")
                )
                all_results = []
                all_tables = set()
                for sr in sub_results:
                    all_results.extend(sr.get("results", []))
                    for t in extract_table_names(sr.get("sql", "")):
                        all_tables.add(t)

                overall_latency = int((time.monotonic() - overall_start) * 1000)
                log_query(question, all_sql, overall_latency, list(all_tables), error=None, retry_count=0, success=True)

                # Store in memory
                store_query(question, all_sql, synthesis[:200])

                final_response = {
                    "sql": all_sql,
                    "results": all_results[:150],  # Cap to prevent huge payloads
                    "tables_used": list(all_tables),
                    "requires_approval": False,
                    "latency_ms": overall_latency,
                    "timing": timing,
                    "retry_count": 0,
                    "visualization": {"type": "none"},
                    "insight": synthesis,
                    "is_decomposed": True,
                    "sub_query_count": plan.count,
                }

                _response_cache[normalized_q] = {
                    "response": final_response,
                    "expires_at": time.monotonic() + 3600,
                }

                yield _sse("final_result", final_response)
                return

        # ── SIMPLE QUERY: Standard single-query pipeline ──

        # 3. LLM Streaming
        generated_sql_chunks = []
        llm_start = time.monotonic()
        first_chunk = True

        async for chunk_content in _stage_generate_sql(
            question, schema_context, combined_examples, intent_context, history
        ):
            if first_chunk:
                yield _sse("status", "Generating SQL...")
                first_chunk = False
            generated_sql_chunks.append(chunk_content)
            yield _sse("sql_chunk", chunk_content)

        timing["llm_ms"] = int((time.monotonic() - llm_start) * 1000)

        # 4. Finalize SQL and Check HITL
        full_raw_sql = "".join(generated_sql_chunks)
        generated_sql = extract_sql(full_raw_sql)
        tables_used = extract_table_names(generated_sql)

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
                "timing": timing,
            }
            log_query(question, generated_sql, current_latency, tables_used, error=None, retry_count=0, success=True)
            yield _sse("final_result", final_resp)
            return

        # 5. Execution with Self-Healing Retry Loop
        yield _sse("status", "Executing query...")
        execution_start = time.monotonic()

        current_sql = generated_sql
        last_error = None
        results = None
        retry_count = 0

        for attempt in range(1 + 2):  # MAX_RETRIES = 2
            try:
                results = await asyncio.to_thread(execute_sql, current_sql)
                generated_sql = current_sql
                break
            except Exception as exec_err:
                last_error = str(exec_err)
                retry_count = attempt + 1
                if attempt < 2:
                    logger.warning(
                        "SQL execution failed (attempt %d/3): %s",
                        attempt + 1, last_error,
                    )
                    yield _sse("status", f"Fixing SQL (attempt {attempt + 2})...")
                    fixed = await fix_sql(question, current_sql, last_error, schema_context)
                    logger.info("Self-healed SQL: %s", fixed)
                    yield _sse("sql_fix", fixed)
                    current_sql = fixed
                else:
                    raise exec_err

        timing["execution_ms"] = int((time.monotonic() - execution_start) * 1000)

        # 6. Parallel: Visualization + Insight generation
        yield _sse("status", "Generating insights...")
        viz_task = asyncio.create_task(_stage_suggest_visualization(question, generated_sql))
        insight_task = asyncio.create_task(generate_insight(question, generated_sql, results))
        viz_suggestion, insight_text = await asyncio.gather(viz_task, insight_task)

        overall_latency = int((time.monotonic() - overall_start) * 1000)
        log_query(question, generated_sql, overall_latency, tables_used, error=None, retry_count=retry_count, success=True)

        # 7. Store in memory
        results_summary = json.dumps(results[:3], default=str)[:200] if results else ""
        store_query(question, generated_sql, results_summary)

        final_response = {
            "sql": generated_sql,
            "results": results,
            "tables_used": tables_used,
            "requires_approval": False,
            "latency_ms": overall_latency,
            "timing": timing,
            "retry_count": retry_count,
            "visualization": viz_suggestion,
            "insight": insight_text,
        }

        _response_cache[normalized_q] = {
            "response": final_response,
            "expires_at": time.monotonic() + 3600,
        }

        yield _sse("final_result", final_response)

    except Exception as exc:
        overall_latency = int((time.monotonic() - overall_start) * 1000)
        logger.error("orchestrate_query failed: %s", exc, exc_info=True)
        log_query(question, "", overall_latency, [], error=str(exc), retry_count=0, success=False)
        yield _sse("error", str(exc))
