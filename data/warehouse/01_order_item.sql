-- 行粒度：一条订单明细；唯一键 (order_id, order_item_id)
-- 只允许 N:1 关联，避免扇出
CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.order_item;

CREATE TABLE dws.order_item AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_id,
    c.customer_state,
    s.seller_state,
    COALESCE(
        t.product_category_name_english,
        p.product_category_name,
        'unknown'
    ) AS category,
    o.order_status,
    o.order_purchase_timestamp AS purchase_ts,
    o.order_delivered_customer_date AS delivered_ts,
    i.price AS item_price,
    i.freight_value
FROM
    ods.order_items i
    JOIN ods.orders o ON o.order_id = i.order_id
    JOIN ods.customers c ON c.customer_id = o.customer_id
    JOIN ods.sellers s ON s.seller_id = i.seller_id
    JOIN ods.products p ON p.product_id = i.product_id
    LEFT JOIN ods.category_translation t ON t.product_category_name = p.product_category_name;

ALTER TABLE dws.order_item ADD PRIMARY KEY (order_id, order_item_id);