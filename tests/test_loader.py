from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from logisql.ingest.loader import (
    _clean_value,
    _prepare_frame,
    _records,
    load_olist_dataset,
)


def test_prepare_frame_renames_olist_typos_and_coerces_numbers() -> None:
    frame = pd.DataFrame(
        [
            {
                "product_id": "p1",
                "product_name_lenght": "42",
                "product_description_lenght": "100",
                "product_photos_qty": "2",
                "product_weight_g": None,
            }
        ]
    )
    cleaned = _prepare_frame("products", frame)
    assert "product_name_length" in cleaned.columns
    assert "product_name_lenght" not in cleaned.columns
    assert int(cleaned.iloc[0]["product_name_length"]) == 42

    records = _records(cleaned)
    assert records[0]["product_weight_g"] is None
    assert records[0]["product_name_length"] == 42


def test_prepare_frame_parses_timestamps() -> None:
    frame = pd.DataFrame(
        [
            {
                "order_id": "o1",
                "order_purchase_timestamp": "2018-01-01 10:00:00",
            }
        ]
    )
    cleaned = _prepare_frame("orders", frame)
    assert isinstance(cleaned.iloc[0]["order_purchase_timestamp"], pd.Timestamp)


def test_clean_value_converts_nan_to_none() -> None:
    assert _clean_value(float("nan")) is None
    assert _clean_value(None) is None
    assert _clean_value("value") == "value"


def test_loader_reports_missing_csv_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing Olist CSV"):
        load_olist_dataset(
            csv_dir=tmp_path,
            database_url="postgresql://user:pass@localhost:5432/db",
        )
