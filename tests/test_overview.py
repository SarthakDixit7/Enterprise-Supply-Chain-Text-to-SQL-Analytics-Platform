from __future__ import annotations

from logisql.db.executor import QueryExecutor
from logisql.db.overview import OverviewService, build_overview_sql


def test_build_overview_sql_respects_allowlist() -> None:
    assert build_overview_sql(frozenset()) is None

    orders_only = build_overview_sql(frozenset({"orders"}))
    assert orders_only is not None
    assert "FROM orders" in orders_only
    assert "order_items" not in orders_only
    assert "sellers" not in orders_only

    full = build_overview_sql(
        frozenset({"orders", "order_items", "sellers", "products"})
    )
    assert full is not None
    for fragment in ("order_items", "sellers", "products", "late_orders"):
        assert fragment in full


async def test_overview_service_handles_strict_allowlist(executor: QueryExecutor) -> None:
    service = OverviewService(executor=executor, allowed_tables=frozenset({"orders"}))
    snapshot = await service.get()

    assert snapshot.orders == 120
    assert snapshot.delivered_orders > 0
    assert snapshot.sellers == 0
    assert snapshot.products == 0
    assert snapshot.item_count == 0
    assert snapshot.gross_item_value == 0.0
    assert snapshot.first_order_at


async def test_overview_service_caches_and_refreshes(executor: QueryExecutor) -> None:
    service = OverviewService(executor=executor, allowed_tables=frozenset({"orders"}))

    first = await service.get()
    second = await service.get()
    assert second == first

    refreshed = await service.get(force=True)
    assert refreshed == first
