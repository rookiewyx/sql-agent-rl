"""semantic/models.py 的测试。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from data.build_dws import build
from semantic.models import ModelError, check_against_db, load_models, violates


def test_models_yaml_loads():
    assert set(load_models()) == {"order_item", "order_category", "review"}


def test_unknown_join_target_is_rejected(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text(
        "a:\n  table: dws.a\n  grain: x\n  primary_key: [id]\n"
        "  joins:\n    b:\n      keys: {id: id}\n      cardinality: one_to_one\n",
        encoding="utf-8",
    )
    with pytest.raises(ModelError, match="不存在"):
        load_models(path)


@pytest.mark.parametrize("declared, actual, bad", [
    ("one_to_many", "one_to_many", False),
    ("one_to_many", "one_to_one", False),     # 数据比声明更严格，不算错
    ("one_to_many", "many_to_many", True),
    ("many_to_one", "many_to_many", True),
    ("many_to_many", "one_to_one", False),
])
def test_violates(declared, actual, bad):
    assert violates(declared, actual) is bad


def test_declared_models_match_mini_db(ods, dsn):
    build(dsn)
    assert check_against_db(ods, load_models()) == []


def test_wrong_primary_key_is_reported(ods, dsn):
    build(dsn)
    models = load_models()
    models["review"] = replace(models["review"], primary_key=("review_id",))
    assert any("主键" in p for p in check_against_db(ods, models))


def test_second_review_on_same_order_breaks_one_to_many(ods, dsn):
    # o1 有两个类目；再给它加一条评价，关联就变成多对多
    ods.execute("INSERT INTO ods.order_reviews VALUES ('r3', 'o1', 4, '2018-01-15', '2018-01-16')")
    build(dsn)
    models = load_models()
    review = models["review"]
    # 测试自己声明 one_to_many，不依赖 YAML 里写的是什么
    models["review"] = replace(review, joins=(replace(review.joins[0], cardinality="one_to_many"),))
    problems = check_against_db(ods, models)
    assert any("review → order_category" in p and "many_to_many" in p for p in problems)