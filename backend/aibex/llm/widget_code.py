"""Widget code written by the code model (T42; docs/api.md → "Chat loop", `create_widget` with `description`).

The chat model (`llm_model_fast`) plans the widget: id, title, read-only SQL inputs and a plain-language
`description`. `write_widget_code` then asks the code model (`llm_model_code`) for the TSX. The code model sees only
the description, the input names with their SQL and result columns/types (from a `LIMIT 0` run – no rows), the
runtime contract and, when a widget is replaced, its previous code. It gets no tools. The answer is parsed from a
fenced code block (or the bare text) and must contain `export default`; otherwise a readable `WidgetCodeError`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import duckdb

from aibex.bundles import Bundle
from aibex.query import QueryError, check_readonly
from aibex.widgets import input_params

MAX_DESCRIPTION = 4000
CODE_MODEL_TIMEOUT = 90.0  # seconds, one non-streamed attempt (providers without chat_text)
CODE_STREAM_IDLE = 60.0  # streamed: max seconds without a new chunk (incl. time to the first token)
CODE_STREAM_MAX = 150.0  # streamed: max seconds in total for the code model
CODE_FALLBACK_MAX = 90.0  # streamed: max seconds in total for the chat-model fallback
# Reasoning models on the e-INFRA LiteLLM proxy otherwise think for minutes (>30 000 reasoning chars, no answer
# after 150 s) on the widget prompt; with these hints `coder` answered in 12–16 s (T42 probe, 2026-11-22). Both keys
# were accepted by `coder` and `agentic`: `reasoning_effort` (OpenAI / gpt-oss style) and `enable_thinking` (Qwen-style
# chat templates); a model that does not know one ignores it.
CODE_EXTRA_BODY: dict = {"reasoning_effort": "low", "chat_template_kwargs": {"enable_thinking": False}}

# (description, inputs, previous_code, errors) -> code; raises WidgetCodeError
CodeWriter = Callable[[str, list[dict], str | None, list[str] | None], str]

WIDGET_CODE_PROMPT = """You write one small React component (TSX) for a sandboxed dashboard widget in a \
bioinformatics app. Reply with ONLY the code in one ```tsx code block, no explanation.

Runtime contract:
- `export default function Widget({ data, selection, onSelect })`.
- `data.inputs.<name>` is {columns: string[], rows: any[][]} – rows are arrays in column order; look up column \
positions with columns.indexOf("<column>"). This holds for one-row inputs too: \
`row[cols.indexOf("gene_name")]`, never `row.gene_name`. Inputs can be empty (0 rows), e.g. when nothing is \
selected: then render a short hint such as "Select a gene in a plot or table".
- `selection` is the list of selected keys (may be empty); call onSelect([key]) to select.
- `React` and `Plotly` are globals. Do not import anything else; there is no network (no fetch, XMLHttpRequest, \
WebSocket, localStorage, cookies, eval, new Function, window.open). Hooks: React.useState, React.useEffect, React.useRef.
- For charts use Plotly.react(divRef.current, traces, layout, {displayModeBar: false, responsive: true}) inside \
React.useEffect, on a <div ref={divRef} style={{width: "100%", height: "100%"}} />. Plotly is the basic bundle: \
scatter, bar and pie traces only.
- Trace x and y are flat arrays of numbers or strings, never arrays of arrays. To draw many line segments (e.g. \
stems or connectors) in one trace, use flat arrays with null between segments: x [p1, p1, null, p2, p2, null]. \
Prefer one plot; for stacked subplots give every axis a domain and an anchor (yaxis2: {domain, anchor: "x"}).
- The widget fills its panel (style the root with width/height 100%). Keep it short (about 150 lines at most), \
readable and robust: no crash on nulls or missing columns."""


class WidgetCodeError(Exception):
    """The code model failed or returned no usable code; the message goes back to the chat model.

    `unreachable` = no model answered (time-out, network): a retry would only double the wait, so the chat loop stops.
    """

    def __init__(self, message: str, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


def input_columns(bundle: Bundle, sql: str) -> list[tuple[str, str]]:
    """Result columns and DuckDB types of a widget input (LIMIT 0, parameters NULL); raises QueryError."""
    stmt = check_readonly(sql)
    params = input_params(sql)
    try:
        cur = bundle.cursor()
        cur.execute(f"SELECT * FROM (\n{stmt}\n) AS w LIMIT 0", params or [])
        return [(d[0], str(d[1])) for d in cur.description or []]
    except duckdb.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise QueryError(f"query failed: {first}") from None


def _describe_inputs(bundle: Bundle, inputs: list[dict]) -> str:
    lines = []
    for inp in inputs:
        if not isinstance(inp, dict):
            continue
        name, sql = inp.get("name"), inp.get("sql")
        try:
            cols = ", ".join(f"{c} ({t})" for c, t in input_columns(bundle, str(sql)))
        except QueryError as exc:
            cols = f"(columns unknown: {exc})"
        lines.append(f"- data.inputs.{name}: SQL `{sql}` → columns: {cols}")
    return "\n".join(lines) or "- (no inputs)"


_FENCE = re.compile(r"```[ \t]*([A-Za-z]*)[^\n]*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """The code from a model answer: the fenced block containing `export default` (else the largest), else the text."""
    blocks = [m.group(2) for m in _FENCE.finditer(text or "")]
    if blocks:
        with_export = [b for b in blocks if "export default" in b]
        code = (with_export or sorted(blocks, key=len, reverse=True))[0]
    else:
        code = (text or "").strip()
        if code.startswith("```"):  # unterminated fence
            code = code.split("\n", 1)[1] if "\n" in code else ""
    code = code.strip()
    if "export default" not in code:
        raise WidgetCodeError("the code model returned no component with `export default`")
    return code + "\n"


def build_messages(
    bundle: Bundle, description: str, inputs: list[dict], previous_code: str | None, errors: list[str] | None
) -> list[dict]:
    parts = [
        f"Widget request:\n{description.strip()[:MAX_DESCRIPTION]}",
        f"Inputs (resolved by the server; `$selected` = first selected key or NULL):\n{_describe_inputs(bundle, inputs)}",
    ]
    if previous_code:
        parts.append(f"Current code of this widget (change it as requested):\n```tsx\n{previous_code}\n```")
    if errors:
        parts.append("Your previous code was rejected:\n" + "\n".join(f"- {e}" for e in errors) + "\nFix it.")
    return [{"role": "system", "content": WIDGET_CODE_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


def make_code_writer(
    bundle: Bundle, provider: Any, model: str | None, fallback_model: str | None = None
) -> CodeWriter:
    """A `CodeWriter` that asks the code model (no tools) for the widget code.

    When the provider has `chat_text` (the real one), the answer is **streamed** with low-reasoning hints
    (`CODE_EXTRA_BODY`): a slow but steady answer is not cut
    by a read timeout, only `CODE_STREAM_IDLE` s without a chunk or `CODE_STREAM_MAX` s in total end it. Otherwise
    `provider.chat` is used, bounded (`CODE_MODEL_TIMEOUT`, no retry, when the provider supports `with_timeout`). If the
    code model fails, the chat model (`fallback_model`, None = provider default) writes the code the same way (fallback
    total `CODE_FALLBACK_MAX` s), so a slow code model cannot stall a live demo.
    """
    bounded = provider.with_timeout(CODE_MODEL_TIMEOUT) if hasattr(provider, "with_timeout") else provider

    def ask(messages: list[dict], m: str | None, max_seconds: float) -> str:
        if hasattr(provider, "chat_text"):
            return provider.chat_text(
                messages, model=m, max_seconds=max_seconds, idle_seconds=CODE_STREAM_IDLE, extra_body=CODE_EXTRA_BODY
            )
        return bounded.chat(messages, [], model=m).text

    def write(description: str, inputs: list[dict], previous_code: str | None, errors: list[str] | None) -> str:
        messages = build_messages(bundle, description, inputs, previous_code, errors)
        write.used_fallback = False  # type: ignore[attr-defined]
        try:
            text = ask(messages, model, CODE_STREAM_MAX)
        except Exception as exc:  # noqa: BLE001 – LLMError or a broken provider
            first = f"the code model could not be reached: {str(exc)[:200]}"
            if model is None or model == fallback_model:
                raise WidgetCodeError(first, unreachable=True) from None
            try:
                text = ask(messages, fallback_model, CODE_FALLBACK_MAX)
            except Exception as exc2:  # noqa: BLE001
                raise WidgetCodeError(
                    f"{first}; the chat model also failed: {str(exc2)[:200]}", unreachable=True
                ) from None
            write.used_fallback = True  # type: ignore[attr-defined]
        return extract_code(text)

    write.used_fallback = False  # type: ignore[attr-defined]
    return write
