"""项目配置：从环境变量与 .env 读取。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sqlagent"
    )


def olist_raw_dir() -> Path:
    raw = Path(os.environ.get("OLIST_RAW_DIR", "data/raw"))
    return raw if raw.is_absolute() else PROJECT_ROOT / raw

def set_env_value(key: str, value: str, env_file: Path = ENV_FILE) -> None:
    """在 .env 中设置一个键的值；键不存在则追加，文件不存在则创建。"""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")