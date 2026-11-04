-- LogiSQL-Agent | Olist relational schema for Supabase/PostgreSQL
-- Run this in the Supabase SQL editor before loading the CSV files.
-- Five tables, explicit primary/foreign keys, and analytics indexes.

BEGIN;

CREATE TABLE IF NOT EXISTS public.sellers (
    seller_id             TEXT PRIMARY KEY,
    seller_zip_code_prefix VARCHAR(16),
    seller_city           VARCHAR(128),
    seller_state          VARCHAR(8)
);

CREATE TABLE IF NOT EXISTS public.products (
    product_id                TEXT PRIMARY KEY,
    product_category_name     VARCHAR(128),
    product_name_length       INTEGER,
    product_description_length INTEGER,
    product_photos_qty        INTEGER,
    product_weight_g          INTEGER,
    product_length_cm         INTEGER,
    product_height_cm         INTEGER,
    product_width_cm          INTEGER
);

CREATE TABLE IF NOT EXISTS public.orders (
    order_id                       TEXT PRIMARY KEY,
    customer_id                    TEXT NOT NULL,
    order_status                   VARCHAR(32) NOT NULL,
    order_purchase_timestamp       TIMESTAMPTZ NOT NULL,
    order_approved_at              TIMESTAMPTZ,
    order_delivered_carrier_date   TIMESTAMPTZ,
    order_delivered_customer_date  TIMESTAMPTZ,
    order_estimated_delivery_date  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.order_items (
    order_id           TEXT NOT NULL REFERENCES public.orders(order_id) ON DELETE CASCADE,
    order_item_id      INTEGER NOT NULL,
    product_id         TEXT NOT NULL REFERENCES public.products(product_id),
    seller_id          TEXT NOT NULL REFERENCES public.sellers(seller_id),
    shipping_limit_date TIMESTAMPTZ,
    price              NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    freight_value      NUMERIC(12, 2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE IF NOT EXISTS public.order_payments (
    order_id            TEXT NOT NULL REFERENCES public.orders(order_id) ON DELETE CASCADE,
    payment_sequential  INTEGER NOT NULL,
    payment_type        VARCHAR(32) NOT NULL,
    payment_installments INTEGER NOT NULL CHECK (payment_installments >= 0),
    payment_value       NUMERIC(12, 2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE INDEX IF NOT EXISTS ix_orders_customer_id
    ON public.orders (customer_id);
CREATE INDEX IF NOT EXISTS ix_orders_status
    ON public.orders (order_status);
CREATE INDEX IF NOT EXISTS ix_orders_purchase_ts
    ON public.orders (order_purchase_timestamp);
CREATE INDEX IF NOT EXISTS ix_order_items_product_id
    ON public.order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_order_items_seller_id
    ON public.order_items (seller_id);
CREATE INDEX IF NOT EXISTS ix_order_items_shipping_limit
    ON public.order_items (shipping_limit_date);
CREATE INDEX IF NOT EXISTS ix_products_category
    ON public.products (product_category_name);
CREATE INDEX IF NOT EXISTS ix_sellers_state
    ON public.sellers (seller_state);
CREATE INDEX IF NOT EXISTS ix_payments_type
    ON public.order_payments (payment_type);

-- Refresh PostgREST/Supabase's schema cache after loading.
NOTIFY pgrst, 'reload schema';

COMMIT;
