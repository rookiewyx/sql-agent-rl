"""所有测试共享的 fixture。pytest 会自动加载本文件。"""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

import common.config  # noqa: F401  导入时会加载 .env

DSN = os.environ.get("TEST_DATABASE_URL")

MINI_ODS = """
CREATE SCHEMA IF NOT EXISTS ods;
DROP TABLE IF EXISTS ods.order_items, ods.orders, ods.customers, ods.sellers,
    ods.products, ods.category_translation, ods.order_reviews;

CREATE TABLE ods.customers (customer_id text, customer_state text);
CREATE TABLE ods.sellers (seller_id text, seller_state text);
CREATE TABLE ods.products (product_id text, product_category_name text);
CREATE TABLE ods.category_translation (
    product_category_name text, product_category_name_english text);
CREATE TABLE ods.orders (
    order_id text, customer_id text, order_status text,
    order_purchase_timestamp timestamp, order_delivered_customer_date timestamp);
CREATE TABLE ods.order_items (
    order_id text, order_item_id int, product_id text, seller_id text,
    price numeric(10, 2), freight_value numeric(10, 2));
CREATE TABLE ods.order_reviews (
    review_id text, order_id text, review_score int,
    review_creation_date timestamp, review_answer_timestamp timestamp);

INSERT INTO ods.customers VALUES ('c1', 'SP'), ('c2', 'RJ');
INSERT INTO ods.sellers VALUES ('s1', 'SP');
INSERT INTO ods.products VALUES
    ('p1', 'beleza_saude'),     -- 有翻译
    ('p2', NULL),               -- 缺类目
    ('p3', 'categoria_nova');   -- 没有翻译
INSERT INTO ods.category_translation VALUES ('beleza_saude', 'health_beauty');
INSERT INTO ods.orders VALUES
    ('o1', 'c1', 'delivered', '2018-01-05', '2018-01-10'),
    ('o2', 'c2', 'delivered', '2018-02-01', '2018-02-08');
INSERT INTO ods.order_items VALUES
    ('o1', 1, 'p1', 's1', 100.00, 10.00),
    ('o1', 2, 'p2', 's1',  50.00,  5.00),
    ('o2', 1, 'p3', 's1',  30.00,  3.00);
INSERT INTO ods.order_reviews VALUES
    ('r1', 'o1', 5, '2018-01-11', '2018-01-12'),
    ('r2', 'o2', 1, '2018-02-09', '2018-02-10');
"""


@pytest.fixture
def dsn() -> str:
    if not DSN:
        pytest.skip("未设置 TEST_DATABASE_URL")
    if "test" not in conninfo_to_dict(DSN).get("dbname", ""):
        pytest.exit("TEST_DATABASE_URL 的库名不含 test，拒绝运行", returncode=1)
    return DSN


@pytest.fixture
def ods(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(MINI_ODS)
        yield conn