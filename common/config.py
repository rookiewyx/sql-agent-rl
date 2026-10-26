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