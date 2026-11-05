from __future__ import annotations

import json
from pathlib import Path

import pytest

from logisql.evaluation import GoldenCase, evaluate_sql, load_cases

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_passes_when_required_fragments_are_present() -> None:
    case = GoldenCase(
        id="orders_by_status",
        question="How many orders are there by status?",
        required_tables=("orders",),
        required_columns=("order_status",),
    )
    result = evaluate_sql(
        case,
        "SELECT order_status, COUNT(*) AS order_count "
        "FROM orders GROUP BY order_status",
    )
    assert result.passed is True
    assert result.failures == ()


def test_reports_missing_table_and_column() -> None:
    case = GoldenCase(
        id="revenue",
        question="Revenue by category?",
        required_tables=("order_items", "products"),
        required_columns=("product_category_name", "price"),
    )
    result = evaluate_sql(case, "SELECT COUNT(*) FROM orders")
    assert result.passed is False
    assert "missing table: order_items" in result.failures
    assert "missing table: products" in result.failures
    assert "missing column: price" in result.failures


def test_reports_forbidden_keywords() -> None:
    case = GoldenCase(id="safe", question="Anything?", required_tables=("orders",))
    result = evaluate_sql(case, "DELETE FROM orders")
    assert result.passed is False
    assert "forbidden keyword: delete" in result.failures


def test_empty_sql_fails() -> None:
    case = GoldenCase(id="empty", question="Anything?")
    result = evaluate_sql(case, None)
    assert result.passed is False
    assert result.failures == ("no SQL was generated",)


def test_load_cases_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "question": "How many orders?",
                    "required_tables": ["orders"],
                    "required_columns": ["order_id"],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0].id == "one"
    assert cases[0].required_tables == ("orders",)
    assert "insert" in cases[0].forbidden_keywords


def test_load_cases_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {"id": "one", "question": "First?"},
                {"id": "one", "question": "Second?"},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)


def test_repository_golden_cases_load() -> None:
    cases = load_cases(REPO_ROOT / "evals" / "golden_questions.json")
    assert len(cases) >= 5
    assert all(case.required_tables for case in cases)
    assert len({case.id for case in cases}) == len(cases)
