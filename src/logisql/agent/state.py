from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class AgentState(TypedDict, total=False):
    request_id: str
    question: str
    dialect: str
    row_limit: int

    schema_context: str
    schema_table_count: int

    candidate_sql: str
    sql: str
    validation_error: str | None
    execution_error: str | None

    attempt_count: int
    retry_count: int

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_ms: float

    headline: str
    summary: str
    key_takeaways: list[str]
    chart: dict[str, Any] | None
    chart_spec: dict[str, Any] | None

    status: Literal["success", "failed"]
    error: str | None

    warnings: Annotated[list[str], operator.add]
    attempts: Annotated[list[dict[str, Any]], operator.add]
    node_timings: Annotated[list[dict[str, Any]], operator.add]


def initial_state(
    *,
    request_id: str,
    question: str,
    dialect: str,
    row_limit: int,
) -> AgentState:
    return AgentState(
        request_id=request_id,
        question=question,
        dialect=dialect,
        row_limit=row_limit,
        retry_count=0,
        attempt_count=0,
        warnings=[],
        attempts=[],
        node_timings=[],
        status="failed",
        error=None,
        chart=None,
        chart_spec=None,
        key_takeaways=[],
    )


__all__ = ["AgentState", "initial_state"]
