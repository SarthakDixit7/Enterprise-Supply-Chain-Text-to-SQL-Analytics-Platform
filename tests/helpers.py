from __future__ import annotations

from typing import Any

from logisql.agent.llm import ChartSpec, SynthesisOutput

DEFAULT_SQL = (
    "SELECT order_status, COUNT(*) AS order_count "
    "FROM orders GROUP BY order_status ORDER BY order_count DESC"
)


class FakeLLM:
    """Deterministic LLM double for graph and API tests."""

    def __init__(
        self,
        *,
        generated_sql: list[str] | None = None,
        repairs: list[str] | None = None,
        synthesis: SynthesisOutput | None = None,
        synthesis_error: Exception | None = None,
    ) -> None:
        self.generated_sql = list(generated_sql or [DEFAULT_SQL])
        self.repairs = list(repairs or [DEFAULT_SQL])
        self.synthesis = synthesis or SynthesisOutput(
            headline="Order statuses are concentrated in delivered",
            summary="Delivered orders dominate the result set returned by the query.",
            key_takeaways=["Delivered orders are the largest status group."],
            chart=ChartSpec(
                type="bar",
                x="order_status",
                y="order_count",
                title="Orders by status",
            ),
        )
        self.synthesis_error = synthesis_error
        self.calls: dict[str, int] = {"generate": 0, "repair": 0, "synthesize": 0}
        self.repair_errors: list[str] = []

    async def generate_sql(
        self, *, question: str, schema_context: str, dialect: str, row_limit: int
    ) -> str:
        self.calls["generate"] += 1
        if len(self.generated_sql) > 1:
            return self.generated_sql.pop(0)
        return self.generated_sql[0]

    async def repair_sql(
        self,
        *,
        question: str,
        schema_context: str,
        dialect: str,
        previous_sql: str,
        error: str,
        attempt: int,
        row_limit: int,
    ) -> str:
        self.calls["repair"] += 1
        self.repair_errors.append(error)
        if len(self.repairs) > 1:
            return self.repairs.pop(0)
        return self.repairs[0]

    async def synthesize(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        row_count: int,
        truncated: bool,
    ) -> SynthesisOutput:
        self.calls["synthesize"] += 1
        if self.synthesis_error:
            raise self.synthesis_error
        return self.synthesis
