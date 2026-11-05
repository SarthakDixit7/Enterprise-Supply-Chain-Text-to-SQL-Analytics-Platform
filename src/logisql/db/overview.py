from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from pydantic import BaseModel

from logisql.db.executor import QueryExecutor

# Hardcoded, read-only aggregates used for the UI's dataset snapshot. The
# query is assembled from allowlisted tables so strict deployments still work.
_ORDERS_AGGREGATES = [
    "(SELECT COUNT(*) FROM orders) AS orders",
    "(SELECT COUNT(*) FROM orders WHERE order_status = 'delivered') AS delivered_orders",
    """(SELECT COUNT(*) FROM orders
      WHERE order_status = 'delivered'
        AND order_delivered_customer_date IS NOT NULL
        AND order_estimated_delivery_date IS NOT NULL
        AND order_delivered_customer_date > order_estimated_delivery_date
    ) AS late_orders""",
    "(SELECT MIN(order_purchase_timestamp) FROM orders) AS first_order_at",
    "(SELECT MAX(order_purchase_timestamp) FROM orders) AS last_order_at",
]

_ORDER_ITEMS_AGGREGATES = [
    "(SELECT COUNT(*) FROM order_items) AS item_count",
    "(SELECT COALESCE(SUM(price + freight_value), 0) FROM order_items) AS gross_item_value",
]


def build_overview_sql(allowed_tables: frozenset[str]) -> str | None:
    """Build the snapshot query from only the tables this deployment allows."""

    selects: list[str] = []
    if "orders" in allowed_tables:
        selects.extend(_ORDERS_AGGREGATES)
    if "order_items" in allowed_tables:
        selects.extend(_ORDER_ITEMS_AGGREGATES)
    if "sellers" in allowed_tables:
        selects.append("(SELECT COUNT(*) FROM sellers) AS sellers")
    if "products" in allowed_tables:
        selects.append("(SELECT COUNT(*) FROM products) AS products")

    if not selects:
        return None
    return "SELECT\n    " + ",\n    ".join(selects)


class DatasetOverview(BaseModel):
    """Aggregate dataset health metrics shown in the UI and API."""

    orders: int = 0
    delivered_orders: int = 0
    late_orders: int = 0
    on_time_rate: float | None = None
    item_count: int = 0
    sellers: int = 0
    products: int = 0
    gross_item_value: float = 0.0
    first_order_at: str | None = None
    last_order_at: str | None = None


@dataclass
class OverviewService:
    """Caches a cheap dataset snapshot so UI polling does not hammer the DB."""

    executor: QueryExecutor
    allowed_tables: frozenset[str]
    ttl_seconds: float = 60.0
    _cache: DatasetOverview | None = field(default=None, init=False, repr=False)
    _cached_at: float = field(default=0.0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def get(self, *, force: bool = False) -> DatasetOverview:
        fresh = self._cache is not None and (time.monotonic() - self._cached_at) < self.ttl_seconds
        if fresh and not force:
            assert self._cache is not None
            return self._cache

        async with self._lock:
            fresh = self._cache is not None and (
                time.monotonic() - self._cached_at
            ) < self.ttl_seconds
            if fresh and not force:
                assert self._cache is not None
                return self._cache

            overview = await self._compute()
            self._cache = overview
            self._cached_at = time.monotonic()
            return overview

    async def _compute(self) -> DatasetOverview:
        sql = build_overview_sql(self.allowed_tables)
        if sql is None:
            return DatasetOverview()

        result = await self.executor.execute(sql, row_limit=1)
        row = result.rows[0] if result.rows else {}

        orders = int(row.get("orders") or 0)
        delivered = int(row.get("delivered_orders") or 0)
        late = int(row.get("late_orders") or 0)
        on_time = round((delivered - late) / delivered, 4) if delivered else None

        return DatasetOverview(
            orders=orders,
            delivered_orders=delivered,
            late_orders=late,
            on_time_rate=on_time,
            item_count=int(row.get("item_count") or 0),
            sellers=int(row.get("sellers") or 0),
            products=int(row.get("products") or 0),
            gross_item_value=round(float(row.get("gross_item_value") or 0.0), 2),
            first_order_at=row.get("first_order_at"),
            last_order_at=row.get("last_order_at"),
        )


__all__ = ["DatasetOverview", "OverviewService", "build_overview_sql"]
