"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / "config" / ".env"


def _getenv_optional(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value if value else None


@dataclass(frozen=True)
class AppSettings:
    """Runtime settings loaded from environment and config/.env."""

    storage_path: str = "data/graph"
    llm_provider: str = "openai"
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_api_base: Optional[str] = None


def load_settings(env_path: str | Path = DEFAULT_ENV_PATH) -> AppSettings:
    """Load settings from config/.env and process environment variables."""

    load_dotenv(env_path, override=False, encoding="utf-8-sig")
    storage_path = Path(os.getenv("STORAGE_PATH", "data/graph"))
    if not storage_path.is_absolute():
        storage_path = PROJECT_ROOT / storage_path
    llm_provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    is_ollama = llm_provider in {"ollama", "local"}
    default_model = "llama3.1" if is_ollama else "gpt-4o-mini"
    llm_model = _getenv_optional("LLM_MODEL")
    if not llm_model and is_ollama:
        llm_model = _getenv_optional("OLLAMA_MODEL")
    llm_api_base = _getenv_optional("LLM_API_BASE") or _getenv_optional("OPENAI_API_BASE")
    if not llm_api_base and is_ollama:
        llm_api_base = _getenv_optional("OLLAMA_BASE_URL")

    return AppSettings(
        storage_path=str(storage_path),
        llm_provider=llm_provider,
        llm_api_key=_getenv_optional("LLM_API_KEY") or _getenv_optional("OPENAI_API_KEY"),
        llm_model=llm_model or default_model,
        llm_api_base=llm_api_base,
    )
