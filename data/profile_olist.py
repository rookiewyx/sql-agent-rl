"""Olist 数据画像：验证宽表设计所依赖的假设（docs/mvp_spec.md §1.2）。

用法：
    python -m data.profile_olist                 # 输出 docs/data_profile.md 与 data/profile_result.json
    python -m data.profile_olist --write-env     # 同时把 REFERENCE_DATE 写入 .env

每项检查给出状态：
    PASS  假设成立
    WARN  假设不完全成立，但有既定的处理方式（如去重、记录丢弃行数）
    FAIL  假设不成立，必须先修改宽表设计
    INFO  只用于记录，没有通过 / 不通过之分
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from common.config import PROJECT_ROOT, database_url, set_env_value
from data.reference_date import ReferenceDateResult, determine_reference_date

REPORT_MD = PROJECT_ROOT / "docs" / "data_profile.md"
RESULT_JSON = PROJECT_ROOT / "data" / "profile_result.json"

# 指标定义中要排除的订单状态（docs/mvp_spec.md §3.1）
EXPECTED_EXCLUDED_STATUSES = ("canceled", "unavailable")


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class Check:
    id: str
    title: str
    status: str
    summary: str
    impact: str
    metrics: dict[str, Any] = field(default_factory=dict)
    tables: list[Table] = field(default_factory=list)


# ---------------------------------------------------------------- 查询工具

def rows(cur: psycopg.Cursor, sql: str) -> list[tuple]:
    cur.execute(sql)
    return cur.fetchall()


def scalar(cur: psycopg.Cursor, sql: str) -> Any:
    cur.execute(sql)
    return cur.fetchone()[0]


def pct(a: int, b: int) -> str:
    return "0%" if not b else f"{a / b:.2%}"


def uniqueness(cur: psycopg.Cursor, table: str, cols: list[str]) -> dict[str, Any]:
    key = ", ".join(cols)
    null_cond = " OR ".join(f"{c} IS NULL" for c in cols)
    total = scalar(cur, f"SELECT count(*) FROM {table}")
    null_keys = scalar(cur, f"SELECT count(*) FROM {table} WHERE {null_cond}")
    distinct = scalar(
        cur, f"SELECT count(*) FROM (SELECT DISTINCT {key} FROM {table} WHERE NOT ({null_cond})) t"
    )
    examples = rows(
        cur,
        f"""SELECT {key}, count(*) AS n FROM {table} WHERE NOT ({null_cond})
            GROUP BY {key} HAVING count(*) > 1 ORDER BY n DESC, {key} LIMIT 5""",
    )
    return {
        "rows": total,
        "null_keys": null_keys,
        "distinct_keys": distinct,
        "duplicate_rows": total - null_keys - distinct,   # 重复键多出来的行数
        "duplicate_examples": [list(r) for r in examples],
    }


def uniqueness_check(cur, cid: str, title: str, table: str, cols: list[str], impact_fail: str) -> Check:
    u = uniqueness(cur, table, cols)
    ok = u["duplicate_rows"] == 0 and u["null_keys"] == 0
    key = "(" + ", ".join(cols) + ")"
    summary = (
        f"{u['rows']:,} 行，{key} 唯一，无空键。"
        if ok
        else f"{u['rows']:,} 行，重复键多出 {u['duplicate_rows']:,} 行，空键 {u['null_keys']:,} 行。"
    )
    check = Check(
        cid, title, "PASS" if ok else "FAIL", summary,
        "无。" if ok else impact_fail, metrics=u,
    )
    if u["duplicate_examples"]:
        check.tables.append(Table("重复键示例（前 5 个）", cols + ["出现次数"], u["duplicate_examples"]))
    return check

# ---------------------------------------------------------------- 各项检查

def check_p1(cur) -> Check:
    return uniqueness_check(
        cur, "P1", "orders.order_id 唯一", "ods.orders", ["order_id"],
        "订单表存在重复主键，order_item 宽表关联订单时会扇出。需要先确定订单去重规则。",
    )


def check_p2(cur) -> Check:
    return uniqueness_check(
        cur, "P2", "order_items (order_id, order_item_id) 唯一", "ods.order_items",
        ["order_id", "order_item_id"],
        "明细表的唯一键不成立，dws.order_item 无法以 (order_id, order_item_id) 为主键。需要重新定义明细粒度。",
    )


def check_p3(cur) -> Check:
    return uniqueness_check(
        cur, "P3", "customers.customer_id 唯一", "ods.customers", ["customer_id"],
        "客户表存在重复 customer_id，订单关联客户时会扇出。需要先确定客户去重规则。",
    )


def check_p4(cur) -> Check:
    c = uniqueness_check(
        cur, "P4", "products.product_id 唯一；类目空值", "ods.products", ["product_id"],
        "商品表存在重复 product_id，明细关联商品时会扇出。需要先确定商品去重规则。",
    )
    null_products = scalar(cur, "SELECT count(*) FROM ods.products WHERE product_category_name IS NULL")
    blank_products = scalar(
        cur, "SELECT count(*) FROM ods.products WHERE product_category_name IS NOT NULL AND trim(product_category_name) = ''"
    )
    items_null_cat = scalar(
        cur,
        """SELECT count(*) FROM ods.order_items i JOIN ods.products p ON p.product_id = i.product_id
           WHERE p.product_category_name IS NULL OR trim(p.product_category_name) = ''""",
    )
    total_items = scalar(cur, "SELECT count(*) FROM ods.order_items")
    c.metrics.update(
        products_null_category=null_products,
        products_blank_category=blank_products,
        items_with_null_category=items_null_cat,
        items_total=total_items,
    )
    c.summary += (
        f" 类目为空的商品 {null_products:,} 个（空字符串 {blank_products:,} 个），"
        f"涉及明细 {items_null_cat:,} 条（占全部明细 {pct(items_null_cat, total_items)}）。"
    )
    if c.status == "PASS":
        c.impact = "类目为空的商品在宽表中记为 unknown。"
        if blank_products:
            c.impact += " 空字符串类目也需要按 unknown 处理（宽表构建时使用 NULLIF(trim(...), '')）。"
    return c


def check_p5(cur) -> Check:
    t = uniqueness(cur, "ods.category_translation", ["product_category_name"])
    untranslated = rows(
        cur,
        """SELECT p.product_category_name,
                  count(DISTINCT p.product_id) AS products,
                  count(i.order_id)            AS items
           FROM ods.products p
           LEFT JOIN ods.category_translation t ON t.product_category_name = p.product_category_name
           LEFT JOIN ods.order_items i          ON i.product_id = p.product_id
           WHERE p.product_category_name IS NOT NULL AND trim(p.product_category_name) <> ''
             AND t.product_category_name IS NULL
           GROUP BY p.product_category_name
           ORDER BY items DESC, p.product_category_name""",
    )
    categories = scalar(
        cur,
        "SELECT count(DISTINCT product_category_name) FROM ods.products WHERE product_category_name IS NOT NULL",
    )
    translation_unique = t["duplicate_rows"] == 0 and t["null_keys"] == 0
    status = "INFO" if translation_unique else "FAIL"
    summary = (
        f"翻译表 {t['rows']:,} 行，键{'唯一' if translation_unique else '不唯一'}；"
        f"商品类目 {categories:,} 个，其中 {len(untranslated)} 个没有英文翻译。"
    )
    impact = (
        "没有翻译的类目在宽表中保留原始葡萄牙语名称。"
        if translation_unique
        else "翻译表的键不唯一，商品左关联翻译表时会扇出，必须先对翻译表去重。"
    )
    c = Check("P5", "类目翻译覆盖率", status, summary, impact,
              metrics={"translation": t, "categories": categories,
                       "untranslated": [list(r) for r in untranslated]})
    if untranslated:
        c.tables.append(Table("没有英文翻译的类目", ["类目（原始名称）", "商品数", "明细数"],
                              [list(r) for r in untranslated]))
    return c


def check_p6(cur) -> Check:
    total = scalar(cur, "SELECT count(*) FROM ods.order_reviews")
    distinct_review_id = scalar(cur, "SELECT count(DISTINCT review_id) FROM ods.order_reviews")
    pair = uniqueness(cur, "ods.order_reviews", ["review_id", "order_id"])
    review_ids_multi_orders = scalar(
        cur,
        """SELECT count(*) FROM (SELECT review_id FROM ods.order_reviews
           GROUP BY review_id HAVING count(DISTINCT order_id) > 1) t""",
    )
    per_order = rows(
        cur,
        """SELECT CASE WHEN n >= 3 THEN '3+' ELSE n::text END AS reviews, count(*) AS orders
           FROM (SELECT order_id, count(*) AS n FROM ods.order_reviews GROUP BY order_id) t
           GROUP BY 1 ORDER BY 1""",
    )
    null_scores = scalar(cur, "SELECT count(*) FROM ods.order_reviews WHERE review_score IS NULL")
    out_of_range = scalar(
        cur, "SELECT count(*) FROM ods.order_reviews WHERE review_score NOT BETWEEN 1 AND 5"
    )
    score_dist = rows(
        cur,
        "SELECT review_score, count(*) FROM ods.order_reviews GROUP BY 1 ORDER BY 1 NULLS LAST",
    )

    issues = []
    if pair["duplicate_rows"]:
        issues.append(f"(review_id, order_id) 重复多出 {pair['duplicate_rows']:,} 行")
    if pair["null_keys"]:
        issues.append(f"空键 {pair['null_keys']:,} 行")
    if out_of_range:
        issues.append(f"评分超出 1–5 的 {out_of_range:,} 行")
    status = "WARN" if issues else "PASS"

    summary = (
        f"{total:,} 行；review_id 去重后 {distinct_review_id:,} 个，"
        f"其中 {review_ids_multi_orders:,} 个 review_id 对应多笔订单；"
        f"(review_id, order_id) 去重后 {pair['distinct_keys']:,} 个；评分为空 {null_scores:,} 行。"
    )
    if issues:
        summary += " 问题：" + "；".join(issues) + "。"

    impacts = []
    if review_ids_multi_orders:
        impacts.append("review_id 单独不能作为主键，dws.review 使用 (review_id, order_id)。")
    if pair["duplicate_rows"]:
        impacts.append(
            "需要建立 ods.order_reviews_dedup：每个 (review_id, order_id) 按 review_answer_timestamp "
            f"保留最新一条，预计去掉 {pair['duplicate_rows']:,} 行。"
        )
    if out_of_range:
        impacts.append("评分超出 1–5 的记录需要确定处理规则（建议视为无效评分，按空值处理）。")
    if null_scores:
        impacts.append(f"评分为空的 {null_scores:,} 条评价不计入差评率的分子与分母。")
    else:
        impacts.append("当前数据中没有空评分，差评率的空值规则仍保留，用于防御后续数据。")

    c = Check("P6", "评价表的唯一键与评分", status, summary, " ".join(impacts),
              metrics={"rows": total, "distinct_review_id": distinct_review_id,
                       "review_id_pair": pair, "review_ids_in_multiple_orders": review_ids_multi_orders,
                       "null_scores": null_scores, "out_of_range_scores": out_of_range,
                       "reviews_per_order": [list(r) for r in per_order],
                       "score_distribution": [list(r) for r in score_dist]})
    c.tables.append(Table("每笔订单的评价数", ["评价数", "订单数"], [list(r) for r in per_order]))
    c.tables.append(Table("评分分布", ["评分", "评价数"],
                          [["空" if s is None else s, n] for s, n in score_dist]))
    if pair["duplicate_examples"]:
        c.tables.append(Table("重复的 (review_id, order_id) 示例", ["review_id", "order_id", "出现次数"],
                              pair["duplicate_examples"]))
    return c


def check_p7(cur) -> Check:
    statuses = rows(cur, "SELECT order_status, count(*) FROM ods.orders GROUP BY 1 ORDER BY 2 DESC")
    present = {s for s, _ in statuses}
    missing = [s for s in EXPECTED_EXCLUDED_STATUSES if s not in present]
    status = "PASS" if not missing else "WARN"
    summary = f"共 {len(statuses)} 种状态：" + "、".join(f"{s}（{n:,}）" for s, n in statuses) + "。"
    impact = (
        "指标定义中的排除条件 order_status NOT IN ('canceled', 'unavailable') 与实际取值一致。"
        if not missing
        else f"数据中不存在状态 {missing}，需要核对指标定义中的排除条件。"
    )
    c = Check("P7", "订单状态取值", status, summary, impact,
              metrics={"statuses": [list(r) for r in statuses], "missing_expected": missing})
    c.tables.append(Table("订单状态", ["状态", "订单数"], [list(r) for r in statuses]))
    return c


def check_p8(cur) -> tuple[Check, ReferenceDateResult]:
    mn, mx, nulls = rows(
        cur,
        """SELECT min(order_purchase_timestamp), max(order_purchase_timestamp),
                  count(*) FILTER (WHERE order_purchase_timestamp IS NULL) FROM ods.orders""",
    )[0]
    monthly_rows = rows(
        cur,
        """SELECT date_trunc('month', order_purchase_timestamp)::date AS m, count(*)
           FROM ods.orders WHERE order_purchase_timestamp IS NOT NULL GROUP BY 1 ORDER BY 1""",
    )
    ref = determine_reference_date({m: n for m, n in monthly_rows})
    summary = (
        f"下单时间范围 {mn} 至 {mx}，下单时间为空 {nulls:,} 行。"
        f"最后一个完整月为 {ref.last_complete_month:%Y-%m}，"
        f"REFERENCE_DATE = {ref.reference_date.isoformat()}。"
    )
    impact = (
        f"\"上个月\"解析为 {ref.last_complete_month:%Y-%m}；"
        f"{ref.reference_date:%Y-%m} 及之后的月份按数据不完整处理（OUT_OF_SCOPE）。"
    )
    c = Check("P8", "下单时间范围与 REFERENCE_DATE", "INFO", summary, impact,
              metrics={"min_purchase_ts": str(mn), "max_purchase_ts": str(mx), "null_purchase_ts": nulls,
                       "monthly_orders": [[m.isoformat(), n] for m, n in monthly_rows],
                       "last_complete_month": ref.last_complete_month.isoformat(),
                       "reference_date": ref.reference_date.isoformat()})
    c.tables.append(Table(
        "尾部月份的判定过程（从最后一个月往前）",
        ["月份", "订单数", "之前 6 个月中位数", "阈值（中位数 × 0.5）", "是否完整"],
        [[t.month.strftime("%Y-%m"), t.orders,
          "—" if t.prior_median is None else f"{t.prior_median:g}",
          "—" if t.threshold is None else f"{t.threshold:g}",
          "是" if t.complete else "否"] for t in ref.trace],
    ))
    c.tables.append(Table("月度订单数", ["月份", "订单数"],
                          [[m.strftime("%Y-%m"), n] for m, n in monthly_rows]))
    return c, ref


def check_p9(cur) -> Check:
    checks = {
        "明细的 order_id 不在订单表": """SELECT count(*) FROM ods.order_items i
            WHERE NOT EXISTS (SELECT 1 FROM ods.orders o WHERE o.order_id = i.order_id)""",
        "订单的 customer_id 不在客户表": """SELECT count(*) FROM ods.orders o
            WHERE NOT EXISTS (SELECT 1 FROM ods.customers c WHERE c.customer_id = o.customer_id)""",
        "明细的 product_id 不在商品表": """SELECT count(*) FROM ods.order_items i
            WHERE NOT EXISTS (SELECT 1 FROM ods.products p WHERE p.product_id = i.product_id)""",
        "明细的 seller_id 不在卖家表": """SELECT count(*) FROM ods.order_items i
            WHERE NOT EXISTS (SELECT 1 FROM ods.sellers s WHERE s.seller_id = i.seller_id)""",
        "评价的 order_id 不在订单表": """SELECT count(*) FROM ods.order_reviews r
            WHERE NOT EXISTS (SELECT 1 FROM ods.orders o WHERE o.order_id = r.order_id)""",
    }
    results = {name: scalar(cur, sql) for name, sql in checks.items()}

    # dws.order_item 使用内关联：只有订单、客户、商品、卖家都存在的明细才会进入宽表
    items_total = scalar(cur, "SELECT count(*) FROM ods.order_items")
    items_kept = scalar(
        cur,
        """SELECT count(*) FROM ods.order_items i
           JOIN ods.orders o    ON o.order_id = i.order_id
           JOIN ods.customers c ON c.customer_id = o.customer_id
           JOIN ods.products p  ON p.product_id = i.product_id
           JOIN ods.sellers s   ON s.seller_id = i.seller_id""",
    )
    # dws.review：(review_id, order_id) 去重后，订单与客户都存在的评价
    reviews_kept = scalar(
        cur,
        """SELECT count(*) FROM (SELECT DISTINCT r.review_id, r.order_id FROM ods.order_reviews r
             JOIN ods.orders o    ON o.order_id = r.order_id
             JOIN ods.customers c ON c.customer_id = o.customer_id
             WHERE r.review_id IS NOT NULL AND r.order_id IS NOT NULL) t""",
    )
    ok = all(v == 0 for v in results.values())
    summary = (
        "所有关联键都能找到对应记录。" if ok
        else "存在找不到对应记录的关联键：" + "；".join(f"{k} {v:,} 行" for k, v in results.items() if v) + "。"
    )
    impact = (
        f"dws.order_item 预期 {items_kept:,} 行（ods.order_items 共 {items_total:,} 行"
        + ("" if items_kept == items_total else f"，内关联会去掉 {items_total - items_kept:,} 行")
        + f"）；dws.review 预期 {reviews_kept:,} 行。第 2 步的行数断言使用这两个数字。"
    )
    return Check("P9", "参照完整性", "PASS" if ok else "WARN", summary, impact,
                 metrics={"orphans": results, "items_total": items_total,
                          "expected_dws_order_item_rows": items_kept,
                          "expected_dws_review_rows": reviews_kept},
                 tables=[Table("找不到对应记录的关联键", ["检查", "行数"],
                               [[k, v] for k, v in results.items()])])


def check_p10(cur) -> Check:
    no_items = rows(
        cur,
        """SELECT o.order_status, count(*) FROM ods.orders o
           WHERE NOT EXISTS (SELECT 1 FROM ods.order_items i WHERE i.order_id = o.order_id)
           GROUP BY 1 ORDER BY 2 DESC""",
    )
    orders_no_items = sum(n for _, n in no_items)
    reviews_on_them = scalar(
        cur,
        """SELECT count(*) FROM ods.order_reviews r
           WHERE NOT EXISTS (SELECT 1 FROM ods.order_items i WHERE i.order_id = r.order_id)""",
    )
    reviews_total = scalar(cur, "SELECT count(*) FROM ods.order_reviews")
    summary = (
        f"没有任何明细的订单 {orders_no_items:,} 笔；这些订单上的评价 {reviews_on_them:,} 条"
        f"（占全部评价 {pct(reviews_on_them, reviews_total)}）。"
    )
    impact = (
        f"差评率按类目拆分时，这 {reviews_on_them:,} 条评价不计入任何类目；"
        "按客户州或总体统计时仍然计入。答案的口径说明需要提示这一覆盖范围差异。"
    )
    c = Check("P10", "没有明细的订单", "INFO", summary, impact,
              metrics={"orders_without_items": orders_no_items, "by_status": [list(r) for r in no_items],
                       "reviews_on_orders_without_items": reviews_on_them, "reviews_total": reviews_total})
    if no_items:
        c.tables.append(Table("没有明细的订单（按状态）", ["状态", "订单数"], [list(r) for r in no_items]))
    return c

# ---------------------------------------------------------------- 报告

def display_path(p: str) -> str:
    """项目内的路径显示为相对路径，避免在报告中暴露本机目录。"""
    try:
        return Path(p).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p


def is_synthetic(source_dir: str) -> bool:
    return (Path(source_dir) / "sample_truth.json").exists()


def fmt(v: Any) -> str:
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def render_table(t: Table, max_rows: int = 40) -> str:
    out = [f"**{t.title}**", "", "| " + " | ".join(t.columns) + " |",
           "| " + " | ".join("---" for _ in t.columns) + " |"]
    for r in t.rows[:max_rows]:
        out.append("| " + " | ".join(fmt(v) for v in r) + " |")
    if len(t.rows) > max_rows:
        out.append(f"\n（共 {len(t.rows)} 行，只显示前 {max_rows} 行）")
    return "\n".join(out)


def render_markdown(checks: list[Check], manifest: list[tuple], ref: ReferenceDateResult, generated_at: str) -> str:
    badge = {"PASS": "✅ PASS", "WARN": "⚠️ WARN", "FAIL": "❌ FAIL", "INFO": "ℹ️ INFO"}
    lines = [
        "# Olist 数据画像",
        "",
        f"> 由 `python -m data.profile_olist` 自动生成于 {generated_at}。请勿手工修改；数据变化后重新运行。",
        "",
        "## 数据版本",
        "",
        "| 表 | 文件 | 行数 | SHA-256 |",
        "| --- | --- | --- | --- |",
    ]
    source_dir = manifest[0][4] if manifest else "未知"
    if is_synthetic(source_dir):
        lines[2:2] = [
            "> ⚠️ **本报告基于合成样例数据生成**（数据目录中存在 `sample_truth.json`），"
            "只用于验证画像流程，不代表真实 Olist 数据。",
            "",
        ]
    for table, filename, sha, n, _src, _at in manifest:
        lines.append(f"| `ods.{table}` | `{filename}` | {n:,} | `{sha[:16]}…` |")
    lines += ["", f"数据目录：`{display_path(source_dir)}`", ""]

    lines += ["## 检查结果汇总", "", "| 编号 | 检查项 | 状态 | 结论 |", "| --- | --- | --- | --- |"]
    for c in checks:
        lines.append(f"| {c.id} | {c.title} | {badge[c.status]} | {c.summary} |")

    lines += ["", f"## REFERENCE_DATE：`{ref.reference_date.isoformat()}`", "",
              f"最后一个完整月为 **{ref.last_complete_month:%Y-%m}**。规则见 `docs/mvp_spec.md` §1.3"
              f"（之前 {ref.window} 个月中位数 × {ref.ratio}）。", ""]

    lines += ["## 对宽表设计的影响", ""]
    for c in checks:
        if c.impact and c.impact != "无。":
            lines.append(f"- **{c.id}**：{c.impact}")
    blocking = [c.id for c in checks if c.status == "FAIL"]
    lines += ["", ("**存在 FAIL 项（" + "、".join(blocking) + "），需要先修改宽表设计，再进行第 2 步。**")
              if blocking else "没有 FAIL 项，可以按 `docs/mvp_spec.md` §2 进行第 2 步。", ""]

    lines += ["## 检查明细", ""]
    for c in checks:
        lines += [f"### {c.id} {c.title}　{badge[c.status]}", "", c.summary, "",
                  f"**影响：** {c.impact}", ""]
        for t in c.tables:
            lines += [render_table(t), ""]
    return "\n".join(lines)


def run_profile(dsn: str) -> tuple[list[Check], ReferenceDateResult, list[tuple]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('ods._load_manifest')")
        if cur.fetchone()[0] is None:
            raise RuntimeError("没有找到导入清单 ods._load_manifest，请先运行 python -m data.load_olist")
        manifest = rows(cur, "SELECT * FROM ods._load_manifest ORDER BY table_name")
        checks = [check_p1(cur), check_p2(cur), check_p3(cur), check_p4(cur),
                  check_p5(cur), check_p6(cur), check_p7(cur)]
        p8, ref = check_p8(cur)
        checks += [p8, check_p9(cur), check_p10(cur)]
    return checks, ref, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Olist 数据画像")
    parser.add_argument("--dsn", default=None, help="数据库连接，默认 DATABASE_URL")
    parser.add_argument("--out", type=Path, default=REPORT_MD, help="Markdown 报告路径")
    parser.add_argument("--json", type=Path, default=RESULT_JSON, help="JSON 结果路径")
    parser.add_argument("--write-env", action="store_true", help="把 REFERENCE_DATE 写入 .env")
    args = parser.parse_args(argv)

    try:
        checks, ref, manifest = run_profile(args.dsn or database_url())
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(checks, manifest, ref, generated_at), encoding="utf-8")
    result = {
        "generated_at": generated_at,
        "reference_date": ref.reference_date.isoformat(),
        "last_complete_month": ref.last_complete_month.isoformat(),
        "manifest": [{"table": t, "file": f, "sha256": s, "rows": n} for t, f, s, n, _, _ in manifest],
        "checks": [asdict(c) for c in checks],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if manifest and is_synthetic(manifest[0][4]):
        print("注意：当前数据是合成样例数据，报告只用于验证流程。")
    for c in checks:
        print(f"  {c.id:<4} {c.status:<5} {c.title}")
    print(f"REFERENCE_DATE = {ref.reference_date.isoformat()}（最后一个完整月 {ref.last_complete_month:%Y-%m}）")
    if args.write_env:
        set_env_value("REFERENCE_DATE", ref.reference_date.isoformat())
        print("已写入 .env")
    print(f"报告：{args.out}")

    return 2 if any(c.status == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())