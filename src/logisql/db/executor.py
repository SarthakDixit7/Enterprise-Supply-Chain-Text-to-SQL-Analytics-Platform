from __future__ import annotations

import asyncio
import base64
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from logisql.config import Settings


class QueryExecutionError(RuntimeError):
    """A safe, user-facing SQL execution failure."""


@dataclass(frozen=True)
class QueryExecutionResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _dedupe_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for column in columns:
        base = column or "column"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


@dataclass
class QueryExecutor:
    engine: AsyncEngine
    settings: Settings
    _dialect: str = field(init=False)

    def __post_init__(self) -> None:
        self._dialect = self.engine.dialect.name

    @property
    def dialect(self) -> str:
        return "postgresql" if self._dialect == "postgresql" else "sqlite"

    async def execute(
        self,
        sql: str,
        *,
        row_limit: int | None = None,
    ) -> QueryExecutionResult:
        limit = min(row_limit or self.settings.default_row_limit, self.settings.max_row_limit)
        statement = sql.strip().rstrip(";")
        wrapped = (
            "SELECT * FROM (\n"
            f"{statement}\n"
            ") AS _logisql_result\n"
            f"LIMIT {int(limit) + 1}"
        )
        started = time.perf_counter()

        try:
            if self._dialect == "postgresql":
                raw_rows, raw_columns = await self._execute_postgres(wrapped)
            else:
                raw_rows, raw_columns = await asyncio.wait_for(
                    self._execute_sqlite(wrapped),
                    timeout=(self.settings.query_timeout_ms / 1000) + 1,
                )
        except TimeoutError as exc:
            raise QueryExecutionError(
                f"Query exceeded the {self.settings.query_timeout_ms} ms timeout."
            ) from exc
        except SQLAlchemyError as exc:
            raise QueryExecutionError(self._safe_db_error(exc)) from exc
        except Exception as exc:
            if isinstance(exc, QueryExecutionError):
                raise
            raise QueryExecutionError(self._safe_db_error(exc)) from exc

        columns = _dedupe_columns(raw_columns)
        rows = [
            {columns[index]: _json_value(value) for index, value in enumerate(row)}
            for row in raw_rows[:limit]
        ]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return QueryExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=len(raw_rows) > limit,
            elapsed_ms=elapsed_ms,
        )

    async def _execute_postgres(self, sql: str) -> tuple[list[Any], list[str]]:
        async with self.engine.connect() as connection, connection.begin():
            await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            await connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = {int(self.settings.query_timeout_ms)}"
            )
            result = await connection.execute(text(sql))
            rows = result.fetchall()
            columns = [str(key) for key in result.keys()]  # noqa: SIM118 - SQLAlchemy Result
            return rows, columns

    async def _execute_sqlite(self, sql: str) -> tuple[list[Any], list[str]]:
        async with self.engine.connect() as connection:
            await connection.exec_driver_sql("PRAGMA query_only = ON")
            try:
                result = await connection.execute(text(sql))
                rows = result.fetchall()
                columns = [
                    str(key) for key in result.keys()  # noqa: SIM118 - SQLAlchemy Result
                ]
                return rows, columns
            finally:
                with suppress(Exception):
                    await connection.exec_driver_sql("PRAGMA query_only = OFF")

    @staticmethod
    def _safe_db_error(exc: Exception) -> str:
        message = str(getattr(exc, "orig", exc)).strip()
        message = " ".join(message.split())
        if len(message) > 1500:
            message = message[:1497] + "..."
        return message or exc.__class__.__name__


__all__ = ["QueryExecutionError", "QueryExecutionResult", "QueryExecutor"]
