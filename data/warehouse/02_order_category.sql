-- 行粒度：一笔订单中出现的一个类目；用于把订单级事实（评价）归属到类目
DROP TABLE IF EXISTS dws.order_category;

CREATE TABLE dws.order_category AS
SELECT DISTINCT
    order_id,
    category
FROM dws.order_item;

ALTER TABLE dws.order_category ADD PRIMARY KEY (order_id, category);