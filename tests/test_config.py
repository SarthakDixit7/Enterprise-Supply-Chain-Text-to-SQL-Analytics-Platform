from __future__ import annotations

from pathlib import Path

from logisql.config import Settings
from logisql.db.engine import async_database_url
from logisql.db.seed import ensure_demo_database


def test_sqlite_path_resolves_relative_file() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///./data/demo.db")
    assert settings.sqlite_path == (Path.cwd() / "data" / "demo.db").resolve()


def test_sqlite_path_is_none_for_memory_database() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    assert settings.sqlite_path is None


def test_sqlite_path_is_none_for_postgres() -> None:
    settings = Settings(database_url="postgresql://user:pass@localhost:5432/db")
    assert settings.sqlite_path is None


def test_memory_database_skips_demo_seed() -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        allow_demo_seed=True,
    )
    assert ensure_demo_database(settings) is None


def test_database_url_is_trimmed() -> None:
    settings = Settings(database_url="  sqlite+aiosqlite:///./x.db  ")
    assert settings.database_url == "sqlite+aiosqlite:///./x.db"


def test_async_database_url_normalizes_postgres() -> None:
    assert (
        async_database_url("postgres://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert (
        async_database_url("postgresql://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert (
        async_database_url("postgresql+psycopg://u:p@host:5432/db")
        == "postgresql+psycopg://u:p@host:5432/db"
    )
    assert (
        async_database_url("sqlite+aiosqlite:///./demo.db")
        == "sqlite+aiosqlite:///./demo.db"
    )


def test_allowed_tables_are_normalized() -> None:
    settings = Settings(allowed_tables=" Orders , order_items ,, ")
    assert settings.allowed_table_set == frozenset({"orders", "order_items"})


def test_cors_origins_are_split_and_trimmed() -> None:
    settings = Settings(cors_origins="http://a, http://b ,,")
    assert settings.cors_origin_list == ["http://a", "http://b"]


def test_llm_configuration_ignores_whitespace_key() -> None:
    assert Settings(groq_api_key="   ").llm_configured is False
    assert Settings(groq_api_key="gsk_test").llm_configured is True
