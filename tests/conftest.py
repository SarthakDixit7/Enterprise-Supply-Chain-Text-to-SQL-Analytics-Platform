from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from logisql.agent.graph import LogiSQLAgent
from logisql.config import Settings
from logisql.db.engine import create_engine
from logisql.db.executor import QueryExecutor
from logisql.db.schema import SchemaService
from logisql.db.seed import seed_demo_database
from tests.helpers import FakeLLM

ALLOWED = "orders,order_items,products,sellers,order_payments"


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    database_path = tmp_path / "logisql_test.db"
    seed_demo_database(database_path, order_count=120, force=True)
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        allowed_tables=ALLOWED,
        allow_demo_seed=True,
        groq_api_key="test-key",
        max_retries=2,
        default_row_limit=100,
        max_row_limit=500,
        query_timeout_ms=5_000,
        schema_cache_ttl_seconds=300,
    )


@pytest_asyncio.fixture
async def engine(test_settings: Settings):
    db_engine = create_engine(test_settings)
    try:
        yield db_engine
    finally:
        await db_engine.dispose()


@pytest.fixture
def schema_service(engine, test_settings) -> SchemaService:
    return SchemaService(engine=engine, settings=test_settings)


@pytest.fixture
def executor(engine, test_settings) -> QueryExecutor:
    return QueryExecutor(engine=engine, settings=test_settings)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def agent(
    test_settings: Settings,
    schema_service: SchemaService,
    executor: QueryExecutor,
    fake_llm: FakeLLM,
) -> LogiSQLAgent:
    return LogiSQLAgent(
        settings=test_settings,
        schema_service=schema_service,
        executor=executor,
        llm=fake_llm,
    )
