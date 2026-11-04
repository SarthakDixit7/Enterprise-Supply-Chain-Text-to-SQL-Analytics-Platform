from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def langsmith_enabled() -> bool:
    """Return whether LangSmith tracing is configured for this process."""

    return os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true" and bool(
        os.getenv("LANGCHAIN_API_KEY")
    )


def tracing_metadata(
    *,
    request_id: str,
    question: str,
    model: str,
    row_limit: int,
) -> dict[str, Any]:
    """Build a LangGraph/LangChain run config without requiring LangSmith."""

    metadata: dict[str, Any] = {
        "request_id": request_id,
        "question_length": len(question),
        "model": model,
        "row_limit": row_limit,
        "app": "logisql-agent",
    }
    if langsmith_enabled():
        logger.info("LangSmith tracing enabled for request %s", request_id)
        metadata["langsmith_project"] = os.getenv("LANGCHAIN_PROJECT", "logisql-agent")
    return {
        "run_name": "logisql_text_to_sql",
        "tags": ["logisql", "text-to-sql", "langgraph"],
        "metadata": metadata,
    }
