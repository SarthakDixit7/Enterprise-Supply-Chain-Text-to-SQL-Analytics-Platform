from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Make optional observability/tooling variables in `.env` visible to libraries
# such as LangSmith, not just to pydantic-settings.
load_dotenv(override=False)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LogiSQL-Agent"
    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./data/logisql_demo.db"
    database_schema: str = "public"
    allowed_tables: str = "orders,order_items,products,sellers,order_payments"
    allow_demo_seed: bool = True

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0

    max_retries: int = Field(default=3, ge=0, le=5)
    default_row_limit: int = Field(default=200, ge=1, le=1000)
    max_row_limit: int = Field(default=1000, ge=1, le=10_000)
    query_timeout_ms: int = Field(default=15_000, ge=1_000, le=120_000)
    schema_cache_ttl_seconds: int = Field(default=300, ge=0)

    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    api_base_url: str = "http://localhost:8000"
    max_concurrent_queries: int = Field(default=4, ge=1, le=100)
    query_queue_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @field_validator("database_url")
    @classmethod
    def _strip_database_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test, or production")
        return normalized

    @property
    def allowed_table_set(self) -> frozenset[str]:
        return frozenset(
            table.strip().lower()
            for table in self.allowed_tables.split(",")
            if table.strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.strip())

    @property
    def sqlite_path(self) -> Path | None:
        if not self.is_sqlite:
            return None
        database = make_url(self.database_url).database
        # In-memory and URI-named databases have no file to seed or create.
        if not database or database == ":memory:" or database.startswith("file:"):
            return None
        return Path(database).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configure_logging(level: str | None = None) -> None:
    """Configure concise, timestamped application logging once."""

    resolved = (level or get_settings().log_level).upper()
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(resolved)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(resolved)

    # These tend to be noisy at INFO level in local development.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
