"""端到端：生成合成数据 → 导入 → 画像，与生成器独立计算的期望结果逐项对照。

需要一个可以随意清空的测试数据库，通过 TEST_DATABASE_URL 指定；未设置时跳过。
测试会重建该库中的 ods 表。
"""

import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from data.load_olist import load
from data.make_sample_olist import generate
from data.profile_olist import run_profile

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="未设置 TEST_DATABASE_URL")

# 保险：测试会清空目标库的 ods 表，数据库名必须包含 test，防止误连正式库
if DSN and "test" not in conninfo_to_dict(DSN).get("dbname", ""):
    pytest.exit(
        f"TEST_DATABASE_URL 指向的数据库 {conninfo_to_dict(DSN).get('dbname')!r} 名字里没有 test，"
        "为防止清空正式数据，拒绝运行。",
        returncode=1,
    )


@pytest.fixture(scope="module")
def profiled(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample")
    truth = generate(out, seed=42)
    load(out, DSN)
    checks, ref, manifest = run_profile(DSN)
    return truth, {c.id: c for c in checks}, ref, manifest


def test_row_counts_match_source(profiled):
    truth, _, _, manifest = profiled
    loaded = {t: n for t, _f, _s, n, _src, _at in manifest}
    for table, n in truth["rows"].items():
        assert loaded[table] == n, table


def test_primary_keys(profiled):
    _, c, _, _ = profiled
    for cid in ("P1", "P2", "P3", "P4"):
        assert c[cid].status == "PASS", cid


def test_null_and_untranslated_categories(profiled):
    truth, c, _, _ = profiled
    assert c["P4"].metrics["products_null_category"] == truth["products_null_category"]
    assert sorted(r[0] for r in c["P5"].metrics["untranslated"]) == truth["untranslated_categories"]
    assert c["P5"].metrics["translation"]["duplicate_rows"] == 0


def test_review_issues_detected(profiled):
    truth, c, _, _ = profiled
    p6 = c["P6"]
    assert p6.status == "WARN"
    assert p6.metrics["review_id_pair"]["duplicate_rows"] == truth["duplicate_review_pairs"]
    assert p6.metrics["review_id_pair"]["null_keys"] == truth["null_review_id_rows"]
    assert p6.metrics["review_ids_in_multiple_orders"] == truth["review_ids_in_multiple_orders"]
    assert p6.metrics["null_scores"] == truth["null_scores"]
    assert "ods.order_reviews_dedup" in p6.impact


def test_statuses(profiled):
    truth, c, _, _ = profiled
    assert c["P7"].status == "PASS"
    assert sorted(s for s, _ in c["P7"].metrics["statuses"]) == truth["statuses"]


def test_reference_date(profiled):
    truth, c, ref, _ = profiled
    assert ref.reference_date.isoformat() == truth["expected_reference_date"]
    assert ref.last_complete_month.isoformat() == truth["expected_last_complete_month"]


def test_referential_integrity_and_expected_dws_rows(profiled):
    truth, c, _, _ = profiled
    p9 = c["P9"]
    assert p9.status == "WARN"
    assert p9.metrics["orphans"] == truth["orphans"]
    assert p9.metrics["expected_dws_order_item_rows"] == truth["expected_dws_order_item_rows"]
    assert p9.metrics["expected_dws_review_rows"] == truth["expected_dws_review_rows"]


def test_orders_without_items(profiled):
    truth, c, _, _ = profiled
    assert c["P10"].metrics["orders_without_items"] == truth["orders_without_items"]
    assert c["P10"].metrics["reviews_on_orders_without_items"] == truth["reviews_on_orders_without_items"]


def test_multiline_review_text_survives_copy(profiled):
    with psycopg.connect(DSN) as conn:
        n = conn.execute(
            "SELECT count(*) FROM ods.order_reviews WHERE review_comment_message LIKE '%' || chr(10) || '%'"
        ).fetchone()[0]
    assert n > 0
