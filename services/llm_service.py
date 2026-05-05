"""
services/llm_service.py — Centralized LLM management.

Provides singleton LLM instances for different tiers:
  - sql:  Primary model (gemini-2.5-flash, temp=0) for SQL generation
  - fast: Secondary model (gemini-3.1-flash-lite-preview, temp=0.3) for auxiliary tasks
  - embedding: Handled by chroma_client.py (Google Gemini embeddings)

All agent modules should import LLMs from here instead of creating their own.
"""

import os
import logging

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
logger = logging.getLogger(__name__)

# Module-level singletons
_llm_sql: ChatGoogleGenerativeAI | None = None
_llm_fast: ChatGoogleGenerativeAI | None = None

FAST_MODEL = "gemini-3.1-flash-lite-preview"


def get_sql_llm(temperature: float = 0) -> ChatGoogleGenerativeAI:
    """Return the primary SQL-generation LLM (deterministic, high accuracy)."""
    global _llm_sql
    if _llm_sql is None:
        _llm_sql = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL"),
            temperature=temperature,
            api_key=os.getenv("GEMINI_API_KEY", ""),
        )
        logger.info("Initialized SQL LLM: %s", os.getenv("GEMINI_MODEL"))
    return _llm_sql


def get_fast_llm(temperature: float = 0.1) -> ChatGoogleGenerativeAI:
    """Return the fast auxiliary LLM (expansion, viz, insight, intent)."""
    global _llm_fast
    if _llm_fast is None:
        model = os.getenv("GEMINI_FAST_MODEL", FAST_MODEL)
        _llm_fast = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            api_key=os.getenv("GEMINI_API_KEY", ""),
        )
        logger.info("Initialized Fast LLM: %s", model)
    return _llm_fast
