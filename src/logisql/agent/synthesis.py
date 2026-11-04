from __future__ import annotations

import math
from typing import Any

from logisql.agent.llm import SynthesisOutput


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isfinite(value) and abs(value) >= 1000:
            return f"{value:,.2f}"
        return f"{value:g}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def fallback_synthesis(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    row_count: int,
    truncated: bool,
    reason: str | None = None,
) -> SynthesisOutput:
    """Deterministic executive summary used when narration fails."""

    if not rows:
        return SynthesisOutput(
            headline="No matching records",
            summary="The validated query completed successfully but returned no rows.",
            key_takeaways=["No matching records were found for this question."],
            chart=None,
        )

    row_word = "row" if row_count == 1 else "rows"
    suffix = " (result capped; more rows may exist)" if truncated else ""
    summary = (
        f"The query returned {row_count:,} {row_word}{suffix}. "
        f"Returned fields: {', '.join(columns[:8])}"
        f"{'…' if len(columns) > 8 else ''}. Review the result table and SQL "
        "for the full evidence."
    )

    takeaways: list[str] = []
    for row in rows[:3]:
        parts = [f"{column}: {_format_value(row.get(column))}" for column in columns[:4]]
        takeaways.append(" · ".join(parts))
    if not takeaways:
        takeaways = ["The query completed without a narrative summary."]

    return SynthesisOutput(
        headline=f"Query returned {row_count:,} {row_word}",
        summary=summary,
        key_takeaways=takeaways,
        chart=None,
    )


__all__ = ["fallback_synthesis"]
