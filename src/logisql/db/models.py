from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)

metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("order_id", String(64), primary_key=True),
    Column("customer_id", String(64), nullable=False),
    Column("order_status", String(32), nullable=False),
    Column("order_purchase_timestamp", DateTime(timezone=True), nullable=False),
    Column("order_approved_at", DateTime(timezone=True), nullable=True),
    Column("order_delivered_carrier_date", DateTime(timezone=True), nullable=True),
    Column("order_delivered_customer_date", DateTime(timezone=True), nullable=True),
    Column("order_estimated_delivery_date", DateTime(timezone=True), nullable=True),
)

order_items = Table(
    "order_items",
    metadata,
    Column("order_id", String(64), ForeignKey("orders.order_id", ondelete="CASCADE"), primary_key=True),
    Column("order_item_id", Integer, primary_key=True),
    Column("product_id", String(64), ForeignKey("products.product_id"), nullable=False),
    Column("seller_id", String(64), ForeignKey("sellers.seller_id"), nullable=False),
    Column("shipping_limit_date", DateTime(timezone=True), nullable=True),
    Column("price", Numeric(12, 2), nullable=False),
    Column("freight_value", Numeric(12, 2), nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("product_id", String(64), primary_key=True),
    Column("product_category_name", String(128), nullable=True),
    Column("product_name_length", Integer, nullable=True),
    Column("product_description_length", Integer, nullable=True),
    Column("product_photos_qty", Integer, nullable=True),
    Column("product_weight_g", Integer, nullable=True),
    Column("product_length_cm", Integer, nullable=True),
    Column("product_height_cm", Integer, nullable=True),
    Column("product_width_cm", Integer, nullable=True),
)

sellers = Table(
    "sellers",
    metadata,
    Column("seller_id", String(64), primary_key=True),
    Column("seller_zip_code_prefix", String(16), nullable=True),
    Column("seller_city", String(128), nullable=True),
    Column("seller_state", String(8), nullable=True),
)

order_payments = Table(
    "order_payments",
    metadata,
    Column(
        "order_id",
        String(64),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("payment_sequential", Integer, primary_key=True),
    Column("payment_type", String(32), nullable=False),
    Column("payment_installments", Integer, nullable=False),
    Column("payment_value", Numeric(12, 2), nullable=False),
)

Index("ix_orders_customer_id", orders.c.customer_id)
Index("ix_orders_status", orders.c.order_status)
Index("ix_orders_purchase_ts", orders.c.order_purchase_timestamp)
Index("ix_order_items_product_id", order_items.c.product_id)
Index("ix_order_items_seller_id", order_items.c.seller_id)
Index("ix_order_items_shipping_limit", order_items.c.shipping_limit_date)
Index("ix_products_category", products.c.product_category_name)
Index("ix_sellers_state", sellers.c.seller_state)
Index("ix_payments_type", order_payments.c.payment_type)
