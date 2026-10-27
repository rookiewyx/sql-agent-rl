-- 行粒度：一条评价；唯一键 (review_id, order_id)
-- 去重用 CTE，不建视图（原因见下文）
DROP TABLE IF EXISTS dws.review;

CREATE TABLE dws.review AS
WITH
    dedup AS (
        SELECT DISTINCT
            ON (review_id, order_id) review_id,
            order_id,
            review_score,
            review_creation_date
        FROM ods.order_reviews
        WHERE
            review_id IS NOT NULL
            AND order_id IS NOT NULL
        ORDER BY
            review_id,
            order_id,
            review_answer_timestamp DESC NULLS LAST
    )
SELECT r.review_id, r.order_id, r.review_score, r.review_creation_date AS review_created_ts, o.order_status, c.customer_state
FROM dedup r
    JOIN ods.orders o ON o.order_id = r.order_id
    JOIN ods.customers c ON c.customer_id = o.customer_id;

ALTER TABLE dws.review ADD PRIMARY KEY (review_id, order_id);