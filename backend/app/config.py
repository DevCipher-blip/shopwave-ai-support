from pydantic_settings import BaseSettings
from pydantic import field_validator
from pathlib import Path


class Settings(BaseSettings):
    groq_api_key: str
    database_url: str = "sqlite+aiosqlite:///./shopwave.db"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Paths
    data_dir: Path = Path(__file__).parent.parent.parent / "data"

    @field_validator("groq_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v or v == "your_groq_api_key_here":
            raise ValueError("GROQ_API_KEY must be set in .env")
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # Uvicorn/SQLAlchemy async engine requires an async DB driver.
        # Normalize common sync sqlite URLs from env files.
        if not v:
            return "sqlite+aiosqlite:///./shopwave.db"
        if isinstance(v, str) and v.startswith("sqlite:///") and not v.startswith("sqlite+aiosqlite:///"):
            return v.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
