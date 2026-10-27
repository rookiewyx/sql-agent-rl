"""生成与 Olist 结构一致的合成样例数据，用于在没有真实数据时验证导入与画像流程。

合成数据有意埋入已知的数据问题，并在 Python 中独立计算每项检查的期望结果
（写入 sample_truth.json），测试会用它与画像脚本的 SQL 结果对照。

合成数据只用于测试流水线，不用于任何准确率评测。

用法：
    python -m data.make_sample_olist                      # 输出到 data/sample_synthetic/
    python -m data.make_sample_olist --out /some/dir --seed 7
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from common.config import PROJECT_ROOT
from data.olist_schema import TABLES_BY_NAME
from data.reference_date import add_months

DEFAULT_OUT = PROJECT_ROOT / "data" / "sample_synthetic"

CATEGORIES = {
    "beleza_saude": "health_beauty",
    "informatica_acessorios": "computers_accessories",
    "esporte_lazer": "sports_leisure",
    "moveis_decoracao": "furniture_decor",
    "utilidades_domesticas": "housewares",
    "relogios_presentes": "watches_gifts",
    "telefonia": "telephony",
    "brinquedos": "toys",
    "eletronicos": "electronics",
    "automotivo": "auto",
    "cama_mesa_banho": "bed_bath_table",
    "perfumaria": "perfumery",
    "bebes": "baby",
    "papelaria": "stationery",
    "pet_shop": "pet_shop",
    "ferramentas_jardim": "garden_tools",
    "cool_stuff": "cool_stuff",
    "fashion_bolsas_e_acessorios": "fashion_bags_accessories",
}
UNTRANSLATED = ["pc_gamer", "portateis_cozinha_e_preparadores_de_alimentos"]
STATES = ["SP"] * 6 + ["RJ"] * 2 + ["MG"] * 2 + ["RS", "PR", "SC", "BA"]
STATUSES = ["delivered"] * 90 + ["shipped"] * 3 + ["canceled"] * 2 + ["unavailable"] * 1 + \
           ["invoiced"] * 2 + ["processing"] * 2

# 埋入的问题规模
N_PRODUCTS = 300
N_SELLERS = 80
N_NULL_CATEGORY_PRODUCTS = 6
N_ORPHAN_PRODUCT_ITEMS = 3
N_ORPHAN_SELLER_ITEMS = 2
N_ORPHAN_CUSTOMER_ORDERS = 1
N_REUSED_REVIEW_IDS = 20
N_DUPLICATE_REVIEW_PAIRS = 7
N_NULL_SCORES = 4
N_NULL_REVIEW_IDS = 1


def hexid(rng: random.Random) -> str:
    return uuid.UUID(int=rng.getrandbits(128)).hex


def ts(d: datetime | None) -> str:
    return "" if d is None else d.strftime("%Y-%m-%d %H:%M:%S")


def month_plan() -> list[tuple[date, int]]:
    """每月订单数：首月零星、中间逐步增长、末尾两个月零星（模拟数据截断）。"""
    plan = [(date(2016, 9, 1), 3)]
    m, n = date(2016, 10, 1), 30
    while m <= date(2018, 8, 1):
        plan.append((m, n))
        m, n = add_months(m, 1), min(n + 5, 150)
    plan += [(date(2018, 9, 1), 6), (date(2018, 10, 1), 2)]
    return plan


def generate(out: Path, seed: int = 42) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    # 商品与卖家
    cat_pool = list(CATEGORIES) + UNTRANSLATED
    products = []
    for i in range(N_PRODUCTS):
        cat = None if i < N_NULL_CATEGORY_PRODUCTS else rng.choice(cat_pool)
        products.append({"product_id": hexid(rng), "product_category_name": cat})
    sellers = [{"seller_id": hexid(rng), "seller_state": rng.choice(STATES)} for _ in range(N_SELLERS)]

    orders, customers, items, payments, reviews = [], [], [], [], []
    for month, n_orders in month_plan():
        next_month = add_months(month, 1)
        span = (datetime.combine(next_month, datetime.min.time())
                - datetime.combine(month, datetime.min.time())).total_seconds()
        for _ in range(n_orders):
            purchase = datetime.combine(month, datetime.min.time()) + timedelta(seconds=rng.randrange(int(span)))
            status = rng.choice(STATUSES)
            cust = {"customer_id": hexid(rng), "customer_unique_id": hexid(rng),
                    "customer_state": rng.choice(STATES)}
            customers.append(cust)
            delivered = purchase + timedelta(days=rng.randint(3, 20)) if status == "delivered" else None
            orders.append({"order_id": hexid(rng), "customer_id": cust["customer_id"],
                           "order_status": status, "purchase": purchase, "delivered": delivered})

    # 没有明细的订单：全部 unavailable，以及一半 canceled
    no_item_orders = set()
    for o in orders:
        if o["order_status"] == "unavailable" or (o["order_status"] == "canceled" and rng.random() < 0.5):
            no_item_orders.add(o["order_id"])

    for o in orders:
        if o["order_id"] in no_item_orders:
            continue
        n_items = rng.choices([1, 2, 3, 4], weights=[70, 20, 7, 3])[0]
        total = 0.0
        for k in range(1, n_items + 1):
            price = round(rng.uniform(10, 500), 2)
            freight = round(rng.uniform(5, 40), 2)
            total += price + freight
            items.append({"order_id": o["order_id"], "order_item_id": k,
                          "product_id": rng.choice(products)["product_id"],
                          "seller_id": rng.choice(sellers)["seller_id"],
                          "shipping": o["purchase"] + timedelta(days=3), "price": price, "freight": freight})
        payments.append({"order_id": o["order_id"], "value": round(total, 2)})

    # 埋入：明细引用不存在的商品 / 卖家；订单引用不存在的客户
    for it in rng.sample(items, N_ORPHAN_PRODUCT_ITEMS):
        it["product_id"] = "missing_product_" + hexid(rng)[:8]
    for it in rng.sample([i for i in items if not i["product_id"].startswith("missing_")], N_ORPHAN_SELLER_ITEMS):
        it["seller_id"] = "missing_seller_" + hexid(rng)[:8]
    orphan_customer_orders = rng.sample([o for o in orders if o["order_id"] not in no_item_orders],
                                        N_ORPHAN_CUSTOMER_ORDERS)
    orphan_customer_ids = {o["customer_id"] for o in orphan_customer_orders}
    customers = [c for c in customers if c["customer_id"] not in orphan_customer_ids]

    # 评价：约 95% 的订单有一条评价，约 1.5% 的订单有第二条
    for o in orders:
        n_rev = 0 if rng.random() > 0.95 else (2 if rng.random() < 0.015 else 1)
        for _ in range(n_rev):
            created = o["purchase"] + timedelta(days=rng.randint(5, 25))
            reviews.append({"review_id": hexid(rng), "order_id": o["order_id"],
                            "score": rng.choices([1, 2, 3, 4, 5], weights=[10, 3, 8, 19, 60])[0],
                            "created": created.replace(hour=0, minute=0, second=0),
                            "answered": created + timedelta(days=1, hours=rng.randint(0, 20))})

    # 埋入：同一个 review_id 出现在两笔不同的订单上
    singles = [r for r in reviews]
    rng.shuffle(singles)
    reused = 0
    used_orders = set()
    for a, b in zip(singles[0::2], singles[1::2]):
        if reused >= N_REUSED_REVIEW_IDS:
            break
        if a["order_id"] == b["order_id"] or a["order_id"] in used_orders or b["order_id"] in used_orders:
            continue
        b["review_id"] = a["review_id"]
        used_orders |= {a["order_id"], b["order_id"]}
        reused += 1

    # 埋入：评分为空
    for r in rng.sample(reviews, N_NULL_SCORES):
        r["score"] = None

    # 埋入：完全重复的 (review_id, order_id)，回复时间不同
    dup_sources = rng.sample([r for r in reviews if r["order_id"] not in used_orders], N_DUPLICATE_REVIEW_PAIRS)
    for r in dup_sources:
        reviews.append({**r, "answered": r["answered"] + timedelta(days=1)})

    # 埋入：review_id 为空的评价（检验唯一性检查对空键的处理）
    for r in rng.sample([r for r in reviews if r["order_id"] not in used_orders], N_NULL_REVIEW_IDS):
        reviews.append({**r, "review_id": None})

    # ---------------------------------------------------------------- 写 CSV
    def write(table: str, rows: list[list], bom: bool = False) -> None:
        spec = TABLES_BY_NAME[table]
        with (out / spec.filename).open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(spec.column_names)
            w.writerows(rows)

    write("orders", [[o["order_id"], o["customer_id"], o["order_status"], ts(o["purchase"]),
                      ts(o["purchase"] + timedelta(hours=1)), "", ts(o["delivered"]),
                      ts(o["purchase"] + timedelta(days=25))] for o in orders])
    write("order_items", [[i["order_id"], i["order_item_id"], i["product_id"], i["seller_id"],
                           ts(i["shipping"]), f"{i['price']:.2f}", f"{i['freight']:.2f}"] for i in items])
    write("order_payments", [[p["order_id"], 1, "credit_card", 1, f"{p['value']:.2f}"] for p in payments])
    write("order_reviews", [["" if r["review_id"] is None else r["review_id"], r["order_id"], "" if r["score"] is None else r["score"],
                             "", "Produto chegou, obrigado.\nRecomendo." if r["score"] == 5 else "",
                             ts(r["created"]), ts(r["answered"])] for r in reviews])
    write("customers", [[c["customer_id"], c["customer_unique_id"], "01001", "sao paulo",
                         c["customer_state"]] for c in customers])
    write("products", [[p["product_id"], p["product_category_name"] or "", 40, 300, 1, 500, 20, 10, 15]
                       for p in products])
    write("sellers", [[s["seller_id"], "01001", "sao paulo", s["seller_state"]] for s in sellers])
    write("category_translation", [[pt, en] for pt, en in CATEGORIES.items()], bom=True)

    # ---------------------------------------------------------------- 独立计算期望结果
    order_ids = {o["order_id"] for o in orders}
    customer_ids = {c["customer_id"] for c in customers}
    product_ids = {p["product_id"] for p in products}
    seller_ids = {s["seller_id"] for s in sellers}
    order_by_id = {o["order_id"]: o for o in orders}
    item_order_ids = {i["order_id"] for i in items}
    used_categories = {p["product_category_name"] for p in products if p["product_category_name"]}

    expected_items = sum(
        1 for i in items
        if i["order_id"] in order_ids and order_by_id[i["order_id"]]["customer_id"] in customer_ids
        and i["product_id"] in product_ids and i["seller_id"] in seller_ids
    )
    expected_reviews = len({
        (r["review_id"], r["order_id"]) for r in reviews
        if r["review_id"] is not None and order_by_id[r["order_id"]]["customer_id"] in customer_ids
    })
    truth = {
        "seed": seed,
        "rows": {"orders": len(orders), "order_items": len(items), "order_reviews": len(reviews),
                 "customers": len(customers), "products": len(products), "sellers": len(sellers)},
        "products_null_category": N_NULL_CATEGORY_PRODUCTS,
        "untranslated_categories": sorted(c for c in UNTRANSLATED if c in used_categories),
        "review_ids_in_multiple_orders": reused,
        "duplicate_review_pairs": N_DUPLICATE_REVIEW_PAIRS,
        "null_review_id_rows": N_NULL_REVIEW_IDS,
        "null_scores": N_NULL_SCORES,
        "orphans": {
            "明细的 order_id 不在订单表": 0,
            "订单的 customer_id 不在客户表": N_ORPHAN_CUSTOMER_ORDERS,
            "明细的 product_id 不在商品表": N_ORPHAN_PRODUCT_ITEMS,
            "明细的 seller_id 不在卖家表": N_ORPHAN_SELLER_ITEMS,
            "评价的 order_id 不在订单表": 0,
        },
        "orders_without_items": len(order_ids - item_order_ids),
        "reviews_on_orders_without_items": sum(1 for r in reviews if r["order_id"] not in item_order_ids),
        "expected_dws_order_item_rows": expected_items,
        "expected_dws_review_rows": expected_reviews,
        "statuses": sorted({o["order_status"] for o in orders}),
        "expected_reference_date": "2018-09-01",
        "expected_last_complete_month": "2018-08-01",
    }
    (out / "sample_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "README.md").write_text(
        "# 合成样例数据\n\n由 `python -m data.make_sample_olist` 生成，结构与 Olist 一致，"
        "有意埋入已知的数据问题，仅用于测试导入与画像流程，**不是真实数据，不能用于任何评测**。\n"
        "`sample_truth.json` 记录了埋入的问题与各项检查的期望结果。\n",
        encoding="utf-8",
    )
    return truth


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Olist 结构的合成样例数据")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    truth = generate(args.out, args.seed)
    print(f"已生成到 {args.out}：" + "，".join(f"{k} {v:,}" for k, v in truth["rows"].items()))


if __name__ == "__main__":
    main()
