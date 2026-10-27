"""把 Olist 原始 CSV 导入 ODS 层。

用法：
    python -m data.load_olist
    python -m data.load_olist --source 其他目录
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from common.config import PROJECT_ROOT, database_url, olist_raw_dir
from data.olist_schema import TABLES, TableSpec

MANIFEST_JSON = PROJECT_ROOT / "data" / "load_manifest.json"


class LoadError(Exception):
    pass


def read_header(path: Path) -> list[str]:
    # utf-8-sig 去掉部分文件开头的 BOM
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [h.strip() for h in next(csv.reader(f))]


def validate_sources(source: Path) -> dict[str, list[str]]:
    """返回 {表名: CSV 中的列顺序}；有问题时一次性列出全部问题。"""
    problems: list[str] = []
    headers: dict[str, list[str]] = {}
    for spec in TABLES:
        path = source / spec.filename
        if not path.exists():
            problems.append(f"缺少文件：{path}")
            continue
        header = read_header(path)
        expected = set(spec.column_names)
        if set(header) != expected:
            missing = sorted(expected - set(header))
            extra = sorted(set(header) - expected)
            problems.append(f"{spec.filename} 表头不符：缺少 {missing}，多出 {extra}")
            continue
        headers[spec.table] = header
    if problems:
        raise LoadError("\n".join(problems))
    return headers

def copy_table(cur: psycopg.Cursor, spec: TableSpec, path: Path, header: list[str]) -> int:
    cur.execute(f"DROP TABLE IF EXISTS ods.{spec.table}")
    cur.execute(spec.create_sql())
    # 按 CSV 中的实际列顺序指定列，表头顺序与定义不同时也能正确导入
    cols = ", ".join(header)
    with path.open("rb") as f, cur.copy(
        f"COPY ods.{spec.table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)"
    ) as copy:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            copy.write(chunk)
    cur.execute(f"SELECT count(*) FROM ods.{spec.table}")
    return cur.fetchone()[0]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(source: Path, dsn: str) -> dict:
    headers = validate_sources(source)
    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {"loaded_at": loaded_at, "source_dir": str(source), "tables": {}}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS ods")
        for spec in TABLES:
            path = source / spec.filename
            rows = copy_table(cur, spec, path, headers[spec.table])
            manifest["tables"][spec.table] = {
                "file": spec.filename,
                "sha256": sha256_of(path),
                "rows": rows,
            }
            print(f"  ods.{spec.table:<22} {rows:>9,} 行")

        cur.execute("DROP TABLE IF EXISTS ods._load_manifest")
        cur.execute(
            """CREATE TABLE ods._load_manifest (
                   table_name text PRIMARY KEY, filename text, sha256 text,
                   row_count bigint, source_dir text, loaded_at timestamptz)"""
        )
        for table, info in manifest["tables"].items():
            cur.execute(
                "INSERT INTO ods._load_manifest VALUES (%s, %s, %s, %s, %s, %s)",
                (table, info["file"], info["sha256"], info["rows"], str(source), loaded_at),
            )
        for spec in TABLES:
            cur.execute(f"ANALYZE ods.{spec.table}")
        conn.commit()

    MANIFEST_JSON.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入 Olist 原始 CSV 到 ODS 层")
    parser.add_argument("--source", type=Path, default=None, help="CSV 目录，默认 OLIST_RAW_DIR")
    parser.add_argument("--dsn", default=None, help="数据库连接，默认 DATABASE_URL")
    args = parser.parse_args(argv)

    source = (args.source or olist_raw_dir()).resolve()
    print(f"从 {source} 导入 ...")
    try:
        load(source, args.dsn or database_url())
    except LoadError as e:
        print(f"导入未开始，原因：\n{e}", file=sys.stderr)
        print("下载方式见 data/raw/README.md", file=sys.stderr)
        return 1
    print(f"完成。导入清单：{MANIFEST_JSON.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())