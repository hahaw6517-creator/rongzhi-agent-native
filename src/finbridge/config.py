"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str

    @property
    def api_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL") or os.getenv("BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL") or os.getenv("MODEL", "deepseek-chat"),
    )