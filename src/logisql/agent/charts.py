from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import plotly.graph_objects as go

from logisql.agent.llm import ChartSpec

_PALETTE = [
    "#0f766e",
    "#f97316",
    "#2563eb",
    "#db2777",
    "#ca8a04",
    "#7c3aed",
    "#0891b2",
    "#dc2626",
]

# Numeric-looking columns that are usually identifiers or ordinals, not
# measures. Charting them produces noise such as "Rank by category".
_NON_MEASURE_NAMES = {
    "id",
    "index",
    "position",
    "rank",
    "rn",
    "row_number",
    "year",
    "month",
    "day",
}
_NON_MEASURE_SUFFIXES = ("_id", "_key", "_rank", "_index", "_position")
_MEASURE_HINTS = (
    "amount",
    "avg",
    "cost",
    "count",
    "freight",
    "items",
    "mean",
    "orders",
    "pct",
    "percent",
    "price",
    "profit",
    "qty",
    "quantity",
    "rate",
    "revenue",
    "sales",
    "score",
    "share",
    "sum",
    "total",
    "value",
    "volume",
    "weight",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_column(rows: list[dict[str, Any]], column: str) -> bool:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    return bool(values) and all(_is_number(value) for value in values)


def _measure_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    """Order numeric columns so real measures beat ids, ranks, and ordinals."""

    order = {column: index for index, column in enumerate(columns)}
    numeric = [column for column in columns if _is_numeric_column(rows, column)]

    def score(column: str) -> int:
        name = column.lower()
        value = 0
        if name in _NON_MEASURE_NAMES or name.endswith(_NON_MEASURE_SUFFIXES):
            value -= 100
        if any(hint in name for hint in _MEASURE_HINTS):
            value += 10
        return value

    return sorted(numeric, key=lambda column: (-score(column), order[column]))



def _is_temporal_column(rows: list[dict[str, Any]], column: str) -> bool:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    if not values:
        return False
    if all(isinstance(value, (datetime, date)) for value in values):
        return True
    if not all(isinstance(value, str) for value in values):
        return False
    sample = values[0]
    return bool(
        len(sample) >= 10
        and sample[4:5] == "-"
        and sample[7:8] == "-"
        and sample[:4].isdigit()
    )


def infer_chart_spec(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> ChartSpec | None:
    if not rows or not columns:
        return None

    numeric = _measure_columns(columns=columns, rows=rows)
    temporal = [column for column in columns if _is_temporal_column(rows, column)]
    categorical = [column for column in columns if column not in numeric and column not in temporal]

    if temporal and numeric:
        return ChartSpec(
            type="line",
            x=temporal[0],
            y=numeric[0],
            title=f"{numeric[0].replace('_', ' ').title()} over {temporal[0].replace('_', ' ')}",
        )
    if categorical and numeric and len(rows) <= 60:
        return ChartSpec(
            type="bar",
            x=categorical[0],
            y=numeric[0],
            title=f"{numeric[0].replace('_', ' ').title()} by {categorical[0].replace('_', ' ')}",
        )
    return None


def _validated_spec(
    requested: ChartSpec | None,
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> tuple[ChartSpec | None, str | None]:
    if requested is None or requested.type == "none":
        return infer_chart_spec(columns=columns, rows=rows), None

    if requested.x not in columns or requested.y not in columns:
        return (
            infer_chart_spec(columns=columns, rows=rows),
            "The model proposed a chart with columns that were not in the result; "
            "an automatic chart was used instead.",
        )
    if not _is_numeric_column(rows, requested.y):
        return (
            infer_chart_spec(columns=columns, rows=rows),
            "The model proposed a non-numeric chart measure; an automatic chart was used instead.",
        )
    if requested.color is not None and requested.color not in columns:
        requested = requested.model_copy(update={"color": None})
    return requested, None


def _base_layout(title: str | None) -> dict[str, Any]:
    return {
        "template": "plotly_white",
        "height": 430,
        "margin": {"l": 40, "r": 24, "t": 56 if title else 24, "b": 48},
        "title": {
            "text": title or "",
            "font": {"size": 17, "color": "#0f172a"},
            "x": 0.02,
            "xanchor": "left",
        },
        "font": {"family": "Inter, Segoe UI, sans-serif", "color": "#334155"},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "colorway": _PALETTE,
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 1, "xanchor": "right"},
        "hoverlabel": {"bgcolor": "#0f172a", "font": {"color": "white"}},
    }


def _sort_rows(rows: list[dict[str, Any]], x: str) -> list[dict[str, Any]]:
    try:
        return sorted(rows, key=lambda row: (row.get(x) is None, row.get(x)))
    except TypeError:
        return rows


def build_chart(
    *,
    rows: list[dict[str, Any]],
    columns: list[str],
    requested: ChartSpec | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a safe Plotly figure JSON from a validated chart request."""

    if not rows or not columns:
        return None, None

    spec, warning = _validated_spec(requested, columns=columns, rows=rows)
    if spec is None or spec.type == "none" or not spec.x or not spec.y:
        return None, warning

    x_column, y_column = spec.x, spec.y
    title = spec.title or f"{y_column.replace('_', ' ').title()} by {x_column.replace('_', ' ')}"
    figure = go.Figure()

    if spec.type == "pie":
        figure.add_trace(
            go.Pie(
                labels=[row.get(x_column) for row in rows],
                values=[row.get(y_column) for row in rows],
                hole=0.46,
                textinfo="label+percent",
            )
        )
    else:
        series: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if spec.color:
            for row in rows:
                series[str(row.get(spec.color) or "Unknown")].append(row)
        else:
            series[""] = rows

        for series_name, series_rows in list(series.items())[:12]:
            if spec.type in {"line", "area"}:
                ordered = _sort_rows(series_rows, x_column)
                trace = go.Scatter(
                    x=[row.get(x_column) for row in ordered],
                    y=[row.get(y_column) for row in ordered],
                    mode="lines+markers",
                    name=series_name or y_column,
                    line={"width": 2.5},
                    fill="tozeroy" if spec.type == "area" else None,
                    fillcolor="rgba(15, 118, 110, 0.15)" if spec.type == "area" else None,
                )
            elif spec.type == "scatter":
                trace = go.Scatter(
                    x=[row.get(x_column) for row in series_rows],
                    y=[row.get(y_column) for row in series_rows],
                    mode="markers",
                    name=series_name or y_column,
                    marker={"size": 9, "opacity": 0.78},
                )
            else:
                trace = go.Bar(
                    x=[row.get(x_column) for row in series_rows],
                    y=[row.get(y_column) for row in series_rows],
                    name=series_name or y_column,
                )
            figure.add_trace(trace)

    layout = _base_layout(title)
    if spec.type in {"bar", "line", "area", "scatter"} and len(rows) > 12:
        layout["xaxis"] = {"tickangle": -25, "automargin": True}
    if spec.type == "bar":
        layout["barmode"] = "group"
    figure.update_layout(**layout)

    return json.loads(figure.to_json()), warning


__all__ = ["build_chart", "infer_chart_spec"]
