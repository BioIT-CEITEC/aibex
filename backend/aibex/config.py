"""Runtime configuration from environment variables (and a repo-root .env in development)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("AIBEX_DATA_DIR", str(REPO_ROOT / "data")))
    frontend_dist: Path = Path(os.getenv("AIBEX_FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist")))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://llm.ai.e-infra.cz/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model_fast: str = os.getenv("LLM_MODEL_FAST", "agentic")
    llm_model_code: str = os.getenv("LLM_MODEL_CODE", "coder")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
