from __future__ import annotations

from logisql.agent.charts import build_chart, infer_chart_spec
from logisql.agent.llm import ChartSpec

ROWS = [
    {"order_status": "delivered", "order_count": 100},
    {"order_status": "shipped", "order_count": 12},
    {"order_status": "canceled", "order_count": 5},
]
COLUMNS = ["order_status", "order_count"]


def test_infers_bar_chart() -> None:
    spec = infer_chart_spec(columns=COLUMNS, rows=ROWS)
    assert spec is not None
    assert spec.type == "bar"
    assert spec.x == "order_status"
    assert spec.y == "order_count"


def test_infers_line_chart_for_temporal_data() -> None:
    rows = [
        {"month": "2018-01-01", "revenue": 100.0},
        {"month": "2018-02-01", "revenue": 125.0},
    ]
    spec = infer_chart_spec(columns=["month", "revenue"], rows=rows)
    assert spec is not None
    assert spec.type == "line"


def test_builds_plotly_json() -> None:
    chart, warning = build_chart(
        rows=ROWS,
        columns=COLUMNS,
        requested=ChartSpec(type="bar", x="order_status", y="order_count"),
    )
    assert warning is None
    assert chart is not None
    assert chart["data"][0]["type"] == "bar"
    assert chart["layout"]["title"]["text"].startswith("Order Count")


def test_builds_pie_chart() -> None:
    chart, warning = build_chart(
        rows=ROWS,
        columns=COLUMNS,
        requested=ChartSpec(type="pie", x="order_status", y="order_count"),
    )
    assert warning is None
    assert chart is not None
    assert chart["data"][0]["type"] == "pie"


def test_invalid_chart_falls_back_to_inferred_chart() -> None:
    chart, warning = build_chart(
        rows=ROWS,
        columns=COLUMNS,
        requested=ChartSpec(type="line", x="missing", y="order_count"),
    )
    assert chart is not None
    assert warning is not None
    assert "not in the result" in warning


def test_no_rows_returns_no_chart() -> None:
    chart, warning = build_chart(rows=[], columns=COLUMNS, requested=None)
    assert chart is None
    assert warning is None
