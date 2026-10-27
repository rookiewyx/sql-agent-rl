"""从 ODS 构建 DWS 宽表，并在同一事务里做断言。

用法：
    python -m data.build_dws
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import psycopg

from common.config import PROJECT_ROOT, database_url

SQL_DIR = PROJECT_ROOT / "data" / "warehouse"

# 明细的父表全部存在。用 EXISTS 计数，不会因为父表有重复键而扇出
ITEM_HAS_PARENTS = """
    EXISTS (SELECT 1 FROM ods.orders o WHERE o.order_id = i.order_id
            AND EXISTS (SELECT 1 FROM ods.customers c WHERE c.customer_id = o.customer_id))
    AND EXISTS (SELECT 1 FROM ods.sellers s WHERE s.seller_id = i.seller_id)
    AND EXISTS (SELECT 1 FROM ods.products p WHERE p.product_id = i.product_id)
"""


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    actual_sql: str
    expected_sql: str


CHECKS = [
    Check(
        "order_item 行数 = ODS 中父表齐全的明细数",
        "SELECT COUNT(*) FROM dws.order_item",
        f"SELECT COUNT(*) FROM ods.order_items i WHERE {ITEM_HAS_PARENTS}",
    ),
    Check(
        "order_item 商品金额守恒",
        "SELECT SUM(item_price) FROM dws.order_item",
        f"SELECT SUM(price) FROM ods.order_items i WHERE {ITEM_HAS_PARENTS}",
    ),
    Check(
        "order_category 覆盖 order_item 的全部订单",
        "SELECT COUNT(DISTINCT order_id) FROM dws.order_category",
        "SELECT COUNT(DISTINCT order_id) FROM dws.order_item",
    ),
    Check(
        "review 行数 = ODS 中去重且父表齐全的评价数",
        "SELECT COUNT(*) FROM dws.review",
        """
        SELECT COUNT(*) FROM (
            SELECT DISTINCT review_id, order_id FROM ods.order_reviews r
            WHERE review_id IS NOT NULL AND order_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM ods.orders o WHERE o.order_id = r.order_id
                  AND EXISTS (SELECT 1 FROM ods.customers c WHERE c.customer_id = o.customer_id))
        ) x
        """,
    ),
]


def run_checks(cur: psycopg.Cursor) -> list[str]:
    problems: list[str] = []
    for check in CHECKS:
        actual = cur.execute(check.actual_sql).fetchone()[0]
        expected = cur.execute(check.expected_sql).fetchone()[0]
        ok = actual == expected
        print(f"[{'OK' if ok else 'FAIL'}] {check.name}：实际 {actual}，期望 {expected}")
        if not ok:
            problems.append(f"{check.name}：实际 {actual}，期望 {expected}")
    return problems


def build(url: str) -> None:
    # 连接的 with 块正常结束时提交；抛出异常时整体回滚，旧表保持不变
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for path in sorted(SQL_DIR.glob("*.sql")):
            print(f"执行 {path.name}")
            cur.execute(path.read_text(encoding="utf-8"))
        problems = run_checks(cur)
        if problems:
            raise BuildError("断言失败，已回滚：\n" + "\n".join(problems))
        for table in ("order_item", "order_category", "review"):
            cur.execute(f"ANALYZE dws.{table}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=database_url())
    args = parser.parse_args()
    try:
        build(args.database_url)
    except (BuildError, psycopg.Error) as e:
        print(f"构建失败：{e}", file=sys.stderr)
        return 1
    print("DWS 构建完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())