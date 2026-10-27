"""语义层模型：读取 models.yaml，并对照数据库核对。

用法：
    python -m semantic.models
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
import yaml
from psycopg import sql

from common.config import PROJECT_ROOT, database_url

MODELS_YAML = PROJECT_ROOT / "semantic" / "models.yaml"
CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}


class ModelError(Exception):
    pass


@dataclass(frozen=True)
class Join:
    target: str
    keys: dict[str, str]
    cardinality: str


@dataclass(frozen=True)
class Model:
    name: str
    table: str
    grain: str
    primary_key: tuple[str, ...]
    joins: tuple[Join, ...] = ()


# ---------- 加载：只检查结构，不连数据库 ----------

def load_models(path: Path = MODELS_YAML) -> dict[str, Model]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    models: dict[str, Model] = {}
    for name, spec in raw.items():
        missing = [k for k in ("table", "grain", "primary_key") if not (spec or {}).get(k)]
        if missing:
            problems.append(f"{name}：缺少 {missing}")
            continue
        joins = []
        for target, j in (spec.get("joins") or {}).items():
            if j.get("cardinality") not in CARDINALITIES:
                problems.append(f"{name} → {target}：cardinality 必须是 {sorted(CARDINALITIES)} 之一")
            if not j.get("keys"):
                problems.append(f"{name} → {target}：缺少 keys")
            joins.append(Join(target, dict(j.get("keys") or {}), j.get("cardinality", "")))
        models[name] = Model(name, spec["table"], spec["grain"],
                             tuple(spec["primary_key"]), tuple(joins))
    for m in models.values():
        for j in m.joins:
            if j.target not in models:
                problems.append(f"{m.name} → {j.target}：关联的模型不存在")
    if problems:
        raise ModelError("\n".join(problems))
    return models


# ---------- 核对：用数据检验声明 ----------

PK_SQL = """
SELECT a.attname
FROM pg_index i
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
WHERE i.indrelid = %s::regclass AND i.indisprimary
"""


def _ident(table: str) -> sql.Identifier:
    return sql.Identifier(*table.split("."))   # "dws.review" → "dws"."review"


def _max_matches(conn: psycopg.Connection, src: Model, dst: Model, keys: dict[str, str]) -> int:
    """src 的一行，最多能匹配 dst 的多少行。"""
    on = sql.SQL(" AND ").join(
        sql.SQL("s.{} = d.{}").format(sql.Identifier(a), sql.Identifier(b)) for a, b in keys.items()
    )
    group = sql.SQL(", ").join(sql.SQL("s.{}").format(sql.Identifier(c)) for c in src.primary_key)
    query = sql.SQL(
        "SELECT COALESCE(MAX(n), 0) FROM ("
        "  SELECT COUNT(*) AS n FROM {src} s JOIN {dst} d ON {on} GROUP BY {group}"
        ") x"
    ).format(src=_ident(src.table), dst=_ident(dst.table), on=on, group=group)
    return conn.execute(query).fetchone()[0]


def actual_cardinality(left_max: int, right_max: int) -> str:
    left = "one" if right_max <= 1 else "many"    # 右侧每行最多对应 1 个左侧行 → 左侧是 one
    right = "one" if left_max <= 1 else "many"
    return f"{left}_to_{right}"


def violates(declared: str, actual: str) -> bool:
    """声明为 one 的一侧，数据里出现了 many，才算违反；数据比声明更严格不算错。"""
    d_left, _, d_right = declared.split("_")
    a_left, _, a_right = actual.split("_")
    return (d_left == "one" and a_left == "many") or (d_right == "one" and a_right == "many")


def check_against_db(conn: psycopg.Connection, models: dict[str, Model]) -> list[str]:
    problems: list[str] = []
    for m in models.values():
        if conn.execute("SELECT to_regclass(%s)", [m.table]).fetchone()[0] is None:
            problems.append(f"{m.name}：表 {m.table} 不存在")
            continue
        pk = {row[0] for row in conn.execute(PK_SQL, [m.table])}
        if pk != set(m.primary_key):
            problems.append(f"{m.name}：主键声明为 {list(m.primary_key)}，数据库里是 {sorted(pk)}")
    if problems:
        return problems   # 表或主键不对，关联检查就没有意义了

    for m in models.values():
        for j in m.joins:
            dst = models[j.target]
            left_max = _max_matches(conn, m, dst, j.keys)
            right_max = _max_matches(conn, dst, m, {b: a for a, b in j.keys.items()})
            actual = actual_cardinality(left_max, right_max)
            if violates(j.cardinality, actual):
                problems.append(
                    f"{m.name} → {j.target}：声明为 {j.cardinality}，数据里是 {actual}"
                    f"（左表一行最多匹配 {left_max} 行，右表一行最多匹配 {right_max} 行）"
                )
    return problems


def main() -> int:
    try:
        models = load_models()
        with psycopg.connect(database_url()) as conn:
            problems = check_against_db(conn, models)
    except (ModelError, psycopg.Error) as e:
        print(f"核对失败：{e}", file=sys.stderr)
        return 1
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        return 1
    print(f"[OK] {len(models)} 个模型与数据库一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())