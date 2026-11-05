from __future__ import annotations

from pathlib import Path

from logisql.db.seed import seed_demo_database


def test_seed_returns_all_table_counts(tmp_path: Path) -> None:
    database_path = tmp_path / "seed.db"
    counts = seed_demo_database(database_path, order_count=20, force=True)
    assert counts["orders"] == 20
    assert counts["sellers"] == 40
    assert counts["products"] == 160
    assert counts["order_items"] > 0
    assert counts["order_payments"] >= 20


def test_seed_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "seed.db"
    first = seed_demo_database(database_path, order_count=20, force=True)
    second = seed_demo_database(database_path, order_count=20)
    assert second == first
