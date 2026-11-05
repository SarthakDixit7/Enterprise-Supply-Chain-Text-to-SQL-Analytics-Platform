from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from logisql.agent.graph import LogiSQLAgent
from logisql.agent.llm import AnalyticsLLM
from logisql.api.metrics import QueryMetrics
from logisql.config import Settings
from logisql.db.executor import QueryExecutor
from logisql.db.overview import OverviewService
from logisql.db.schema import SchemaService


@dataclass
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    schema_service: SchemaService
    overview_service: OverviewService
    executor: QueryExecutor
    llm: AnalyticsLLM
    agent: LogiSQLAgent
    query_semaphore: asyncio.Semaphore
    metrics: QueryMetrics
