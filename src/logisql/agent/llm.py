from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from sqlglot import parse
from sqlglot.errors import ParseError

from logisql.agent.prompts import (
    SQL_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    sql_generation_prompt,
    sql_repair_prompt,
    synthesis_prompt,
)
from logisql.config import Settings

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_SQL_START_RE = re.compile(r"(?is)\b(select|with)\b")


class LLMConfigurationError(RuntimeError):
    """Raised when the Groq API key is missing."""


class LLMResponseError(RuntimeError):
    """Raised when an LLM response cannot be parsed."""


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "scatter", "pie", "area", "none"] = "none"
    x: str | None = None
    y: str | None = None
    color: str | None = None
    title: str | None = None


class SynthesisOutput(BaseModel):
    headline: str = Field(default="Query complete")
    summary: str = ""
    key_takeaways: list[str] = Field(default_factory=list)
    chart: ChartSpec | None = None


class AnalyticsLLM(Protocol):
    async def generate_sql(
        self, *, question: str, schema_context: str, dialect: str, row_limit: int
    ) -> str: ...

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
    ) -> str: ...

    async def synthesize(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        row_count: int,
        truncated: bool,
    ) -> SynthesisOutput: ...


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def clean_sql_response(text: str, *, dialect: str = "postgres") -> str:
    """Extract the most likely SQL statement from a chatty model response."""

    candidate = (text or "").strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    candidate = re.sub(r"^(?:sql|query)\s*:\s*", "", candidate, flags=re.IGNORECASE).strip()
    candidate = candidate.strip("`").strip()
    if not candidate:
        return ""

    for attempt in (candidate, _trim_to_statement(candidate)):
        if not attempt:
            continue
        try:
            parse(attempt, read=dialect)
            return attempt
        except ParseError:
            continue
    return _trim_to_statement(candidate) or candidate


def _trim_to_statement(text: str) -> str:
    match = _SQL_START_RE.search(text)
    if not match:
        return text.strip()
    candidate = text[match.start() :].strip()
    if ";" in candidate:
        # A single trailing semicolon is stripped later; extra statements are
        # rejected by the guardrail.
        candidate = candidate.split(";", 1)[0].strip() + ";"
    return candidate


def parse_json_response(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    if start == -1:
        raise LLMResponseError("The model did not return a JSON object.")
    try:
        parsed, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"Could not parse synthesis JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMResponseError("Synthesis response was not a JSON object.")
    return parsed


def _normalize_synthesis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for field in ("headline", "summary"):
        if normalized.get(field) is None:
            normalized[field] = ""
        elif not isinstance(normalized[field], str):
            normalized[field] = str(normalized[field])

    chart = normalized.get("chart")
    if isinstance(chart, dict):
        chart = dict(chart)
        chart_type = str(chart.get("type") or "none").lower()
        chart["type"] = chart_type if chart_type in {
            "bar",
            "line",
            "scatter",
            "pie",
            "area",
            "none",
        } else "none"
        if chart["type"] == "none":
            chart.update({"x": None, "y": None, "color": None})
        normalized["chart"] = chart
    elif chart in (None, "", "null"):
        normalized["chart"] = None

    takeaways = normalized.get("key_takeaways")
    if isinstance(takeaways, str):
        normalized["key_takeaways"] = [takeaways]
    elif isinstance(takeaways, list):
        normalized["key_takeaways"] = [
            str(item) for item in takeaways if isinstance(item, (str, int, float))
        ]
    else:
        normalized["key_takeaways"] = []
    return normalized


class GroqAnalyticsLLM:
    """Groq-backed implementation of the agent's LLM operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: ChatGroq | None = None

    def _get_client(self) -> ChatGroq:
        if not self.settings.llm_configured:
            raise LLMConfigurationError(
                "GROQ_API_KEY is not configured. Add it to .env to enable the agent."
            )
        if self._client is None:
            self._client = ChatGroq(
                model=self.settings.groq_model,
                api_key=self.settings.groq_api_key,
                temperature=self.settings.llm_temperature,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=2,
            )
        return self._client

    async def _invoke(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_client()
        response = await client.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        return _content_to_text(response.content)

    async def generate_sql(
        self,
        *,
        question: str,
        schema_context: str,
        dialect: str,
        row_limit: int,
    ) -> str:
        text = await self._invoke(
            SQL_SYSTEM_PROMPT,
            sql_generation_prompt(
                question=question,
                schema_context=schema_context,
                dialect=dialect,
                row_limit=row_limit,
            ),
        )
        return clean_sql_response(text, dialect=dialect)

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
        text = await self._invoke(
            SQL_SYSTEM_PROMPT,
            sql_repair_prompt(
                question=question,
                schema_context=schema_context,
                dialect=dialect,
                previous_sql=previous_sql,
                error=error,
                attempt=attempt,
                row_limit=row_limit,
            ),
        )
        return clean_sql_response(text, dialect=dialect)

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
        text = await self._invoke(
            SYNTHESIS_SYSTEM_PROMPT,
            synthesis_prompt(
                question=question,
                sql=sql,
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
            ),
        )
        payload = _normalize_synthesis_payload(parse_json_response(text))
        return SynthesisOutput.model_validate(payload)


__all__ = [
    "AnalyticsLLM",
    "ChartSpec",
    "GroqAnalyticsLLM",
    "LLMConfigurationError",
    "LLMResponseError",
    "SynthesisOutput",
    "clean_sql_response",
    "parse_json_response",
]
