from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from logisql.agent.graph import LogiSQLAgent
from logisql.agent.llm import AnalyticsLLM
from logisql.config import Settings
from logisql.db.executor import QueryExecutor
from logisql.db.schema import SchemaService


@dataclass
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    schema_service: SchemaService
    executor: QueryExecutor
    llm: AnalyticsLLM
    agent: LogiSQLAgent
