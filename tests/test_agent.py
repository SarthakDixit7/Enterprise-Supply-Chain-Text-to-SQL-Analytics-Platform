from __future__ import annotations

import pytest

from logisql.agent.graph import LogiSQLAgent
from logisql.agent.llm import LLMConfigurationError
from logisql.config import Settings
from logisql.db.executor import QueryExecutor
from logisql.db.schema import SchemaService
from tests.helpers import DEFAULT_SQL, FakeLLM


async def test_agent_end_to_end(agent: LogiSQLAgent, fake_llm: FakeLLM) -> None:
    result = await agent.run(
        question="How many orders are there by status?",
        request_id="test-success",
    )

    assert result["status"] == "success"
    assert result["row_count"] > 0
    assert result["columns"] == ["order_status", "order_count"]
    assert result["sql"] == DEFAULT_SQL
    assert result["chart"] is not None
    assert result["retry_count"] == 0
    assert result["attempt_count"] == 1
    assert fake_llm.calls == {"generate": 1, "repair": 0, "synthesize": 1}
    assert result["total_ms"] >= 0
    assert any(item["node"] == "execute" for item in result["node_timings"])


async def test_agent_repairs_guardrail_failure(agent: LogiSQLAgent, fake_llm: FakeLLM) -> None:
    fake_llm.generated_sql = ["SELECT * FROM customers"]
    fake_llm.repairs = [DEFAULT_SQL]

    result = await agent.run(question="Invalid table", request_id="test-repair")

    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert result["attempt_count"] == 2
    assert fake_llm.calls["repair"] == 1
    kinds = [attempt["kind"] for attempt in result["attempts"]]
    assert "validation_failed" in kinds
    assert "repaired" in kinds


async def test_agent_repairs_database_error(agent: LogiSQLAgent, fake_llm: FakeLLM) -> None:
    fake_llm.generated_sql = ["SELECT nonexistent_column FROM orders"]
    fake_llm.repairs = [DEFAULT_SQL]

    result = await agent.run(question="Bad column", request_id="test-db-repair")

    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert fake_llm.repair_errors
    assert "nonexistent_column" in fake_llm.repair_errors[0].lower()
    kinds = [attempt["kind"] for attempt in result["attempts"]]
    assert "execution_failed" in kinds


async def test_agent_stops_after_retry_budget(agent: LogiSQLAgent, fake_llm: FakeLLM) -> None:
    fake_llm.generated_sql = ["SELECT * FROM customers"]
    fake_llm.repairs = ["SELECT * FROM customers", "SELECT * FROM customers"]

    result = await agent.run(question="Still invalid", request_id="test-failure")

    assert result["status"] == "failed"
    assert result["retry_count"] == 2
    assert result["attempt_count"] == 3
    assert not result.get("rows")
    assert "allowlisted" in result["error"].lower()


async def test_agent_falls_back_when_synthesis_fails(
    agent: LogiSQLAgent, fake_llm: FakeLLM
) -> None:
    fake_llm.synthesis_error = RuntimeError("narration unavailable")

    result = await agent.run(question="How many orders?", request_id="test-fallback")

    assert result["status"] == "success"
    assert result["row_count"] > 0
    assert result["warnings"]
    assert "deterministic" in result["warnings"][0].lower()
    assert result["headline"].startswith("Query returned")


async def test_agent_requires_groq_key(
    test_settings: Settings,
    schema_service: SchemaService,
    executor: QueryExecutor,
    fake_llm: FakeLLM,
) -> None:
    settings = test_settings.model_copy(update={"groq_api_key": None})
    unconfigured = LogiSQLAgent(
        settings=settings,
        schema_service=schema_service,
        executor=executor,
        llm=fake_llm,
    )

    with pytest.raises(LLMConfigurationError):
        await unconfigured.run(question="Anything", request_id="test-no-key")
