from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from logisql.agent.llm import LLMConfigurationError
from logisql.api.container import AppContainer
from logisql.api.schemas import (
    ExampleQuestion,
    ExamplesResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
)
from logisql.db.engine import ping_database

logger = logging.getLogger(__name__)
router = APIRouter()

EXAMPLES = [
    ExampleQuestion(
        category="Revenue",
        question=(
            "Which product categories generated the most item revenue from delivered "
            "orders in 2018? Show the top 10."
        ),
    ),
    ExampleQuestion(
        category="Delivery",
        question=(
            "Which seller states have the longest average delivery time in days for "
            "delivered orders? Show states with at least 20 delivered orders."
        ),
    ),
    ExampleQuestion(
        category="Seller quality",
        question=(
            "Which sellers have the highest on-time delivery rate among sellers with "
            "at least 20 delivered orders? Show the top 10."
        ),
    ),
    ExampleQuestion(
        category="Trends",
        question=(
            "How did monthly order volume and total freight value trend between "
            "January 2017 and August 2018?"
        ),
    ),
    ExampleQuestion(
        category="Freight",
        question=(
            "What are the top 10 product categories by average freight cost as a "
            "percentage of item price?"
        ),
    ),
    ExampleQuestion(
        category="Payments",
        question="Which payment types have the highest average order value?",
    ),
    ExampleQuestion(
        category="Operations",
        question=(
            "What share of delivered orders arrived after the estimated delivery date, "
            "by product category? Show the 10 worst categories with at least 20 orders."
        ),
    ),
]


def _container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not initialized.")
    return container


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(request: Request) -> HealthResponse:
    container = _container(request)
    database_ok = await ping_database(container.engine)
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        app=container.settings.app_name,
        database=database_ok,
        llm_configured=container.settings.llm_configured,
        model=container.settings.groq_model,
        dialect=container.executor.dialect,
    )


@router.get("/schema", response_model=SchemaResponse, tags=["schema"])
async def schema(request: Request, force: bool = Query(default=False)) -> SchemaResponse:
    container = _container(request)
    introspected = await container.schema_service.get(force=force)
    relationships = [rel for table in introspected.tables for rel in table.relationships]
    return SchemaResponse(
        dialect=introspected.dialect,
        tables=introspected.tables,
        relationships=relationships,
        warnings=introspected.warnings,
        introspected_at=introspected.introspected_at,
    )


@router.get("/examples", response_model=ExamplesResponse, tags=["schema"])
async def examples() -> ExamplesResponse:
    return ExamplesResponse(examples=EXAMPLES)


@router.post("/query", response_model=QueryResponse, tags=["agent"])
async def query(request: Request, payload: QueryRequest) -> QueryResponse:
    container = _container(request)
    request_id = getattr(request.state, "request_id", "unknown")

    if not container.settings.llm_configured:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not configured on the API server. Add it to .env and restart."
        )

    result = await container.agent.run(
        question=payload.question,
        request_id=request_id,
        row_limit=payload.row_limit,
    )
    return QueryResponse(
        request_id=request_id,
        status=result.get("status", "failed"),
        question=payload.question,
        sql=result.get("sql"),
        headline=result.get("headline") or "Query complete",
        summary=result.get("summary") or "",
        key_takeaways=result.get("key_takeaways") or [],
        columns=result.get("columns") or [],
        rows=result.get("rows") or [],
        row_count=result.get("row_count") or 0,
        truncated=result.get("truncated") or False,
        chart=result.get("chart"),
        chart_spec=result.get("chart_spec"),
        attempt_count=result.get("attempt_count") or 0,
        retry_count=result.get("retry_count") or 0,
        attempts=result.get("attempts") or [],
        node_timings=result.get("node_timings") or [],
        total_ms=result.get("total_ms") or 0.0,
        execution_ms=result.get("execution_ms") or 0.0,
        model=container.settings.groq_model,
        schema_tables=result.get("schema_table_count") or 0,
        warnings=result.get("warnings") or [],
        error=result.get("error"),
    )


__all__ = ["router"]


def llm_configuration_error_response(request: Request, exc: LLMConfigurationError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "request_id": getattr(request.state, "request_id", None),
        },
    )
