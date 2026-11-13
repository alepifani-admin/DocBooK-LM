"""Configurazione di DocBooK LM, letta da .env con prefisso DOCBOOKLM_."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Impostazioni del servizio. Ogni campo e' sovrascrivibile da ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="DOCBOOKLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8078

    router_url: str = "http://127.0.0.1:8080"
    default_model: str = "Qwen3.5-9B-UD-Q4_K_XL"

    data_dir: Path = Path("data")
    max_upload_mb: int = 20

    ocr_enabled: bool = True
    allow_private_urls: bool = False

    max_tokens: int = 1200
    temperature: float = 0.2
    top_p: float = 0.9
    history_turns: int = 4
    thinking: bool = False

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "docbook.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.files_dir, self.pages_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
