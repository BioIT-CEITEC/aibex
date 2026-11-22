"""Level 2 widget inputs (docs/api.md → "Panel data shape", "Spec validation rules"; task T40a).

Each widget input is one read-only SQL query over the bundle tables, run through the same guard as the LLM's
`query_data` tool (`aibex/query.py`). The only parameter allowed is `$selected`: it is bound by DuckDB (never
string-formatted) to the first key of the current linked selection, or NULL when nothing is selected. Spec filters
do not apply to widget inputs (their SQL is free-form); the widget's SQL decides what it shows. Each input returns at
most 5000 rows (`truncated` tells when there were more).
"""

from __future__ import annotations

from typing import Any

import duckdb

from aibex.bundles import Bundle
from aibex.query import QueryError, check_readonly, run_query, sql_parameters
from aibex.spec import WidgetPanel

MAX_INPUT_ROWS = 5000
ALLOWED_PARAMS = ("selected",)


def input_params(sql: str) -> dict[str, Any] | None:
    """Parameters for a widget input, all NULL (for a dry run); raises QueryError for anything but `$selected`."""
    names = sql_parameters(sql)
    bad = [n for n in names if n not in ALLOWED_PARAMS]
    if bad:
        shown = ", ".join("?" if n == "?" else f"${n}" for n in bad)
        raise QueryError(f"parameter {shown} is not allowed; the only parameter is $selected "
                         "(the first selected key, or NULL)")
    return {n: None for n in names} or None


def check_input(bundle: Bundle, sql: str) -> None:
    """Guard + parameter check + a LIMIT 0 dry run (unknown tables/columns surface here); raises QueryError."""
    stmt = check_readonly(sql)
    params = input_params(sql)
    try:
        bundle.cursor().execute(f"SELECT * FROM (\n{stmt}\n) AS w LIMIT 0", params or []).fetchall()
    except duckdb.Error as exc:  # binder/catalog errors; the message is shown to the LLM
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise QueryError(f"query failed: {first}") from None


def resolve_inputs(panel: WidgetPanel, bundle: Bundle, selection: list[Any] | None = None) -> dict:
    """`{inputs: {name: {columns, rows, truncated}}}`; raises QueryError when an input fails."""
    selected = selection[0] if selection else None
    out: dict[str, dict] = {}
    for inp in panel.inputs:
        params = input_params(inp.sql)
        if params is not None:
            params = {n: selected for n in params}
        try:
            res = run_query(bundle.cursor(), inp.sql, limit=MAX_INPUT_ROWS, params=params)
        except QueryError as exc:
            raise QueryError(f"input {inp.name!r}: {exc}") from None
        out[inp.name] = {"columns": res["columns"], "rows": res["rows"], "truncated": res["truncated"]}
    return {"inputs": out}
