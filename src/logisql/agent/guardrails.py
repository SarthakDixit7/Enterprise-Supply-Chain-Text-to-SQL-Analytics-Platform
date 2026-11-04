from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class GuardrailError(ValueError):
    """Raised when generated SQL violates the read-only safety policy."""


_BLOCKED_NODE_NAMES = {
    "Alter",
    "Analyze",
    "Attach",
    "Call",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Execute",
    "Export",
    "Grant",
    "Insert",
    "Into",
    "LoadData",
    "Lock",
    "Merge",
    "Pragma",
    "Revoke",
    "Rollback",
    "Set",
    "Transaction",
    "TruncateTable",
    "Update",
    "Use",
    "Vacuum",
}

_BLOCKED_FUNCTIONS = {
    "dblink",
    "dblink_exec",
    "lo_export",
    "lo_import",
    "pg_cancel_backend",
    "pg_create_restore_point",
    "pg_drop_replication_slot",
    "pg_ls_dir",
    "pg_promote",
    "pg_read_binary_file",
    "pg_read_file",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_start_backup",
    "pg_stat_file",
    "pg_stop_backup",
    "pg_switch_wal",
    "pg_terminate_backend",
    "set_config",
}

_BLOCKED_SCHEMAS = {
    "auth",
    "extensions",
    "information_schema",
    "pg_catalog",
    "pg_toast",
    "storage",
    "vault",
}

_READ_QUERY_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

_COMMENT_RE = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)


@dataclass(frozen=True)
class SQLGuardrail:
    """Parses SQL into an AST and enforces a strict read-only allowlist."""

    allowed_tables: frozenset[str]
    dialect: str = "postgres"
    allowed_schema: str = "public"
    max_sql_length: int = 20_000

    def validate(self, sql: str) -> str:
        cleaned = (sql or "").strip()
        if not cleaned:
            raise GuardrailError("The model returned an empty SQL statement.")
        if len(cleaned) > self.max_sql_length:
            raise GuardrailError("Generated SQL is too long.")
        if not self.allowed_tables:
            raise GuardrailError("No tables are allowlisted for this deployment.")

        try:
            statements = parse(cleaned, read=self.dialect)
        except ParseError as exc:
            raise GuardrailError(f"SQL syntax error: {exc}") from exc

        statements = [statement for statement in statements if statement is not None]
        if len(statements) != 1:
            raise GuardrailError("Exactly one SQL statement is allowed.")

        expression = statements[0]
        if not isinstance(expression, _READ_QUERY_TYPES):
            raise GuardrailError(
                "Only read-only SELECT queries (including CTEs and UNIONs) are allowed."
            )

        self._reject_mutating_nodes(expression)
        self._reject_unsafe_tables(expression)
        self._reject_unsafe_functions(expression)
        self._reject_prompt_shaped_comments(cleaned)

        return expression.sql(dialect=self.dialect)

    @staticmethod
    def _reject_mutating_nodes(expression: exp.Expression) -> None:
        for node in expression.walk():
            name = type(node).__name__
            if name in _BLOCKED_NODE_NAMES:
                raise GuardrailError(
                    f"Mutating or unsafe SQL construct is blocked: {name.upper()}."
                )

    def _reject_unsafe_tables(self, expression: exp.Expression) -> None:
        cte_names = {
            cte.alias_or_name.lower()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }
        for table in expression.find_all(exp.Table):
            name = (table.name or "").lower()
            schema = (table.db or "").lower()
            if not name:
                continue
            if schema in _BLOCKED_SCHEMAS or schema.startswith("pg_"):
                raise GuardrailError(f"System schema access is blocked: {schema}.")
            if schema and schema != self.allowed_schema.lower():
                raise GuardrailError(f"Schema '{schema}' is not allowlisted.")
            if name in cte_names:
                continue
            if name not in self.allowed_tables:
                raise GuardrailError(
                    f"Table '{name}' is not allowlisted. Allowed tables: "
                    f"{', '.join(sorted(self.allowed_tables))}."
                )

    @staticmethod
    def _reject_unsafe_functions(expression: exp.Expression) -> None:
        for node in expression.find_all(exp.Func):
            if isinstance(node, exp.Anonymous):
                function_name = str(node.this).lower()
            else:
                function_name = (node.sql_name() or "").lower()
            if function_name in _BLOCKED_FUNCTIONS:
                raise GuardrailError(
                    f"Database function '{function_name}' is blocked by the safety policy."
                )

    @staticmethod
    def _reject_prompt_shaped_comments(sql: str) -> None:
        stripped = _COMMENT_RE.sub(" ", sql).lower()
        if "ignore previous" in stripped or "system prompt" in stripped:
            raise GuardrailError("Suspicious instruction text detected in generated SQL.")

    def references_only_allowed_tables(self, sql: str) -> bool:
        try:
            self.validate(sql)
            return True
        except GuardrailError:
            return False


__all__ = ["GuardrailError", "SQLGuardrail"]
