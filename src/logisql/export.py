from __future__ import annotations

from typing import Any

# A leading one of these characters makes spreadsheet software treat a cell as
# a formula. Prefixing an apostrophe keeps the value readable but inert.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formula injection without altering typed numbers."""

    if not isinstance(value, str) or not value:
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


__all__ = ["sanitize_csv_cell"]
