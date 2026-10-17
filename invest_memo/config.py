"""환경변수(.env) 기반 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_LLM_MODEL = "claude-sonnet-5-5"


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    dart_api_key: str | None = None
    ecos_api_key: str | None = None
    fred_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_model: str = DEFAULT_LLM_MODEL
    cache_dir: Path = Path(".cache")
    cache_ttl_seconds: int = 24 * 3600


def load_settings(env_file: str | None = None) -> Settings:
    """`.env` 를 읽고(이미 설정된 환경변수는 유지) Settings 를 만든다."""
    load_dotenv(env_file, override=False)
    return Settings(
        dart_api_key=_env("DART_API_KEY"),
        ecos_api_key=_env("ECOS_API_KEY"),
        fred_api_key=_env("FRED_API_KEY"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        llm_model=_env("LLM_MODEL") or DEFAULT_LLM_MODEL,
    )
