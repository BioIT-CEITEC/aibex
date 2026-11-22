"""LLM tools as plain functions (docs/api.md → "Chat loop"). The chat loop (T22b) only dispatches to `run_tool`.

Privacy rule: the model never receives whole tables. `describe_bundle` returns the schema plus summary statistics
(no rows; at most 10 example values per string column), `query_data` returns at most 200 rows.
Every tool returns a JSON-able dict and never raises: problems come back as `{"ok": false, "errors": [...]}` so the
model can repair its call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aibex.bundles import Bundle
from aibex.query import QueryError, jsonable, run_query
from aibex.sessions import NothingToUndo, PatchError, Session

MAX_TOOL_ROWS = 200  # privacy rule: no tool result contains more rows than this
N_EXAMPLES = 10  # example values per string column in describe_bundle
MAX_EXAMPLE_LEN = 80  # long example strings are cut

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "describe_bundle",
            "description": (
                "Describe the results bundle: tables, columns with types, row counts, links between tables and "
                "summary statistics per column (numeric min/max/mean, string distinct count and examples). No rows."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_data",
            "description": (
                "Run one read-only DuckDB SELECT on the bundle tables. At most 200 rows are returned; prefer "
                "aggregates (count, avg, GROUP BY) and ORDER BY ... LIMIT. Result: {columns, rows, row_count, "
                "truncated}."
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "a single SELECT/WITH statement"}},
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_view",
            "description": (
                "Change the view by applying an RFC 6902 JSON Patch to the current view spec. The patched spec is "
                "validated; on errors nothing changes and the errors are returned so you can fix the patch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "array",
                        "description": 'JSON Patch operations, e.g. [{"op": "replace", "path": '
                        '"/panels/0/title", "value": "Volcano"}]',
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": ["add", "remove", "replace", "move", "copy", "test"],
                                },
                                "path": {"type": "string"},
                                "from": {"type": "string"},
                                "value": {},
                            },
                            "required": ["op", "path"],
                        },
                    },
                    "summary": {"type": "string", "description": "one short sentence describing the change"},
                },
                "required": ["patch", "summary"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_view",
            "description": "Undo the last change(s) to the view.",
            "parameters": {
                "type": "object",
                "properties": {"steps": {"type": "integer", "minimum": 1, "default": 1}},
                "additionalProperties": False,
            },
        },
    },
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]
CHANGE_TOOLS = {
    "update_view",
    "create_widget",
}  # a rejected call of these counts as a failed attempt (docs/api.md)


@dataclass
class ToolOutcome:
    """What a tool call did. `result` goes back to the model as the tool message content (`content()`)."""

    name: str
    result: dict
    changed: bool = False  # a new spec version was applied
    failed_change: bool = False  # a rejected update_view/create_widget (counts towards "2 failures in a row")
    summary: str = ""  # history summary of an applied change

    def content(self) -> str:
        return json.dumps(self.result, ensure_ascii=False, default=str)


def _err(*errors: str) -> dict:
    return {"ok": False, "errors": list(errors)}


# --- describe_bundle ------------------------------------------------------------------------------------------------
def _qi(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _example(v: Any) -> Any:
    v = jsonable(v)
    if isinstance(v, str) and len(v) > MAX_EXAMPLE_LEN:
        return v[: MAX_EXAMPLE_LEN - 1] + "…"
    return v


def _table_stats(bundle: Bundle, table: str, columns: dict[str, dict]) -> dict[str, dict]:
    cur = bundle.cursor()
    exprs: list[str] = []
    plan: list[tuple[str, str, list[str]]] = []  # column, type, stat names (in the order of exprs)
    for col, meta in columns.items():
        q = _qi(col)
        typ = meta.get("type", "string")
        names = ["n_null"]
        exprs.append(f"count(*) - count({q})")
        if typ in ("int", "float"):
            names += ["min", "max", "mean"]
            exprs += [f"min({q})", f"max({q})", f"avg({q})"]
        elif typ == "date":
            names += ["min", "max"]
            exprs += [f"min({q})", f"max({q})"]
        elif typ == "bool":
            names += ["n_true"]
            exprs += [f"count(*) FILTER (WHERE {q})"]
        else:
            names += ["n_distinct"]
            exprs += [f"count(DISTINCT {q})"]
        plan.append((col, typ, names))
    stats: dict[str, dict] = {}
    if not exprs:
        return stats
    values = list(cur.execute(f"SELECT {', '.join(exprs)} FROM {_qi(table)}").fetchone())
    for col, typ, names in plan:
        st = {n: jsonable(values.pop(0)) for n in names}
        if "mean" in st and isinstance(st["mean"], float):
            st["mean"] = float(f"{st['mean']:.6g}")
        if typ == "string":
            rows = cur.execute(
                f"SELECT {_qi(col)} AS v, count(*) AS n FROM {_qi(table)} WHERE {_qi(col)} IS NOT NULL "
                f"GROUP BY v ORDER BY n DESC, v LIMIT {N_EXAMPLES}"
            ).fetchall()
            st["examples"] = [_example(r[0]) for r in rows]
        stats[col] = st
    return stats


def describe_bundle(bundle: Bundle) -> dict:
    """Schema (as `GET /bundles/{id}/schema`) with per-column `stats`; plus samples.tsv columns if present. No rows."""
    schema = json.loads(json.dumps(bundle.schema(), default=str))  # deep copy, JSON-safe
    for name, t in schema["tables"].items():
        stats = _table_stats(bundle, name, t["columns"])
        for col, meta in t["columns"].items():
            meta["stats"] = stats.get(col, {})
        n_samples = len(bundle.matrix_columns(name))
        if n_samples and n_samples == len(t["columns"]) - 1:
            t["matrix"] = True  # key column + one numeric column per sample
    if bundle.samples:
        cols = bundle.samples_columns
        schema["samples"] = {
            "n": len(bundle.samples),
            "columns": {c: sorted({str(s.get(c)) for s in bundle.samples})[:N_EXAMPLES] for c in cols},
        }
    return schema


# --- query_data -----------------------------------------------------------------------------------------------------
def query_data(bundle: Bundle, sql: Any) -> dict:
    """Guarded read-only query, at most 200 rows: `{columns, rows, row_count, truncated}` (+ `note` when truncated)."""
    if not isinstance(sql, str) or not sql.strip():
        return _err("query_data needs 'sql': a single SELECT statement as a string")
    try:
        out = run_query(bundle.cursor(), sql, limit=MAX_TOOL_ROWS)
    except QueryError as exc:
        return _err(str(exc))
    if out["truncated"]:
        out["note"] = (
            f"only the first {MAX_TOOL_ROWS} of {out['row_count']} rows are shown; use aggregates or ORDER BY + LIMIT"
        )
    return out


# --- update_view / undo_view ----------------------------------------------------------------------------------------
def _coerce_patch(patch: Any) -> Any:
    if isinstance(patch, str):  # some models double-encode the patch
        try:
            patch = json.loads(patch)
        except json.JSONDecodeError:
            return patch
    if isinstance(patch, dict) and "op" in patch:
        patch = [patch]
    return patch


def update_view(session: Session, patch: Any, summary: Any = None) -> ToolOutcome:
    """Validate and apply the patch as one new version (source `llm`); errors are returned, the spec is unchanged."""
    patch = _coerce_patch(patch)
    text = summary.strip() if isinstance(summary, str) and summary.strip() else None
    try:
        session.apply_patch(patch, text, source="llm")
    except PatchError as exc:
        return ToolOutcome("update_view", _err(*exc.errors), failed_change=True)
    return ToolOutcome(
        "update_view",
        {"ok": True, "version": session.version},
        changed=True,
        summary=session.history[-1]["summary"],
    )


def undo_view(session: Session, steps: Any = 1) -> ToolOutcome:
    """Undo `steps` changes (clamped) as one new version (source `llm`)."""
    try:
        n = 1 if steps is None else int(steps)
    except (TypeError, ValueError):
        return ToolOutcome("undo_view", _err(f"steps must be a positive integer, got {steps!r}"))
    if n < 1:
        return ToolOutcome("undo_view", _err(f"steps must be a positive integer, got {steps!r}"))
    try:
        session.undo(n, source="llm")
    except NothingToUndo as exc:
        return ToolOutcome("undo_view", _err(str(exc)))
    return ToolOutcome(
        "undo_view",
        {"ok": True, "version": session.version},
        changed=True,
        summary=session.history[-1]["summary"],
    )


# --- dispatcher -----------------------------------------------------------------------------------------------------
def run_tool(session: Session, name: str, arguments: Any) -> ToolOutcome:
    """Run one tool call for the chat loop. Never raises; unknown tools and bad arguments become error results."""
    failed = name in CHANGE_TOOLS
    if not isinstance(arguments, dict):
        arguments = {}
    if "_invalid_arguments" in arguments:
        raw = str(arguments["_invalid_arguments"])[:200]
        return ToolOutcome(name, _err(f"arguments are not a valid JSON object: {raw}"), failed_change=failed)
    try:
        if name == "describe_bundle":
            return ToolOutcome(name, describe_bundle(session.bundle))
        if name == "query_data":
            return ToolOutcome(name, query_data(session.bundle, arguments.get("sql")))
        if name == "update_view":
            if "patch" not in arguments:
                return ToolOutcome(
                    name,
                    _err("update_view needs 'patch' (a list of JSON Patch operations)"),
                    failed_change=True,
                )
            return update_view(session, arguments["patch"], arguments.get("summary"))
        if name == "undo_view":
            return undo_view(session, arguments.get("steps", 1))
        if name == "create_widget":
            return ToolOutcome(name, _err("create_widget is not available yet"), failed_change=True)
    except Exception as exc:  # noqa: BLE001 – a tool must never crash the chat loop
        return ToolOutcome(
            name, _err(f"{name} failed: {type(exc).__name__}: {str(exc)[:300]}"), failed_change=failed
        )
    return ToolOutcome(name, _err(f"unknown tool {name!r}; available: {', '.join(TOOL_NAMES)}"))
