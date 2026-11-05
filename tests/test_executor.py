from __future__ import annotations

import pytest

from logisql.db.executor import QueryExecutionError, QueryExecutor


async def test_executor_returns_json_safe_rows(executor: QueryExecutor) -> None:
    result = await executor.execute(
        "SELECT order_status, COUNT(*) AS order_count, "
        "AVG(price) AS avg_price FROM orders "
        "JOIN order_items ON orders.order_id = order_items.order_id "
        "GROUP BY order_status ORDER BY order_count DESC",
        row_limit=100,
    )
    assert result.columns == ["order_status", "order_count", "avg_price"]
    assert result.row_count > 0
    assert isinstance(result.rows[0]["order_count"], int)
    assert isinstance(result.rows[0]["avg_price"], float)


async def test_executor_caps_rows_and_flags_truncation(executor: QueryExecutor) -> None:
    result = await executor.execute("SELECT order_id FROM orders ORDER BY order_id", row_limit=5)
    assert result.row_count == 5
    assert result.truncated is True


async def test_executor_is_read_only(executor: QueryExecutor) -> None:
    with pytest.raises(QueryExecutionError):
        await executor.execute("DELETE FROM orders")


async def test_executor_sanitizes_non_finite_floats(executor: QueryExecutor) -> None:
    result = await executor.execute(
        "SELECT 1e400 AS too_big, -1e400 AS too_small, 0.0/0.0 AS nan_value",
        row_limit=10,
    )
    assert result.rows[0]["too_big"] is None
    assert result.rows[0]["too_small"] is None
    assert result.rows[0]["nan_value"] is None
