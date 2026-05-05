"""
api/routes/analytics.py — /api/analytics metrics endpoint.

Provides aggregated performance metrics from the query_log table:
SQL success rate, average latency, retry stats, and usage trends.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from model.database import get_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
async def get_analytics() -> dict[str, Any]:
    """
    Return aggregated query metrics for the dashboard.

    Response includes:
    - total_queries: Total number of queries processed
    - success_rate: Percentage of queries without errors
    - avg_latency_ms: Average response latency in milliseconds
    - avg_retry_count: Average number of self-healing retries
    - top_tables: Most frequently queried tables
    - daily_queries: Queries per day over the last 7 days
    """
    engine = get_engine()

    try:
        with engine.connect() as conn:
            # --- Core metrics ---
            row = conn.execute(text("""
                SELECT
                    COUNT(*)                                          AS total_queries,
                    ROUND(100.0 * SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END)
                          / NULLIF(COUNT(*), 0), 1)                  AS success_rate,
                    ROUND(AVG(latency_ms)::numeric, 0)               AS avg_latency_ms,
                    ROUND(AVG(COALESCE(retry_count, 0))::numeric, 2) AS avg_retry_count
                FROM query_log
            """)).mappings().fetchone()

            metrics = dict(row) if row else {
                "total_queries": 0,
                "success_rate": 100.0,
                "avg_latency_ms": 0,
                "avg_retry_count": 0.0,
            }

            # --- Top tables ---
            top_tables_raw = conn.execute(text("""
                SELECT tables_used, COUNT(*) AS cnt
                FROM query_log
                WHERE tables_used IS NOT NULL AND tables_used != ''
                GROUP BY tables_used
                ORDER BY cnt DESC
                LIMIT 10
            """)).mappings().fetchall()

            # Explode comma-separated table names and re-aggregate
            table_counts: dict[str, int] = {}
            for r in top_tables_raw:
                for table in str(r["tables_used"]).split(","):
                    t = table.strip()
                    if t:
                        table_counts[t] = table_counts.get(t, 0) + int(r["cnt"])
            top_tables = sorted(table_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            # --- Daily queries (last 7 days) ---
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            daily_raw = conn.execute(text("""
                SELECT DATE(created_at) AS day, COUNT(*) AS count
                FROM query_log
                WHERE created_at >= :since
                GROUP BY DATE(created_at)
                ORDER BY day ASC
            """), {"since": seven_days_ago}).mappings().fetchall()

            daily_queries = [
                {"date": str(r["day"]), "count": int(r["count"])}
                for r in daily_raw
            ]

        return {
            "total_queries": int(metrics.get("total_queries", 0)),
            "success_rate": float(metrics.get("success_rate", 100.0) or 100.0),
            "avg_latency_ms": int(metrics.get("avg_latency_ms", 0) or 0),
            "avg_retry_count": float(metrics.get("avg_retry_count", 0.0) or 0.0),
            "top_tables": [{"table": t, "count": c} for t, c in top_tables],
            "daily_queries": daily_queries,
        }

    except Exception as exc:
        logger.error("Analytics query failed: %s", exc, exc_info=True)
        return {
            "total_queries": 0,
            "success_rate": 0.0,
            "avg_latency_ms": 0,
            "avg_retry_count": 0.0,
            "top_tables": [],
            "daily_queries": [],
            "error": str(exc),
        }
