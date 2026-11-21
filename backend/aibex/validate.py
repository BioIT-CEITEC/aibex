"""Full spec validation: structural (aibex/spec.py) + semantic checks against a loaded bundle (docs/api.md,
"Spec validation rules").

Semantic checks:
- every `table` exists in the bundle; every `field` (axes, color, size, label, facet, table columns/sort, filters,
  selection key) is a column of the panel's table
- every `expr` parses with the restricted grammar (aibex/expr.py), uses only columns of its table and type-checks in
  DuckDB (a dry run with `LIMIT 0` on the compiled, normalised SQL – never on the raw string)
- `pca` / `heatmap`: the table is a matrix table (≥ 2 sample columns); `color.field` / `group_by` are samples.tsv
  columns; `rows.by` is `<table>.<column>` of the matrix table or a table linked to it
- widgets: code ≤ 50 000 characters, no network/storage APIs; input SQL passes the read-only query guard

Errors are short, human-readable strings with a location prefix (`panels[0].x.field: ...`), so the LLM can repair
its patch. `validate_spec` never raises.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

import duckdb

from aibex.bundles import Bundle
from aibex.expr import ExprError, compile_expr
from aibex.query import QueryError, check_readonly
from aibex.spec import Filter, PlotPanel, Spec, TablePanel, WidgetPanel, parse_spec

MAX_WIDGET_CODE = 50_000
# docs/api.md: the sandbox has no network anyway (CSP); this catches obvious attempts early and tells the LLM why
WIDGET_BLOCKLIST = {
    "fetch(": re.compile(r"\bfetch\s*\("),
    "XMLHttpRequest": re.compile(r"XMLHttpRequest"),
    "WebSocket": re.compile(r"WebSocket"),
    "importScripts": re.compile(r"importScripts"),
    "document.cookie": re.compile(r"document\s*\.\s*cookie"),
    "localStorage": re.compile(r"localStorage"),
}


def _hint(name: str, options: list[str]) -> str:
    close = difflib.get_close_matches(name, options, n=1, cutoff=0.6)
    if not close:
        lower = {o.lower(): o for o in options}
        if name.lower() in lower:
            close = [lower[name.lower()]]
    if close:
        return f" (did you mean {close[0]!r}?)"
    shown = ", ".join(options[:25]) + (", ..." if len(options) > 25 else "")
    return f" (available: {shown})"


class _Checker:
    def __init__(self, bundle: Bundle):
        self.bundle = bundle
        self.errors: list[str] = []

    def err(self, loc: str, msg: str) -> None:
        self.errors.append(f"{loc}: {msg}")

    def columns(self, table: str) -> list[str]:
        return list(self.bundle.tables[table]["columns"])

    def table(self, loc: str, table: str) -> bool:
        if table in self.bundle.tables:
            return True
        self.err(loc, f"unknown table {table!r}{_hint(table, list(self.bundle.tables))}")
        return False

    def field(self, loc: str, table: str, name: str | None) -> None:
        if name is None:
            return
        cols = self.columns(table)
        if name not in cols:
            self.err(loc, f"unknown column {name!r} in table {table!r}{_hint(name, cols)}")

    def expr(self, loc: str, table: str, expr: str | None) -> None:
        if expr is None:
            return
        try:
            compiled = compile_expr(expr, self.columns(table))
        except ExprError as exc:
            cols = self.columns(table)
            msg = str(exc)
            if msg.startswith("unknown column"):
                msg += f" in table {table!r}{_hint('', cols)}"
            self.err(loc, f"invalid expr {expr!r}: {msg}")
            return
        try:
            self.bundle.cursor().execute(f'SELECT {compiled.sql} FROM "{table}" LIMIT 0').fetchall()
        except duckdb.Error as exc:
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            self.err(loc, f"invalid expr {expr!r}: {first}")

    def encoding(self, loc: str, table: str, enc: Any) -> None:
        if enc is None:
            return
        self.field(f"{loc}.field", table, enc.field)
        self.expr(f"{loc}.expr", table, enc.expr)

    def sample_column(self, loc: str, name: str | None) -> None:
        if name is None:
            return
        cols = self.bundle.samples_columns
        if not cols:
            self.err(loc, "the bundle has no samples.tsv, so sample annotations are not available")
        elif name not in cols:
            self.err(loc, f"unknown samples.tsv column {name!r}{_hint(name, cols)}")

    # -- panels and filters

    def plot(self, loc: str, p: PlotPanel) -> None:
        if not self.table(f"{loc}.table", p.table):
            return
        if p.kind in ("pca", "heatmap"):
            if len(self.bundle.matrix_columns(p.table)) < 2:
                self.err(f"{loc}.table", f"{p.kind} needs a matrix table (key + one numeric column per sample); "
                         f"{p.table!r} has fewer than 2 sample columns")
            if p.kind == "pca" and p.color is not None:
                self.sample_column(f"{loc}.color.field", p.color.field)
            if p.kind == "heatmap":
                self.sample_column(f"{loc}.group_by", p.group_by)
                if p.rows is not None and p.rows.by is not None:
                    self.rows_by(f"{loc}.rows.by", p.table, p.rows.by)
            return
        for name in ("x", "y", "color", "size"):
            self.encoding(f"{loc}.{name}", p.table, getattr(p, name))
        if p.label is not None:
            self.field(f"{loc}.label.field", p.table, p.label.field)
            self.field(f"{loc}.label.by", p.table, p.label.by)
        self.field(f"{loc}.facet", p.table, p.facet)

    def rows_by(self, loc: str, matrix: str, by: str) -> None:
        table, _, col = by.partition(".")
        if not self.table(loc, table):
            return
        self.field(loc, table, col)
        if table != matrix and not self._linked(table, matrix):
            self.err(loc, f"table {table!r} is not linked to {matrix!r} in bundle.yaml")

    def _linked(self, a: str, b: str) -> bool:
        for lk in self.bundle.links:
            ta, tb = lk["from"].split(".", 1)[0], lk["to"].split(".", 1)[0]
            if {ta, tb} == {a, b}:
                return True
        return False

    def table_panel(self, loc: str, p: TablePanel) -> None:
        if not self.table(f"{loc}.table", p.table):
            return
        for i, c in enumerate(p.columns or []):
            self.field(f"{loc}.columns[{i}]", p.table, c)
        for i, s in enumerate(p.sort):
            self.field(f"{loc}.sort[{i}].field", p.table, s.field)

    def widget(self, loc: str, p: WidgetPanel) -> None:
        if len(p.code) > MAX_WIDGET_CODE:
            self.err(f"{loc}.code", f"widget code is {len(p.code)} characters, the limit is {MAX_WIDGET_CODE}")
        for label, rx in WIDGET_BLOCKLIST.items():
            if rx.search(p.code):
                self.err(f"{loc}.code", f"widget code must not use {label} (widgets have no network or storage; "
                         "data arrive through `inputs`)")
        for i, inp in enumerate(p.inputs):
            try:
                check_readonly(inp.sql)
            except QueryError as exc:
                self.err(f"{loc}.inputs[{i}].sql", str(exc))

    def filter(self, loc: str, f: Filter) -> None:
        if not self.table(f"{loc}.table", f.table):
            return
        self.field(f"{loc}.field", f.table, f.field)
        self.expr(f"{loc}.expr", f.table, f.expr)

    def selection(self, spec: Spec) -> None:
        if spec.selection is None:
            return
        key = spec.selection.key
        if not any(key in t["columns"] for t in self.bundle.tables.values()):
            all_cols = sorted({c for t in self.bundle.tables.values() for c in t["columns"]})
            self.err("selection.key", f"column {key!r} is not in any table of the bundle{_hint(key, all_cols)}")

    def run(self, spec: Spec) -> list[str]:
        if spec.bundle != self.bundle.id:
            self.err("bundle", f"spec is for bundle {spec.bundle!r}, not {self.bundle.id!r}")
        for i, f in enumerate(spec.filters):
            self.filter(f"filters[{i}]", f)
        for i, p in enumerate(spec.panels):
            loc = f"panels[{i}]"
            if isinstance(p, PlotPanel):
                self.plot(loc, p)
            elif isinstance(p, TablePanel):
                self.table_panel(loc, p)
            elif isinstance(p, WidgetPanel):
                self.widget(loc, p)
        self.selection(spec)
        return self.errors


def check_semantics(spec: Spec, bundle: Bundle) -> list[str]:
    """Semantic errors of a structurally valid spec against `bundle` (empty list = valid)."""
    return _Checker(bundle).run(spec)


def validate_spec(data: Any, bundle: Bundle) -> tuple[Spec | None, list[str]]:
    """Structural + semantic validation. Returns (spec, []) or (None, errors); never raises."""
    spec, errors = parse_spec(data)
    if spec is None:
        return None, errors
    try:
        errors = check_semantics(spec, bundle)
    except Exception as exc:  # noqa: BLE001 – a validator bug must not crash a live demo; report it as an error
        errors = [f"validation failed: {type(exc).__name__}: {exc}"]
    return (None, errors) if errors else (spec, [])
