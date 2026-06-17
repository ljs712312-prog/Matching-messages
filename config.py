from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
EXAMPLE_ENV_PATH = BASE_DIR / ".env.example"
ENV_PATHS = (WORKSPACE_DIR / ".env", BASE_DIR / ".env")


def load_env_files(override: bool = True) -> None:
    load_dotenv(EXAMPLE_ENV_PATH, override=False)
    for env_path in ENV_PATHS:
        load_dotenv(env_path, override=override)


load_env_files()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


OFFICE_PASSWORD = os.getenv("OFFICE_PASSWORD", "1234")
DEFAULT_COURT = os.getenv("DEFAULT_COURT", "수원")
DEFAULT_YEAR = _as_int(os.getenv("DEFAULT_YEAR"), 2026)
LOOKUP_ENABLED = _as_bool(os.getenv("LOOKUP_ENABLED"), False)
HEADLESS = _as_bool(os.getenv("HEADLESS"), True)
LOOKUP_DELAY_MIN = _as_float(os.getenv("LOOKUP_DELAY_MIN"), 0.8)
LOOKUP_DELAY_MAX = _as_float(os.getenv("LOOKUP_DELAY_MAX"), 1.8)
