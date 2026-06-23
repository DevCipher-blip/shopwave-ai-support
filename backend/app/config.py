from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings

PLACEHOLDER_KEYS = {"", "your_groq_api_key_here"}


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_provider: Literal["groq", "fake"] = "groq"
    stt_provider: Literal["groq", "fake"] = "groq"
    admin_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./shopwave.db"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    rebase_demo_dates: bool = True
    max_audio_bytes: int = 10 * 1024 * 1024

    data_dir: Path = Path(__file__).parent.parent.parent / "data"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # The async engine needs an async driver; accept plain sqlite URLs too.
        if not v:
            return "sqlite+aiosqlite:///./shopwave.db"
        if isinstance(v, str) and v.startswith("sqlite:///"):
            return v.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def has_groq_key(self) -> bool:
        return self.groq_api_key.strip() not in PLACEHOLDER_KEYS

    def check(self) -> None:
        """Fail at startup rather than on the first customer request."""
        needs_groq = "groq" in (self.llm_provider, self.stt_provider)
        if needs_groq and not self.has_groq_key:
            raise RuntimeError("GROQ_API_KEY must be set (or use the fake providers for a demo).")
        if self.admin_token and len(self.admin_token) < 16:
            raise RuntimeError("ADMIN_TOKEN must be at least 16 characters.")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
