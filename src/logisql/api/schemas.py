from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from logisql.db.overview import DatasetOverview
from logisql.db.schema import TableInfo


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    database: bool
    llm_configured: bool
    model: str
    dialect: str


class OverviewResponse(DatasetOverview):
    """Aggregate dataset snapshot exposed by the API."""


class SchemaResponse(BaseModel):
    dialect: str
    tables: list[TableInfo]
    relationships: list[str]
    warnings: list[str]
    introspected_at: float


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    row_limit: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if len(cleaned) < 3:
            raise ValueError("question must contain at least 3 non-whitespace characters")
        return cleaned


class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    attempt: int
    kind: str
    sql: str | None = None
    error: str | None = None
    row_count: int | None = None
    retry: int | None = None
    previous_error: str | None = None


class NodeTiming(BaseModel):
    node: str
    ms: float


class QueryResponse(BaseModel):
    request_id: str
    status: Literal["success", "failed"]
    question: str
    sql: str | None = None
    headline: str
    summary: str
    key_takeaways: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    chart: dict[str, Any] | None = None
    chart_spec: dict[str, Any] | None = None
    attempt_count: int = 0
    retry_count: int = 0
    attempts: list[AttemptRecord] = Field(default_factory=list)
    node_timings: list[NodeTiming] = Field(default_factory=list)
    total_ms: float = 0.0
    execution_ms: float = 0.0
    model: str
    schema_tables: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class ExampleQuestion(BaseModel):
    category: str
    question: str


class ExamplesResponse(BaseModel):
    examples: list[ExampleQuestion]


class ErrorResponse(BaseModel):
    detail: str
    request_id: str | None = None
