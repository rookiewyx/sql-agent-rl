"""Olist 原始表的结构定义（ODS 层）。

ODS 层不加主键与外键约束：唯一性和参照完整性由数据画像检查。
如果在导入时就加约束，存在问题的数据会直接导入失败，画像也就无从谈起。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    table: str                              # ods 中的表名
    filename: str                           # 原始 CSV 文件名
    columns: tuple[tuple[str, str], ...]    # (列名, PostgreSQL 类型)，顺序与 CSV 表头一致

    @property
    def column_names(self) -> list[str]:
        return [name for name, _ in self.columns]

    def create_sql(self, schema: str = "ods") -> str:
        cols = ",\n    ".join(f"{name} {typ}" for name, typ in self.columns)
        return f"CREATE TABLE {schema}.{self.table} (\n    {cols}\n)"


TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "orders",
        "olist_orders_dataset.csv",
        (
            ("order_id", "text"),
            ("customer_id", "text"),
            ("order_status", "text"),
            ("order_purchase_timestamp", "timestamp"),
            ("order_approved_at", "timestamp"),
            ("order_delivered_carrier_date", "timestamp"),
            ("order_delivered_customer_date", "timestamp"),
            ("order_estimated_delivery_date", "timestamp"),
        ),
    ),
    TableSpec(
        "order_items",
        "olist_order_items_dataset.csv",
        (
            ("order_id", "text"),
            ("order_item_id", "integer"),
            ("product_id", "text"),
            ("seller_id", "text"),
            ("shipping_limit_date", "timestamp"),
            ("price", "numeric(12,2)"),
            ("freight_value", "numeric(12,2)"),
        ),
    ),
    TableSpec(
        "order_payments",
        "olist_order_payments_dataset.csv",
        (
            ("order_id", "text"),
            ("payment_sequential", "integer"),
            ("payment_type", "text"),
            ("payment_installments", "integer"),
            ("payment_value", "numeric(12,2)"),
        ),
    ),
    TableSpec(
        "order_reviews",
        "olist_order_reviews_dataset.csv",
        (
            ("review_id", "text"),
            ("order_id", "text"),
            ("review_score", "smallint"),
            ("review_comment_title", "text"),
            ("review_comment_message", "text"),
            ("review_creation_date", "timestamp"),
            ("review_answer_timestamp", "timestamp"),
        ),
    ),
    TableSpec(
        "customers",
        "olist_customers_dataset.csv",
        (
            ("customer_id", "text"),
            ("customer_unique_id", "text"),
            ("customer_zip_code_prefix", "text"),
            ("customer_city", "text"),
            ("customer_state", "text"),
        ),
    ),
    TableSpec(
        "products",
        "olist_products_dataset.csv",
        (
            ("product_id", "text"),
            ("product_category_name", "text"),
            # 以下两列在原始数据中的拼写就是 "lenght"，保持一致
            ("product_name_lenght", "numeric"),
            ("product_description_lenght", "numeric"),
            ("product_photos_qty", "numeric"),
            ("product_weight_g", "numeric"),
            ("product_length_cm", "numeric"),
            ("product_height_cm", "numeric"),
            ("product_width_cm", "numeric"),
        ),
    ),
    TableSpec(
        "sellers",
        "olist_sellers_dataset.csv",
        (
            ("seller_id", "text"),
            ("seller_zip_code_prefix", "text"),
            ("seller_city", "text"),
            ("seller_state", "text"),
        ),
    ),
    TableSpec(
        "category_translation",
        "product_category_name_translation.csv",
        (
            ("product_category_name", "text"),
            ("product_category_name_english", "text"),
        ),
    ),
)

TABLES_BY_NAME = {spec.table: spec for spec in TABLES}