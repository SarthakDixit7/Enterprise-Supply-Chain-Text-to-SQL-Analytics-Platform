from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, make_url

from logisql.db.engine import async_database_url
from logisql.db.models import metadata, order_items, order_payments, orders, products, sellers

FILE_MAP = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
}

COLUMN_ALIASES = {
    "product_name_lenght": "product_name_length",
    "product_description_lenght": "product_description_length",
}

DATETIME_COLUMNS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
}

INTEGER_COLUMNS = {
    "order_items": ["order_item_id"],
    "products": [
        "product_name_length",
        "product_description_length",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "order_payments": ["payment_sequential", "payment_installments"],
}

NUMERIC_COLUMNS = {
    "order_items": ["price", "freight_value"],
    "order_payments": ["payment_value"],
}


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=True)
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, keep_default_na=True, encoding="latin-1")


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (datetime, date)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _prepare_frame(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns={k: v for k, v in COLUMN_ALIASES.items() if k in frame.columns})
    for column in DATETIME_COLUMNS.get(name, []):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in INTEGER_COLUMNS.get(name, []):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in NUMERIC_COLUMNS.get(name, []):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.where(pd.notna(frame), None)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        records.append({key: _clean_value(value) for key, value in row.items()})
    return records


def _filter_fk(
    records: list[dict[str, Any]],
    column: str,
    valid: set[str],
) -> tuple[list[dict[str, Any]], int]:
    kept = [record for record in records if str(record.get(column)) in valid]
    return kept, len(records) - len(kept)


def _load_table(
    engine: Engine,
    table: Any,
    records: list[dict[str, Any]],
    *,
    chunk_size: int = 2000,
) -> int:
    if not records:
        return 0
    statement = pg_insert(table).on_conflict_do_nothing()
    with engine.begin() as connection:
        for start in range(0, len(records), chunk_size):
            connection.execute(statement, records[start : start + chunk_size])
    return len(records)


def load_olist_dataset(
    *,
    csv_dir: Path,
    database_url: str,
    create_schema: bool = True,
    truncate: bool = False,
) -> dict[str, int]:
    csv_dir = csv_dir.expanduser().resolve()
    missing = [filename for filename in FILE_MAP.values() if not (csv_dir / filename).exists()]
    if missing:
        raise FileNotFoundError(
            "Missing Olist CSV files in "
            f"{csv_dir}: {', '.join(missing)}. Download them from Kaggle first."
        )

    url = async_database_url(database_url)
    if url.startswith("sqlite"):
        raise ValueError("The Olist loader targets PostgreSQL/Supabase. Use seed_demo for SQLite.")
    connect_args = {"prepare_threshold": None} if make_url(url).port == 6543 else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)

    data: dict[str, list[dict[str, Any]]] = {}
    try:
        if create_schema:
            metadata.create_all(engine)

        if truncate:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "TRUNCATE TABLE public.order_payments, public.order_items, "
                        "public.orders, public.products, public.sellers "
                        "RESTART IDENTITY CASCADE"
                    )
                )

        for name, filename in FILE_MAP.items():
            frame = _prepare_frame(name, _read_csv(csv_dir / filename))
            data[name] = _records(frame)
            print(f"Read {len(data[name]):>8,} rows from {filename}")

        order_ids = {str(record["order_id"]) for record in data["orders"]}
        product_ids = {str(record["product_id"]) for record in data["products"]}
        seller_ids = {str(record["seller_id"]) for record in data["sellers"]}

        data["order_items"], skipped_orders = _filter_fk(data["order_items"], "order_id", order_ids)
        data["order_items"], skipped_products = _filter_fk(
            data["order_items"], "product_id", product_ids
        )
        data["order_items"], skipped_sellers = _filter_fk(
            data["order_items"], "seller_id", seller_ids
        )
        data["order_payments"], skipped_payments = _filter_fk(
            data["order_payments"], "order_id", order_ids
        )
        if any([skipped_orders, skipped_products, skipped_sellers, skipped_payments]):
            print(
                "Skipped orphan rows -> "
                f"items/order={skipped_orders}, items/product={skipped_products}, "
                f"items/seller={skipped_sellers}, payments/order={skipped_payments}"
            )

        counts: dict[str, int] = {}
        for table in (sellers, products, orders, order_items, order_payments):
            counts[table.name] = _load_table(engine, table, data[table.name])
            print(f"Loaded {counts[table.name]:>8,} rows into {table.name}")

        with engine.connect() as connection:
            final_counts = {
                table.name: int(
                    connection.execute(select(func.count()).select_from(table)).scalar_one()
                )
                for table in (sellers, products, orders, order_items, order_payments)
            }
        return final_counts
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the Olist CSV dataset into Supabase/PostgreSQL.")
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory containing the five Olist CSV files.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL/Supabase URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--no-create-schema",
        action="store_true",
        help="Skip metadata.create_all (use when database/schema.sql was already applied).",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate the five Olist tables before loading.",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Provide --database-url or set DATABASE_URL.")
    if not args.database_url.startswith("postgres"):
        raise SystemExit("Olist ingestion requires a PostgreSQL/Supabase DATABASE_URL.")

    try:
        counts = load_olist_dataset(
            csv_dir=args.csv_dir,
            database_url=args.database_url,
            create_schema=not args.no_create_schema,
            truncate=args.truncate,
        )
    except Exception as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("\nDatabase ready:")
    for table, count in counts.items():
        print(f"  {table:>16}: {count:,} rows")


if __name__ == "__main__":
    main()
