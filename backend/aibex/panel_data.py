"""Panel data: the rows a panel shows, with the spec's filters applied (docs/api.md → "Panel data shape", "Filters").

Every SQL string here is built from validated parts only: identifiers come from the (validated) spec and are
quoted, `expr`s are compiled by aibex/expr.py (the raw string never runs) and filter values are bound parameters.

- `plot` panels (scatter/line/bar/box/violin/histogram): columns `x`, `y` (when defined), `color`, `size`, `label`,
  `facet` when set, plus the table key column (named as in the bundle). `label` holds the label text for rows to be
  labelled (explicit `values`, matched case-insensitively, or the `top_n` rows ascending by `by`), else NULL.
  Labelled rows come first so the 5000-row cap never drops them.
- `table` panels: the listed columns (all when omitted) in order, plus the key column at the end when not listed;
  sorted as specified, then by the key.
- `pca` / `heatmap` panels: task T15c; `widget` panels: task T40a (raise `PanelDataUnsupported`).
- `text` panels have no data (empty result).

A filter applies to panels on its own table and, one hop through a bundle link in either direction, to panels on
linked tables as a semi-join on the link columns (decided, Q2). Disabled filters are ignored.
"""

from __future__ import annotations

from typing import Any

import duckdb

from aibex.bundles import Bundle
from aibex.expr import compile_expr
from aibex.query import jsonable
from aibex.spec import Filter, PlotPanel, Spec, TablePanel, TextPanel

MAX_ROWS = 5000

_OPS = {"<=": "<=", ">=": ">=", "<": "<", ">": ">", "==": "=", "!=": "<>"}


class PanelNotFound(KeyError):
    pass


class PanelDataUnsupported(ValueError):
    """The panel type has no panel-data implementation yet."""


class PanelDataError(ValueError):
    """The query for the panel failed (message is safe to show)."""


def q(name: str) -> str:
    """Quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _columns(bundle: Bundle, table: str) -> list[str]:
    return list(bundle.tables[table]["columns"])


def _expr_sql(bundle: Bundle, table: str, expr: str) -> str:
    return compile_expr(expr, _columns(bundle, table)).sql


def _filter_condition(bundle: Bundle, f: Filter, params: list) -> str:
    """Boolean SQL for one filter over its own table (unqualified columns)."""
    if f.expr is not None:
        return f"({_expr_sql(bundle, f.table, f.expr)})"
    col = q(f.field or "")
    if f.op in _OPS:
        params.append(f.value)
        return f"{col} {_OPS[f.op]} ?"
    if f.op == "between":
        params.extend(f.value)
        return f"{col} BETWEEN ? AND ?"
    if f.op == "in":
        params.extend(f.value)
        return f"{col} IN ({', '.join('?' for _ in f.value)})"
    if f.op == "contains":
        params.append(f.value)
        return f"contains(lower(CAST({col} AS VARCHAR)), lower(?))"
    raise PanelDataError(f"filter {f.id!r}: unsupported op {f.op!r}")


def _link_columns(bundle: Bundle, table: str, other: str) -> tuple[str, str] | None:
    """(column of `table`, column of `other`) of the first bundle link between the two tables, either direction."""
    for lk in bundle.links:
        a_table, _, a_col = lk["from"].partition(".")
        b_table, _, b_col = lk["to"].partition(".")
        if a_table == table and b_table == other:
            return a_col, b_col
        if b_table == table and a_table == other:
            return b_col, a_col
    return None


def filter_where(spec: Spec, bundle: Bundle, table: str) -> tuple[list[str], list]:
    """WHERE conditions (AND-ed) and their parameters for panels on `table`."""
    conds: list[str] = []
    params: list = []
    for f in spec.filters:
        if not f.enabled or f.table not in bundle.tables:
            continue
        if f.table == table:
            conds.append(_filter_condition(bundle, f, params))
            continue
        link = _link_columns(bundle, table, f.table)
        if link is None:
            continue
        own, other = link
        cond = _filter_condition(bundle, f, params)
        conds.append(f"{q(own)} IN (SELECT {q(other)} FROM {q(f.table)} WHERE {cond})")
    return conds, params


def _encoding_sql(bundle: Bundle, table: str, enc: Any) -> str:
    return q(enc.field) if enc.field is not None else f"({_expr_sql(bundle, table, enc.expr)})"


def _plot_select(p: PlotPanel, bundle: Bundle, key: str | None) -> tuple[list[str], list[str], list, str]:
    """(select expressions, output column names, params, ORDER BY) for a simple plot."""
    exprs: list[str] = []
    names: list[str] = []
    params: list = []
    for name in ("x", "y", "color", "size"):
        enc = getattr(p, name)
        if enc is not None:
            exprs.append(_encoding_sql(bundle, p.table, enc))
            names.append(name)
    order = []
    if p.label is not None:
        lab = p.label
        text = f"CAST({q(lab.field)} AS VARCHAR)"
        hits = []
        if lab.values:
            hits.append(f"lower({text}) IN ({', '.join('?' for _ in lab.values)})")
            params.extend(v.lower() for v in lab.values)
        if lab.top_n and lab.by:
            hits.append(f"row_number() OVER (ORDER BY {q(lab.by)} ASC NULLS LAST) <= {int(lab.top_n)}")
        label_sql = f"CASE WHEN {' OR '.join(hits)} THEN {text} END" if hits else "CAST(NULL AS VARCHAR)"
        exprs.append(label_sql)
        names.append("label")
        order.append('"label" IS NULL')
    if p.facet is not None:
        exprs.append(q(p.facet))
        names.append("facet")
    if key is not None and key not in names:
        exprs.append(q(key))
        names.append(key)
        order.append(q(key))
    return exprs, names, params, ", ".join(order)


def _table_select(p: TablePanel, bundle: Bundle, key: str | None) -> tuple[list[str], list[str], str]:
    cols = list(p.columns) if p.columns else _columns(bundle, p.table)
    if key is not None and key not in cols:
        cols.append(key)
    order = [f"{q(s.field)} {s.dir.upper()} NULLS LAST" for s in p.sort]
    if key is not None and key not in [s.field for s in p.sort]:
        order.append(q(key))
    return [q(c) for c in cols], cols, ", ".join(order)


def panel_data(spec: Spec, bundle: Bundle, panel_id: str) -> dict:
    """`{columns, rows, truncated}` for a panel (max 5000 rows). Raises PanelNotFound / PanelDataUnsupported /
    PanelDataError."""
    panel = next((p for p in spec.panels if p.id == panel_id), None)
    if panel is None:
        raise PanelNotFound(panel_id)
    if isinstance(panel, TextPanel):
        return {"columns": [], "rows": [], "truncated": False}
    if isinstance(panel, PlotPanel) and panel.kind in ("pca", "heatmap"):
        raise PanelDataUnsupported(f"panel data for {panel.kind} panels is not implemented yet (task T15c)")
    if not isinstance(panel, (PlotPanel, TablePanel)):
        raise PanelDataUnsupported(f"panel data for {panel.type} panels is not implemented yet (task T40a)")
    if panel.table not in bundle.tables:
        raise PanelDataError(f"unknown table {panel.table!r}")

    key = bundle.tables[panel.table].get("key")
    if isinstance(panel, PlotPanel):
        exprs, names, params, order = _plot_select(panel, bundle, key)
    else:
        exprs, names, order = _table_select(panel, bundle, key)
        params = []
    conds, where_params = filter_where(spec, bundle, panel.table)

    # the label window (top_n) must rank the filtered rows: filter in a subquery first
    source = q(panel.table)
    if conds:
        source = f"(SELECT * FROM {q(panel.table)} WHERE {' AND '.join(conds)})"
    sql = f"SELECT {', '.join(f'{e} AS {q(n)}' for e, n in zip(exprs, names, strict=True))} FROM {source} AS t"
    if order and isinstance(panel, PlotPanel):
        # plot ORDER BY refers to output columns (label, key): order in an outer query to avoid name clashes
        sql = f"SELECT * FROM ({sql}) AS o ORDER BY {order}"
    elif order:
        sql += f" ORDER BY {order}"
    sql += f" LIMIT {MAX_ROWS + 1}"
    try:
        # parameter order follows the SQL text: SELECT (label values) before the filter subquery
        rows = bundle.cursor().execute(sql, params + where_params).fetchall()
    except duckdb.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise PanelDataError(f"panel {panel_id!r}: query failed: {first}") from None
    truncated = len(rows) > MAX_ROWS
    return {
        "columns": names,
        "rows": [[jsonable(v) for v in r] for r in rows[:MAX_ROWS]],
        "truncated": truncated,
    }
