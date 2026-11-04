from __future__ import annotations

from logisql.db.schema import SchemaService


async def test_introspects_sqlite_schema(schema_service: SchemaService) -> None:
    schema = await schema_service.get()
    assert schema.dialect == "sqlite"
    assert set(schema.table_names) == {
        "orders",
        "order_items",
        "products",
        "sellers",
        "order_payments",
    }

    orders = schema.table("orders")
    assert orders is not None
    assert "order_id" in orders.primary_key
    assert any(column.name == "order_purchase_timestamp" for column in orders.columns)

    items = schema.table("order_items")
    assert items is not None
    order_id = next(column for column in items.columns if column.name == "order_id")
    assert order_id.references == "orders.order_id"


async def test_prompt_context_contains_relationships(schema_service: SchemaService) -> None:
    schema = await schema_service.get()
    context = schema.prompt_context()
    assert "TABLE orders" in context
    assert "RELATIONSHIPS" in context
    assert "order_items.order_id -> orders.order_id" in context
    assert "DIALECT: sqlite" in context


async def test_schema_cache_is_reused(schema_service: SchemaService) -> None:
    first = await schema_service.get()
    second = await schema_service.get()
    assert first is second
    forced = await schema_service.get(force=True)
    assert forced is not first
