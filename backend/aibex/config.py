"""Runtime configuration from environment variables (and a repo-root .env in development)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

LLM_PROVIDERS = ("openai", "fake")


def _env(name: str, default: str):
    """Default factory: read the variable when a Settings object is created, not at import time."""
    return field(default_factory=lambda: os.getenv(name) or default)


def _default_data_dir() -> Path:
    return Path(os.getenv("AIBEX_DATA_DIR") or REPO_ROOT / "data")


def _default_frontend_dist() -> Path:
    return Path(os.getenv("AIBEX_FRONTEND_DIST") or REPO_ROOT / "frontend" / "dist")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    frontend_dist: Path = field(default_factory=_default_frontend_dist)
    llm_base_url: str = _env("LLM_BASE_URL", "https://llm.ai.e-infra.cz/v1")
    llm_api_key: str = _env("LLM_API_KEY", "")
    llm_model_fast: str = _env("LLM_MODEL_FAST", "agentic")
    llm_model_code: str = _env("LLM_MODEL_CODE", "coder")
    llm_provider: str = _env("LLM_PROVIDER", "openai")

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "frontend_dist", Path(self.frontend_dist))
        provider = (self.llm_provider or "openai").strip().lower()
        if provider not in LLM_PROVIDERS:
            raise ValueError(f"LLM_PROVIDER must be one of {LLM_PROVIDERS}, got {self.llm_provider!r}")
        object.__setattr__(self, "llm_provider", provider)

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "fake" or bool(self.llm_api_key)


settings = Settings()
