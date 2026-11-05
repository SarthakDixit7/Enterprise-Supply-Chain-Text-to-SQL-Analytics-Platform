from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from logisql import __version__
from logisql.agent.graph import LogiSQLAgent
from logisql.agent.llm import AnalyticsLLM, GroqAnalyticsLLM, LLMConfigurationError
from logisql.api.container import AppContainer
from logisql.api.routes import (
    ServerBusyError,
    llm_configuration_error_response,
    router,
    server_busy_response,
)
from logisql.config import Settings, configure_logging, get_settings
from logisql.db.engine import create_engine
from logisql.db.executor import QueryExecutor
from logisql.db.overview import OverviewService
from logisql.db.schema import SchemaService
from logisql.db.seed import ensure_demo_database

logger = logging.getLogger(__name__)
_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9._-]")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)

    if settings.is_sqlite and settings.allow_demo_seed:
        counts = await asyncio.to_thread(ensure_demo_database, settings)
        if counts:
            logger.info(
                "SQLite demo database ready (%s orders, %s items)",
                counts.get("orders", 0),
                counts.get("order_items", 0),
            )

    engine = create_engine(settings)
    schema_service = SchemaService(engine=engine, settings=settings)
    executor = QueryExecutor(engine=engine, settings=settings)
    overview_service = OverviewService(
        executor=executor, allowed_tables=settings.allowed_table_set
    )
    llm: AnalyticsLLM = app.state.llm_override or GroqAnalyticsLLM(settings)
    agent = LogiSQLAgent(
        settings=settings,
        schema_service=schema_service,
        executor=executor,
        llm=llm,
    )
    app.state.container = AppContainer(
        settings=settings,
        engine=engine,
        schema_service=schema_service,
        overview_service=overview_service,
        executor=executor,
        llm=llm,
        agent=agent,
        query_semaphore=asyncio.Semaphore(settings.max_concurrent_queries),
    )
    logger.info(
        "LogiSQL API started | env=%s | db=%s | llm=%s | concurrency=%s",
        settings.environment,
        executor.dialect,
        settings.groq_model,
        settings.max_concurrent_queries,
    )

    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Database engine disposed.")


def create_app(
    settings: Settings | None = None,
    *,
    llm: AnalyticsLLM | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title="LogiSQL-Agent API",
        description=(
            "Guarded, self-correcting text-to-SQL analytics over the Olist "
            "e-commerce and logistics dataset."
        ),
        version=__version__,
        lifespan=lifespan,
        contact={"name": "LogiSQL-Agent"},
    )
    app.state.settings = resolved_settings
    app.state.llm_override = llm

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        incoming = request.headers.get("x-request-id", "")
        request_id = _REQUEST_ID_RE.sub("", incoming)[:64] or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.exception_handler(LLMConfigurationError)
    async def _llm_configuration_handler(
        request: Request, exc: LLMConfigurationError
    ) -> JSONResponse:
        return llm_configuration_error_response(request, exc)

    @app.exception_handler(ServerBusyError)
    async def _server_busy_handler(request: Request, exc: ServerBusyError) -> JSONResponse:
        return server_busy_response(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled API error for request %s", request_id)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error. Check the API logs.",
                "request_id": request_id,
            },
        )

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "name": "LogiSQL-Agent API",
            "version": __version__,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()


__all__ = ["app", "create_app"]
