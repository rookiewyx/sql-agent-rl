"""build_dws 的测试：手工构造极小的 ODS，逐个埋入问题。"""

from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from data import build_dws
from data.build_dws import BuildError, build

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="未设置 TEST_DATABASE_URL")

if DSN and "test" not in conninfo_to_dict(DSN).get("dbname", ""):
    pytest.exit("TEST_DATABASE_URL 的库名不含 test，拒绝运行", returncode=1)

# 只建构建脚本用到的列。数据少到每个正确答案都能心算
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
def ods():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(MINI_ODS)
        yield conn


def count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_clean_build(ods):
    build(DSN)
    assert count(ods, "dws.order_item") == 3
    assert count(ods, "dws.order_category") == 3  # o1 两个类目，o2 一个
    assert count(ods, "dws.review") == 2
    cats = dict(ods.execute("SELECT product_id, category FROM dws.order_item").fetchall())
    assert cats == {"p1": "health_beauty", "p2": "unknown", "p3": "categoria_nova"}


def test_item_with_missing_parent_is_excluded(ods):
    ods.execute("INSERT INTO ods.order_items VALUES ('o2', 2, 'p_missing', 's1', 99, 1)")
    build(DSN)
    assert count(ods, "dws.order_item") == 3


def test_duplicate_dimension_key_fails_and_rolls_back(ods):
    build(DSN)                                            # 先成功构建一次
    ods.execute("INSERT INTO ods.customers VALUES ('c1', 'MG')")  # c1 重复 → 扇出
    with pytest.raises(psycopg.errors.UniqueViolation):
        build(DSN)
    assert count(ods, "dws.order_item") == 3              # 回滚：还是上一次的结果


def test_duplicate_review_keeps_latest_answer(ods):
    ods.execute("INSERT INTO ods.order_reviews VALUES ('r1', 'o1', 2, '2018-01-11', '2018-01-20')")
    build(DSN)
    assert count(ods, "dws.review") == 2
    score = ods.execute("SELECT review_score FROM dws.review WHERE review_id = 'r1'").fetchone()[0]
    assert score == 2                                     # 保留回复时间最晚的那条


def test_sql_bug_that_drops_rows_is_caught(ods, tmp_path, monkeypatch):
    # 变异测试：把类目翻译的 LEFT JOIN 改成 JOIN，没有翻译的明细会被悄悄丢掉
    for path in build_dws.SQL_DIR.glob("*.sql"):
        sql = path.read_text(encoding="utf-8")
        if path.name.startswith("01"):
            mutated = sql.replace("LEFT JOIN ods.category_translation", "JOIN ods.category_translation")
            assert mutated != sql, "没找到要替换的文本，这个测试什么都没测"
            sql = mutated
        (tmp_path / path.name).write_text(sql, encoding="utf-8")
    monkeypatch.setattr(build_dws, "SQL_DIR", tmp_path)

    with pytest.raises(BuildError, match="order_item 行数"):
        build(DSN)