"""Application configuration, loaded from env / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "vidpack"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    youtube_api_key: str = ""
    groq_api_key: str = ""
    youtube_quota_daily_limit: int = 10000

    db_path: str = str(BASE_DIR / "data" / "vidpack.db")

    research_max_videos: int = 30

    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 60.0
    groq_api_key_2: str = ""
    groq_api_key_3: str = ""

    @property
    def has_youtube_key(self) -> bool:
        return bool(self.youtube_api_key.strip())

    @property
    def has_groq_key(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def groq_keys(self) -> list[str]:
        """All configured Groq keys, priority order, de-duplicated."""
        return list(
            dict.fromkeys(
                k.strip()
                for k in [self.groq_api_key, self.groq_api_key_2, self.groq_api_key_3]
                if k.strip()
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
