from __future__ import annotations

import pytest

from logisql.export import sanitize_csv_cell


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "\t=cmd", "\r=cmd"],
)
def test_formula_like_strings_are_neutralized(value: str) -> None:
    assert sanitize_csv_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["delivered", "São Paulo", "2018-01-01", ""])
def test_plain_strings_are_unchanged(value: str) -> None:
    assert sanitize_csv_cell(value) == value


def test_typed_values_are_unchanged() -> None:
    assert sanitize_csv_cell(None) is None
    assert sanitize_csv_cell(-12.5) == -12.5
    assert sanitize_csv_cell(42) == 42
    assert sanitize_csv_cell(True) is True
