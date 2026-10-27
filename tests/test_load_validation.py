"""导入前的文件校验：不需要数据库。"""

import pytest

from data.load_olist import LoadError, read_header, validate_sources
from data.make_sample_olist import generate
from data.olist_schema import TABLES_BY_NAME


@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample")
    generate(out, seed=1)
    return out


def test_valid_sample_passes(sample_dir):
    headers = validate_sources(sample_dir)
    assert set(headers) == set(TABLES_BY_NAME)


def test_bom_is_stripped_from_header(sample_dir):
    # 合成数据的翻译表带 BOM，与部分真实文件一致
    spec = TABLES_BY_NAME["category_translation"]
    raw = (sample_dir / spec.filename).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert read_header(sample_dir / spec.filename) == spec.column_names


def test_missing_file_is_reported(tmp_path, sample_dir):
    for f in sample_dir.glob("*.csv"):
        if f.name != "olist_orders_dataset.csv":
            (tmp_path / f.name).write_bytes(f.read_bytes())
    with pytest.raises(LoadError, match="缺少文件.*olist_orders_dataset.csv"):
        validate_sources(tmp_path)


def test_header_mismatch_is_reported(tmp_path, sample_dir):
    for f in sample_dir.glob("*.csv"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    path = tmp_path / "olist_sellers_dataset.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("seller_state", "seller_uf")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LoadError, match=r"olist_sellers_dataset.csv 表头不符：缺少 \['seller_state'\]"):
        validate_sources(tmp_path)


def test_reordered_columns_are_accepted(tmp_path, sample_dir):
    for f in sample_dir.glob("*.csv"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    path = tmp_path / "olist_sellers_dataset.csv"
    import csv
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    rows = [list(reversed(r)) for r in rows]
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    headers = validate_sources(tmp_path)
    assert headers["sellers"] == list(reversed(TABLES_BY_NAME["sellers"].column_names))
