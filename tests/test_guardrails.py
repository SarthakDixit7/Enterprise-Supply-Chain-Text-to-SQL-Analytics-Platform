from __future__ import annotations

import pytest

from logisql.agent.guardrails import GuardrailError, SQLGuardrail

ALLOWED = frozenset({"orders", "order_items", "products", "sellers", "order_payments"})


@pytest.fixture
def guard() -> SQLGuardrail:
    return SQLGuardrail(allowed_tables=ALLOWED, dialect="postgres", allowed_schema="public")


def test_accepts_join(guard: SQLGuardrail) -> None:
    sql = """
    SELECT p.product_category_name, SUM(oi.price) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN products p ON p.product_id = oi.product_id
    WHERE o.order_status = 'delivered'
    GROUP BY p.product_category_name
    ORDER BY revenue DESC
    LIMIT 10
    """
    normalized = guard.validate(sql)
    assert normalized.startswith("SELECT")
    assert "product_category_name" in normalized


def test_accepts_cte_and_union(guard: SQLGuardrail) -> None:
    cte = """
    WITH delivered AS (
        SELECT order_id FROM orders WHERE order_status = 'delivered'
    )
    SELECT COUNT(*) AS delivered_orders FROM delivered
    """
    union = "SELECT order_id FROM orders UNION SELECT order_id FROM order_items"
    assert guard.validate(cte)
    assert guard.validate(union)


def test_accepts_qualified_public_table(guard: SQLGuardrail) -> None:
    assert guard.validate("SELECT order_id FROM public.orders LIMIT 1")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "UPDATE orders SET order_status = 'canceled'",
        "INSERT INTO sellers (seller_id) VALUES ('x')",
        "TRUNCATE TABLE orders",
        "CREATE TABLE x AS SELECT * FROM orders",
        "SELECT * FROM orders; DROP TABLE orders",
        "WITH x AS (DELETE FROM orders RETURNING order_id) SELECT * FROM x",
        "SELECT * INTO backup_orders FROM orders",
        "SELECT pg_sleep(10)",
        "SELECT * FROM information_schema.columns",
        "SELECT * FROM auth.users",
        "SELECT * FROM private.orders",
        "SELECT * FROM customers",
        "SET statement_timeout = 0",
        "CALL some_procedure()",
    ],
)
def test_rejects_unsafe_sql(guard: SQLGuardrail, sql: str) -> None:
    with pytest.raises(GuardrailError):
        guard.validate(sql)


def test_rejects_empty(guard: SQLGuardrail) -> None:
    with pytest.raises(GuardrailError):
        guard.validate("   ")


def test_rejects_syntax_error(guard: SQLGuardrail) -> None:
    with pytest.raises(GuardrailError, match="syntax"):
        guard.validate("SELECT FROM WHERE")


def test_rejects_too_long(guard: SQLGuardrail) -> None:
    with pytest.raises(GuardrailError, match="too long"):
        guard.validate("SELECT " + "x" * 25_000)


def test_references_only_allowed_tables(guard: SQLGuardrail) -> None:
    assert guard.references_only_allowed_tables("SELECT order_id FROM orders")
    assert not guard.references_only_allowed_tables("SELECT * FROM customers")
