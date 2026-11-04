from __future__ import annotations

import logging
import time
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from logisql.agent.charts import build_chart
from logisql.agent.guardrails import GuardrailError, SQLGuardrail
from logisql.agent.llm import (
    AnalyticsLLM,
    LLMConfigurationError,
    LLMResponseError,
)
from logisql.agent.state import AgentState, initial_state
from logisql.agent.synthesis import fallback_synthesis
from logisql.config import Settings
from logisql.db.executor import QueryExecutionError, QueryExecutor
from logisql.db.schema import SchemaService
from logisql.observability import tracing_metadata

logger = logging.getLogger(__name__)


def _timing(node: str, started: float) -> list[dict[str, Any]]:
    return [{"node": node, "ms": round((time.perf_counter() - started) * 1000, 2)}]


class LogiSQLAgent:
    """LangGraph workflow: schema -> generate -> guard -> execute -> repair -> narrate."""

    def __init__(
        self,
        *,
        settings: Settings,
        schema_service: SchemaService,
        executor: QueryExecutor,
        llm: AnalyticsLLM,
    ) -> None:
        self.settings = settings
        self.schema_service = schema_service
        self.executor = executor
        self.llm = llm
        self.guardrail = SQLGuardrail(
            allowed_tables=settings.allowed_table_set,
            dialect=executor.dialect,
            allowed_schema=settings.database_schema,
        )
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentState)
        builder.add_node("schema", self._introspect_schema)
        builder.add_node("generate", self._generate_sql)
        builder.add_node("validate", self._validate_sql)
        builder.add_node("execute", self._execute_sql)
        builder.add_node("repair", self._repair_sql)
        builder.add_node("synthesize", self._synthesize)
        builder.add_node("finalize", self._finalize_failure)

        builder.add_edge(START, "schema")
        builder.add_edge("schema", "generate")
        builder.add_edge("generate", "validate")
        builder.add_conditional_edges(
            "validate",
            self._route_after_validation,
            {"execute": "execute", "repair": "repair", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "execute",
            self._route_after_execution,
            {"synthesize": "synthesize", "repair": "repair", "finalize": "finalize"},
        )
        builder.add_edge("repair", "validate")
        builder.add_edge("synthesize", END)
        builder.add_edge("finalize", END)
        return builder.compile()

    async def run(
        self,
        *,
        question: str,
        request_id: str,
        row_limit: int | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_configured:
            raise LLMConfigurationError(
                "GROQ_API_KEY is not configured. Add it to .env to enable the agent."
            )

        limit = min(
            row_limit or self.settings.default_row_limit,
            self.settings.max_row_limit,
        )
        state = initial_state(
            request_id=request_id,
            question=question,
            dialect=self.executor.dialect,
            row_limit=limit,
        )
        started = time.perf_counter()
        config = tracing_metadata(
            request_id=request_id,
            question=question,
            model=self.settings.groq_model,
            row_limit=limit,
        )

        try:
            result = await self.graph.ainvoke(state, config=config)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            logger.exception("Agent run failed for request %s", request_id)
            message = " ".join(str(exc).split())[:1000]
            result = dict(state)
            result.update(
                {
                    "status": "failed",
                    "error": f"Agent execution failed: {message}",
                    "headline": "Agent execution failed",
                    "summary": (
                        "The agent could not complete this request. Check the API logs and "
                        "the configured Groq/database credentials."
                    ),
                    "key_takeaways": [],
                    "chart": None,
                    "chart_spec": None,
                }
            )

        result["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
        result.setdefault("warnings", [])
        result.setdefault("attempts", [])
        result.setdefault("node_timings", [])
        result.setdefault("status", "failed")
        return result

    async def _introspect_schema(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        schema = await self.schema_service.get()
        return {
            "schema_context": schema.prompt_context(),
            "schema_table_count": len(schema.tables),
            "warnings": schema.warnings,
            "node_timings": _timing("schema", started),
        }

    async def _generate_sql(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        sql = await self.llm.generate_sql(
            question=state["question"],
            schema_context=state["schema_context"],
            dialect=state["dialect"],
            row_limit=state["row_limit"],
        )
        return {
            "candidate_sql": sql,
            "attempt_count": 1,
            "validation_error": None,
            "execution_error": None,
            "attempts": [
                {
                    "attempt": 1,
                    "kind": "generated",
                    "sql": sql,
                }
            ],
            "node_timings": _timing("generate", started),
        }

    async def _validate_sql(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        attempt = state.get("attempt_count", 1)
        try:
            normalized = self.guardrail.validate(state.get("candidate_sql", ""))
        except GuardrailError as exc:
            return {
                "validation_error": str(exc),
                "attempts": [
                    {
                        "attempt": attempt,
                        "kind": "validation_failed",
                        "error": str(exc),
                    }
                ],
                "node_timings": _timing("validate", started),
            }
        return {
            "sql": normalized,
            "validation_error": None,
            "execution_error": None,
            "attempts": [
                {
                    "attempt": attempt,
                    "kind": "validated",
                    "sql": normalized,
                }
            ],
            "node_timings": _timing("validate", started),
        }

    async def _execute_sql(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        attempt = state.get("attempt_count", 1)
        try:
            result = await self.executor.execute(state["sql"], row_limit=state["row_limit"])
        except QueryExecutionError as exc:
            return {
                "execution_error": str(exc),
                "attempts": [
                    {
                        "attempt": attempt,
                        "kind": "execution_failed",
                        "error": str(exc),
                    }
                ],
                "node_timings": _timing("execute", started),
            }
        return {
            "execution_error": None,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_ms": result.elapsed_ms,
            "attempts": [
                {
                    "attempt": attempt,
                    "kind": "executed",
                    "row_count": result.row_count,
                    "truncated": result.truncated,
                }
            ],
            "node_timings": _timing("execute", started),
        }

    async def _repair_sql(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        retry_count = state.get("retry_count", 0) + 1
        attempt_count = state.get("attempt_count", 1) + 1
        error = state.get("execution_error") or state.get("validation_error") or "Unknown SQL error"
        previous_sql = state.get("candidate_sql") or state.get("sql") or ""

        sql = await self.llm.repair_sql(
            question=state["question"],
            schema_context=state["schema_context"],
            dialect=state["dialect"],
            previous_sql=previous_sql,
            error=error,
            attempt=retry_count,
            row_limit=state["row_limit"],
        )
        return {
            "candidate_sql": sql,
            "attempt_count": attempt_count,
            "retry_count": retry_count,
            "validation_error": None,
            "execution_error": None,
            "attempts": [
                {
                    "attempt": attempt_count,
                    "kind": "repaired",
                    "retry": retry_count,
                    "previous_error": error,
                    "sql": sql,
                }
            ],
            "node_timings": _timing("repair", started),
        }

    async def _synthesize(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        warnings: list[str] = []
        columns = state.get("columns", [])
        rows = state.get("rows", [])
        row_count = state.get("row_count", 0)
        truncated = state.get("truncated", False)

        if row_count == 0:
            synthesis = fallback_synthesis(
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
            )
        else:
            try:
                synthesis = await self.llm.synthesize(
                    question=state["question"],
                    sql=state.get("sql", ""),
                    columns=columns,
                    rows=rows,
                    row_count=row_count,
                    truncated=truncated,
                )
            except (LLMResponseError, ValueError, RuntimeError) as exc:
                logger.warning("Synthesis failed for request %s: %s", state["request_id"], exc)
                warnings.append(
                    "The executive narrative could not be generated; showing a deterministic summary."
                )
                synthesis = fallback_synthesis(
                    columns=columns,
                    rows=rows,
                    row_count=row_count,
                    truncated=truncated,
                    reason=str(exc),
                )

        chart, chart_warning = build_chart(
            rows=rows,
            columns=columns,
            requested=synthesis.chart,
        )
        if chart_warning:
            warnings.append(chart_warning)

        return {
            "status": "success",
            "headline": synthesis.headline,
            "summary": synthesis.summary,
            "key_takeaways": synthesis.key_takeaways,
            "chart": chart,
            "chart_spec": synthesis.chart.model_dump() if synthesis.chart else None,
            "error": None,
            "warnings": warnings,
            "node_timings": _timing("synthesize", started),
        }

    async def _finalize_failure(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        error = (
            state.get("execution_error")
            or state.get("validation_error")
            or state.get("error")
            or "The agent could not produce a safe, executable query."
        )
        sql = state.get("sql") or state.get("candidate_sql")
        return {
            "status": "failed",
            "error": error,
            "sql": sql,
            "headline": "Could not answer this question",
            "summary": (
                "The generated SQL could not pass validation and execution after the "
                "configured repair attempts. Rephrase the question or add more schema context."
            ),
            "key_takeaways": [
                "No result was returned because the agent stopped on a safety or SQL error.",
                "Review the attempt trail for the exact failure.",
            ],
            "chart": None,
            "chart_spec": None,
            "node_timings": _timing("finalize", started),
        }

    def _route_after_validation(
        self, state: AgentState
    ) -> Literal["execute", "repair", "finalize"]:
        if not state.get("validation_error"):
            return "execute"
        if state.get("retry_count", 0) < self.settings.max_retries:
            return "repair"
        return "finalize"

    def _route_after_execution(
        self, state: AgentState
    ) -> Literal["synthesize", "repair", "finalize"]:
        if not state.get("execution_error"):
            return "synthesize"
        if state.get("retry_count", 0) < self.settings.max_retries:
            return "repair"
        return "finalize"


__all__ = ["LogiSQLAgent"]
