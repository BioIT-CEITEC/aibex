"""Deterministic `FakeProvider` (`LLM_PROVIDER=fake`): no network, used by e2e tests and offline demos.

Rules on the last user message (case-insensitive), docs/api.md → "LLM provider":
- `label <G1>[, <G2> ...]` → `update_view` replacing `label.values` of the first scatter plot panel
- `padj below <x>`         → `update_view` adding (or replacing) filter `padj-lt` on the first scatter's table
- `undo` / `undo <n>`      → `undo_view` with `steps` n (default 1)
- `add widget`             → `create_widget` `row-count` (one input over the bundle's first table)
- anything else            → text "FakeProvider: no rule matched"
- after a tool result      → text "FakeProvider: done" (so the chat loop ends)

The provider only sees `messages` (the `LLMProvider` protocol), so it reads the current spec and the bundle schema from
the context the chat loop sends: any JSON object in a system/user message (fenced ```json block or bare, possibly nested,
e.g. `{"spec": {...}, "schema": {...}}`) that looks like a spec (`panels` list) or a bundle schema (`tables` object).
"""

from __future__ import annotations

import json
import re
from typing import Any

from aibex.llm.provider import LLMResponse, ToolCall, _json_objects

NO_RULE = "FakeProvider: no rule matched"
DONE = "FakeProvider: done"

_LABEL_RE = re.compile(r"\blabel\s+(.+)", re.IGNORECASE | re.DOTALL)
_PADJ_RE = re.compile(r"\bpadj\s+below\s+([0-9]*\.?[0-9]+(?:e[-+]?[0-9]+)?)", re.IGNORECASE)
_UNDO_RE = re.compile(r"^\W*undo(?:\s+(\d+))?\W*$", re.IGNORECASE)
_WIDGET_RE = re.compile(r"\badd\s+(?:a\s+)?widget\b", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\s*(?:,|;|\band\b|\s)\s*", re.IGNORECASE)

WIDGET_CODE = """export default function Widget({ data }: { data: any }) {
  const n = data?.inputs?.rows?.rows?.length ?? 0;
  return (
    <div style={{ padding: 16, fontFamily: 'sans-serif' }}>
      <div style={{ fontSize: 32, fontWeight: 600 }}>{n}</div>
      <div style={{ color: '#666' }}>rows in the input (max 50)</div>
    </div>
  );
}
"""


def _content_text(content: Any) -> str:
    """Message content as text (OpenAI content may be a string or a list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def _walk(value: Any):
    """All dicts inside a JSON value (depth-first, the value itself first)."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            yield v
            stack.extend(reversed(list(v.values())))
        elif isinstance(v, list):
            stack.extend(reversed(v))


def _is_spec(d: dict) -> bool:
    return isinstance(d.get("panels"), list) and "bundle" in d


def _is_schema(d: dict) -> bool:
    return isinstance(d.get("tables"), dict) and "panels" not in d


def find_context(messages: list[dict]) -> tuple[dict | None, dict | None]:
    """(spec, schema) from the newest system/user message that contains them; None when not found."""
    spec: dict | None = None
    schema: dict | None = None
    for m in reversed(messages):
        if m.get("role") not in ("system", "user"):
            continue
        text = _content_text(m.get("content"))
        if "{" not in text:
            continue
        for obj in _json_objects(text):
            for d in _walk(obj):
                if spec is None and _is_spec(d):
                    spec = d
                elif schema is None and _is_schema(d):
                    schema = d
        if spec is not None and schema is not None:
            break
    return spec, schema


def _first_scatter(spec: dict) -> tuple[int, dict] | None:
    for i, p in enumerate(spec.get("panels", [])):
        if isinstance(p, dict) and p.get("type") == "plot" and p.get("kind") == "scatter":
            return i, p
    return None


def _first_table(spec: dict | None, schema: dict | None) -> str | None:
    if schema and schema.get("tables"):
        return next(iter(schema["tables"]))
    for p in (spec or {}).get("panels", []):
        if isinstance(p, dict) and isinstance(p.get("table"), str):
            return p["table"]
    return None


class FakeProvider:
    """Rule-based `LLMProvider` (see module docstring). Counts calls; never raises."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict], model: str | None = None) -> LLMResponse:
        self.calls += 1
        if messages and messages[-1].get("role") == "tool":
            return LLMResponse(text=DONE)
        prompt = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                prompt = _content_text(m.get("content")).strip()
                break
        return self._rule(prompt, messages)

    def _call(self, name: str, arguments: dict) -> LLMResponse:
        return LLMResponse(tool_calls=[ToolCall(id=f"fake-{self.calls}", name=name, arguments=arguments)])

    def _rule(self, prompt: str, messages: list[dict]) -> LLMResponse:
        if m := _UNDO_RE.match(prompt):
            return self._call("undo_view", {"steps": int(m.group(1) or 1)})
        if _WIDGET_RE.search(prompt):
            return self._widget(messages)
        if m := _PADJ_RE.search(prompt):
            return self._padj(float(m.group(1)), messages)
        if m := _LABEL_RE.search(prompt):
            return self._label(m.group(1), messages)
        return LLMResponse(text=NO_RULE)

    def _label(self, rest: str, messages: list[dict]) -> LLMResponse:
        genes = [g.strip(" \t.,;:!?\"'") for g in _SPLIT_RE.split(rest.strip())]
        genes = list(dict.fromkeys(g for g in genes if g))
        spec, _ = find_context(messages)
        found = _first_scatter(spec) if spec else None
        if not genes or found is None:
            return LLMResponse(text=f"{NO_RULE} (no genes or no scatter plot in the view)")
        i, panel = found
        if isinstance(panel.get("label"), dict):
            patch = [{"op": "replace", "path": f"/panels/{i}/label/values", "value": genes}]
        else:
            field = (spec.get("selection") or {}).get("key") if isinstance(spec.get("selection"), dict) else None
            if not field:
                return LLMResponse(text=f"{NO_RULE} (the first scatter plot has no label column)")
            patch = [{"op": "add", "path": f"/panels/{i}/label", "value": {"field": field, "values": genes}}]
        return self._call("update_view", {"patch": patch, "summary": f"Label {', '.join(genes)}"})

    def _padj(self, x: float, messages: list[dict]) -> LLMResponse:
        spec, _ = find_context(messages)
        found = _first_scatter(spec) if spec else None
        if found is None:
            return LLMResponse(text=f"{NO_RULE} (no scatter plot in the view)")
        flt = {"id": "padj-lt", "table": found[1].get("table"), "field": "padj", "op": "<", "value": x, "enabled": True}
        filters = spec.get("filters") or []
        idx = next((k for k, f in enumerate(filters) if isinstance(f, dict) and f.get("id") == "padj-lt"), None)
        if idx is not None:
            patch = [{"op": "replace", "path": f"/filters/{idx}", "value": flt}]
        elif "filters" in spec:
            patch = [{"op": "add", "path": "/filters/-", "value": flt}]
        else:
            patch = [{"op": "add", "path": "/filters", "value": [flt]}]
        return self._call("update_view", {"patch": patch, "summary": f"Filter padj < {x:g}"})

    def _widget(self, messages: list[dict]) -> LLMResponse:
        spec, schema = find_context(messages)
        table = _first_table(spec, schema)
        if table is None:
            return LLMResponse(text=f"{NO_RULE} (no bundle table in the context)")
        return self._call(
            "create_widget",
            {
                "id": "row-count",
                "title": "Row count",
                "inputs": [{"name": "rows", "sql": f"SELECT * FROM {_ident(table)} LIMIT 50"}],
                "code": WIDGET_CODE,
            },
        )


def _ident(name: str) -> str:
    """Table name as a SQL identifier (quoted unless it is a plain lower-case word)."""
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else json.dumps(name)
