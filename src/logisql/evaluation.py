from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FORBIDDEN_KEYWORDS = ("alter", "create", "delete", "drop", "insert", "truncate", "update")


@dataclass(frozen=True)
class GoldenCase:
    """A question plus coarse expectations for the generated SQL."""

    id: str
    question: str
    required_tables: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    forbidden_keywords: tuple[str, ...] = DEFAULT_FORBIDDEN_KEYWORDS


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...] = ()


def _contains_word(sql: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word.lower())}\b", sql))


def _normalize_sql(sql: str | None) -> str:
    return " ".join((sql or "").lower().split())


def evaluate_sql(case: GoldenCase, sql: str | None) -> CaseResult:
    """Check a generated statement against a golden case's expectations."""

    normalized = _normalize_sql(sql)
    if not normalized:
        return CaseResult(case.id, False, ("no SQL was generated",))

    failures: list[str] = []
    for table in case.required_tables:
        if not _contains_word(normalized, table):
            failures.append(f"missing table: {table}")
    for column in case.required_columns:
        if not _contains_word(normalized, column):
            failures.append(f"missing column: {column}")
    for keyword in case.forbidden_keywords:
        if _contains_word(normalized, keyword):
            failures.append(f"forbidden keyword: {keyword}")

    return CaseResult(case.id, not failures, tuple(failures))


def load_cases(path: str | Path) -> list[GoldenCase]:
    """Load and validate a JSON list of golden cases."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Golden case file must contain a non-empty JSON list.")

    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Golden case at index {index} must be an object.")
        try:
            case_id = str(item["id"]).strip()
            question = str(item["question"]).strip()
        except KeyError as exc:
            raise ValueError(f"Golden case at index {index} is missing {exc}.") from exc
        if not case_id or not question:
            raise ValueError(f"Golden case at index {index} has an empty id or question.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate golden case id: {case_id}")
        seen_ids.add(case_id)

        cases.append(
            GoldenCase(
                id=case_id,
                question=question,
                required_tables=tuple(item.get("required_tables", ())),
                required_columns=tuple(item.get("required_columns", ())),
                forbidden_keywords=tuple(
                    item.get("forbidden_keywords", DEFAULT_FORBIDDEN_KEYWORDS)
                ),
            )
        )
    return cases


__all__ = [
    "CaseResult",
    "DEFAULT_FORBIDDEN_KEYWORDS",
    "GoldenCase",
    "evaluate_sql",
    "load_cases",
]
