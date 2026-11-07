"""Настройки из переменных окружения и файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_BASE_URL = "https://ads.vk.com"


def load_dotenv(path: str | Path = ".env") -> None:
    """Минимальный парсер .env: KEY=VALUE, без перезаписи уже заданных переменных."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    agency_client_name: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    token_cache: Path = Path(".vkads_token.json")

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        env = os.environ.get
        return cls(
            client_id=env("VK_ADS_CLIENT_ID") or None,
            client_secret=env("VK_ADS_CLIENT_SECRET") or None,
            access_token=env("VK_ADS_ACCESS_TOKEN") or None,
            agency_client_name=env("VK_ADS_AGENCY_CLIENT_NAME") or None,
            base_url=(env("VK_ADS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            token_cache=Path(env("VK_ADS_TOKEN_CACHE") or ".vkads_token.json"),
        )
