from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine

from logisql.config import Settings
from logisql.db.models import metadata, order_items, order_payments, orders, products, sellers

CATEGORIES = [
    "health_beauty",
    "sports_leisure",
    "furniture_decor",
    "housewares",
    "auto",
    "toys",
    "cool_stuff",
    "computers_accessories",
    "bed_bath_table",
    "garden_tools",
    "watch_gifts",
    "telephony",
    "perfumery",
    "office_furniture",
    "building_tools",
    "electronics",
    "fashion_menswear",
    "fashion_womenswear",
    "baby",
    "pet_shop",
]

CITIES = [
    ("sao paulo", "SP"),
    ("rio de janeiro", "RJ"),
    ("belo horizonte", "MG"),
    ("curitiba", "PR"),
    ("porto alegre", "RS"),
    ("salvador", "BA"),
    ("recife", "PE"),
    ("fortaleza", "CE"),
    ("brasilia", "DF"),
    ("campinas", "SP"),
    ("goiania", "GO"),
    ("manaus", "AM"),
]

PAYMENT_TYPES = ["credit_card", "boleto", "voucher", "debit_card"]
STATUS_WEIGHTS = [
    ("delivered", 88),
    ("shipped", 4),
    ("invoiced", 3),
    ("processing", 2),
    ("unavailable", 1),
    ("canceled", 1),
    ("created", 1),
]


def _weighted_choice(rng: random.Random, choices: list[tuple[str, int]]) -> str:
    population = [value for value, _ in choices]
    weights = [weight for _, weight in choices]
    return rng.choices(population, weights=weights, k=1)[0]


def _shared_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _create_demo_data(order_count: int, seed: int = 42) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    base_date = datetime(2017, 1, 1, tzinfo=UTC)
    span_days = 610

    seller_rows: list[dict] = []
    seller_ids: list[str] = []
    for index in range(40):
        seller_id = f"seller_{index:04d}"
        city, state = rng.choice(CITIES)
        seller_ids.append(seller_id)
        seller_rows.append(
            {
                "seller_id": seller_id,
                "seller_zip_code_prefix": f"{rng.randint(1000, 99999):05d}",
                "seller_city": city,
                "seller_state": state,
            }
        )

    product_rows: list[dict] = []
    product_ids: list[str] = []
    for index in range(160):
        product_id = f"product_{index:04d}"
        category = rng.choice(CATEGORIES)
        weight = rng.randint(150, 15_000)
        product_ids.append(product_id)
        product_rows.append(
            {
                "product_id": product_id,
                "product_category_name": category,
                "product_name_length": rng.randint(20, 65),
                "product_description_length": rng.randint(200, 2500),
                "product_photos_qty": rng.randint(1, 6),
                "product_weight_g": weight,
                "product_length_cm": rng.randint(10, 80),
                "product_height_cm": rng.randint(5, 50),
                "product_width_cm": rng.randint(8, 60),
            }
        )

    order_rows: list[dict] = []
    item_rows: list[dict] = []
    payment_rows: list[dict] = []

    for index in range(order_count):
        order_id = f"order_{index:06d}"
        purchase = base_date + timedelta(
            days=rng.uniform(0, span_days),
            hours=rng.uniform(0, 23),
            minutes=rng.uniform(0, 59),
        )
        approved = purchase + timedelta(minutes=rng.randint(5, 1800))
        status = _weighted_choice(rng, STATUS_WEIGHTS)

        carrier_date: datetime | None = None
        customer_date: datetime | None = None
        if status in {"delivered", "shipped"}:
            carrier_date = purchase + timedelta(days=rng.randint(1, 5))
        if status == "delivered":
            customer_date = carrier_date + timedelta(days=rng.randint(2, 18))
        estimated = purchase + timedelta(days=rng.randint(8, 30))

        order_rows.append(
            {
                "order_id": order_id,
                "customer_id": f"customer_{rng.randint(1, order_count):06d}",
                "order_status": status,
                "order_purchase_timestamp": purchase,
                "order_approved_at": approved,
                "order_delivered_carrier_date": carrier_date,
                "order_delivered_customer_date": customer_date,
                "order_estimated_delivery_date": estimated,
            }
        )

        total = Decimal("0.00")
        item_count = rng.choices([1, 2, 3, 4], weights=[55, 25, 14, 6], k=1)[0]
        for item_number in range(1, item_count + 1):
            product_index = rng.randrange(len(product_ids))
            unit_price = Decimal(rng.randint(1800, 45_000)) / Decimal(100)
            freight = Decimal(rng.randint(500, 4_500)) / Decimal(100)
            total += unit_price + freight
            item_rows.append(
                {
                    "order_id": order_id,
                    "order_item_id": item_number,
                    "product_id": product_ids[product_index],
                    "seller_id": rng.choice(seller_ids),
                    "shipping_limit_date": purchase + timedelta(days=rng.randint(2, 9)),
                    "price": unit_price,
                    "freight_value": freight,
                }
            )

        if rng.random() < 0.12:
            split = (total * Decimal("0.55")).quantize(Decimal("0.01"))
            payment_rows.append(
                {
                    "order_id": order_id,
                    "payment_sequential": 1,
                    "payment_type": "voucher",
                    "payment_installments": 1,
                    "payment_value": split,
                }
            )
            payment_rows.append(
                {
                    "order_id": order_id,
                    "payment_sequential": 2,
                    "payment_type": rng.choice(PAYMENT_TYPES),
                    "payment_installments": rng.randint(1, 10),
                    "payment_value": total - split,
                }
            )
        else:
            payment_rows.append(
                {
                    "order_id": order_id,
                    "payment_sequential": 1,
                    "payment_type": rng.choice(PAYMENT_TYPES),
                    "payment_installments": rng.randint(1, 10),
                    "payment_value": total,
                }
            )

    return {
        "sellers": seller_rows,
        "products": product_rows,
        "orders": order_rows,
        "order_items": item_rows,
        "order_payments": payment_rows,
    }


def _table_counts(connection: Connection) -> dict[str, int]:
    return {
        table.name: int(
            connection.execute(select(func.count()).select_from(table)).scalar_one()
        )
        for table in metadata.sorted_tables
    }


def seed_demo_database(
    database_path: Path,
    *,
    order_count: int = 1200,
    force: bool = False,
    chunk_size: int = 2000,
) -> dict[str, int]:
    """Create a local SQLite Olist-like database if it is empty."""

    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine: Engine = create_engine(_shared_sqlite_url(database_path), future=True)

    try:
        with engine.begin() as connection:
            if force:
                metadata.drop_all(connection)
            metadata.create_all(connection)

            existing = connection.execute(select(func.count()).select_from(orders)).scalar_one()
            if existing and not force:
                return _table_counts(connection)

        data = _create_demo_data(order_count)
        with engine.begin() as connection:
            for table, rows in (
                (sellers, data["sellers"]),
                (products, data["products"]),
                (orders, data["orders"]),
                (order_items, data["order_items"]),
                (order_payments, data["order_payments"]),
            ):
                statement = sqlite_insert(table).on_conflict_do_nothing()
                for start in range(0, len(rows), chunk_size):
                    connection.execute(statement, rows[start : start + chunk_size])

        with engine.connect() as connection:
            return _table_counts(connection)
    finally:
        engine.dispose()


def ensure_demo_database(settings: Settings) -> dict[str, int] | None:
    """Ensure the default SQLite demo DB exists. No-op for external databases."""

    if not settings.is_sqlite or not settings.allow_demo_seed:
        return None
    path = settings.sqlite_path
    if path is None:
        return None
    return seed_demo_database(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a local synthetic Olist database.")
    parser.add_argument(
        "--database-url",
        default="sqlite+aiosqlite:///./data/logisql_demo.db",
        help="SQLite database URL only (Postgres uses scripts/load_olist.py).",
    )
    parser.add_argument("--orders", type=int, default=1200, help="Number of synthetic orders.")
    parser.add_argument("--force", action="store_true", help="Drop and recreate all tables.")
    args = parser.parse_args()

    if not args.database_url.startswith("sqlite"):
        raise SystemExit("Demo seeding is SQLite only. Use scripts/load_olist.py for Supabase.")

    raw_path = args.database_url.split(":///", 1)[-1].split("?", 1)[0]
    counts = seed_demo_database(
        Path(raw_path), order_count=args.orders, force=args.force
    )
    print("Demo database ready:")
    for table, count in counts.items():
        print(f"  {table:>16}: {count:,} rows")


if __name__ == "__main__":
    main()
