from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from logisql.config import Settings


class SchemaIntrospectionError(RuntimeError):
    """Raised when the database schema cannot be read safely."""


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False
    references: str | None = None


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)

    @property
    def relationships(self) -> list[str]:
        result: list[str] = []
        for column in self.columns:
            if column.references:
                result.append(f"{self.name}.{column.name} -> {column.references}")
        return result


class DatabaseSchema(BaseModel):
    dialect: str
    tables: list[TableInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    introspected_at: float = Field(default_factory=time.time)

    @property
    def table_names(self) -> list[str]:
        return [table.name for table in self.tables]

    def table(self, name: str) -> TableInfo | None:
        lowered = name.lower()
        return next((table for table in self.tables if table.name.lower() == lowered), None)

    def prompt_context(self) -> str:
        """Compact, deterministic schema description injected into LLM prompts."""

        blocks: list[str] = [f"DIALECT: {self.dialect}", f"TABLES: {len(self.tables)}"]
        relationships: list[str] = []

        for table in self.tables:
            lines = [f"TABLE {table.name} ("]
            for column in table.columns:
                flags = []
                if column.is_primary_key:
                    flags.append("PRIMARY KEY")
                if not column.nullable:
                    flags.append("NOT NULL")
                if column.references:
                    flags.append(f"REFERENCES {column.references}")
                suffix = f"  -- {', '.join(flags)}" if flags else ""
                lines.append(f"  {column.name} {column.data_type}{suffix}")
            lines.append(");")
            blocks.append("\n".join(lines))
            relationships.extend(table.relationships)

        if relationships:
            blocks.append("RELATIONSHIPS:\n" + "\n".join(f"  {rel}" for rel in relationships))
        if self.warnings:
            blocks.append("SCHEMA WARNINGS:\n" + "\n".join(f"  {w}" for w in self.warnings))
        return "\n\n".join(blocks)


@dataclass
class SchemaService:
    """Caches schema introspection and keeps it out of the hot request path."""

    engine: AsyncEngine
    settings: Settings
    _cache: DatabaseSchema | None = field(default=None, init=False, repr=False)
    _cached_at: float = field(default=0.0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def get(self, *, force: bool = False) -> DatabaseSchema:
        ttl = self.settings.schema_cache_ttl_seconds
        fresh = self._cache is not None and (time.monotonic() - self._cached_at) < ttl
        if fresh and not force:
            assert self._cache is not None
            return self._cache

        async with self._lock:
            fresh = self._cache is not None and (time.monotonic() - self._cached_at) < ttl
            if fresh and not force:
                assert self._cache is not None
                return self._cache
            schema = await self._introspect()
            self._cache = schema
            self._cached_at = time.monotonic()
            return schema

    def invalidate(self) -> None:
        self._cache = None
        self._cached_at = 0.0

    async def _introspect(self) -> DatabaseSchema:
        dialect = self.engine.dialect.name
        async with self.engine.connect() as connection:
            if dialect == "postgresql":
                return await _introspect_postgres(connection, self.settings)
            return await _introspect_with_inspector(connection, self.settings, dialect)


async def _introspect_postgres(connection: Any, settings: Settings) -> DatabaseSchema:
    schema_name = settings.database_schema
    allowed = sorted(settings.allowed_table_set)
    params = {"schema": schema_name, "tables": allowed}

    columns_stmt = text(
        """
        SELECT table_name, column_name, data_type, is_nullable,
               column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name IN :tables
        ORDER BY table_name, ordinal_position
        """
    ).bindparams(bindparam("tables", expanding=True))

    pk_stmt = text(
        """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = :schema
          AND tc.table_name IN :tables
        """
    ).bindparams(bindparam("tables", expanding=True))

    fk_stmt = text(
        """
        SELECT tc.table_name, kcu.column_name,
               ccu.table_name AS foreign_table_name,
               ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = :schema
          AND tc.table_name IN :tables
        """
    ).bindparams(bindparam("tables", expanding=True))

    column_rows = (await connection.execute(columns_stmt, params)).mappings().all()
    if not column_rows:
        raise SchemaIntrospectionError(
            f"No columns found in schema '{schema_name}' for tables: {', '.join(allowed)}. "
            "Check DATABASE_SCHEMA, ALLOWED_TABLES, and that the Olist schema is loaded."
        )

    pk_rows = (await connection.execute(pk_stmt, params)).mappings().all()
    fk_rows = (await connection.execute(fk_stmt, params)).mappings().all()

    primary_keys: dict[tuple[str, str], bool] = {
        (row["table_name"], row["column_name"]): True for row in pk_rows
    }
    references: dict[tuple[str, str], str] = {
        (row["table_name"], row["column_name"]): (
            f"{row['foreign_table_name']}.{row['foreign_column_name']}"
        )
        for row in fk_rows
    }

    tables: dict[str, TableInfo] = {}
    for row in column_rows:
        table_name = row["table_name"]
        table = tables.setdefault(table_name, TableInfo(name=table_name))
        is_pk = (table_name, row["column_name"]) in primary_keys
        if is_pk:
            table.primary_key.append(row["column_name"])
        table.columns.append(
            ColumnInfo(
                name=row["column_name"],
                data_type=str(row["data_type"]).lower(),
                nullable=(row["is_nullable"] == "YES"),
                default=row["column_default"],
                is_primary_key=is_pk,
                references=references.get((table_name, row["column_name"])),
            )
        )

    missing = sorted(set(allowed) - set(tables))
    warnings = [f"Configured table not found in database: {name}" for name in missing]
    if not tables:
        raise SchemaIntrospectionError("Schema introspection returned no allowed tables.")
    return DatabaseSchema(
        dialect="postgresql",
        tables=[tables[name] for name in sorted(tables)],
        warnings=warnings,
    )


async def _introspect_with_inspector(
    connection: Any, settings: Settings, dialect: str
) -> DatabaseSchema:
    def _run(sync_connection: Any) -> DatabaseSchema:
        inspector = inspect(sync_connection)
        existing = set(inspector.get_table_names())
        allowed = settings.allowed_table_set
        selected = sorted(existing & allowed) if allowed else sorted(existing)
        missing = sorted(allowed - existing) if allowed else []
        warnings = [f"Configured table not found in database: {name}" for name in missing]

        tables: list[TableInfo] = []
        for table_name in selected:
            pk_columns = inspector.get_pk_constraint(table_name).get(
                "constrained_columns", []
            ) or []
            fks = inspector.get_foreign_keys(table_name)
            fk_map = {
                fk["constrained_columns"][0]: (
                    f"{fk['referred_table']}.{fk['referred_columns'][0]}"
                )
                for fk in fks
                if fk.get("constrained_columns") and fk.get("referred_columns")
            }
            columns = [
                ColumnInfo(
                    name=column["name"],
                    data_type=str(column["type"]).lower(),
                    nullable=bool(column.get("nullable", True)),
                    default=str(column["default"]) if column.get("default") is not None else None,
                    is_primary_key=column["name"] in pk_columns,
                    references=fk_map.get(column["name"]),
                )
                for column in inspector.get_columns(table_name)
            ]
            tables.append(
                TableInfo(name=table_name, columns=columns, primary_key=list(pk_columns))
            )

        if not tables:
            raise SchemaIntrospectionError(
                "No allowed tables found. Set ALLOWED_TABLES or load the demo dataset."
            )
        return DatabaseSchema(dialect=dialect, tables=tables, warnings=warnings)

    return await connection.run_sync(_run)


__all__ = [
    "ColumnInfo",
    "DatabaseSchema",
    "SchemaIntrospectionError",
    "SchemaService",
    "TableInfo",
]
