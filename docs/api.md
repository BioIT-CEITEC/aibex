# API and internal contracts (v1)

These contracts are what the acceptance tests (`backend/tests/acceptance/`, `frontend/e2e/`) check.
Change them only together with the tests and this file.

## App factory and settings
- `aibex.config.Settings` – dataclass; fields at least `data_dir: Path`, `frontend_dist: Path`, `llm_base_url`, `llm_api_key`,
  `llm_model_fast`, `llm_model_code`, `llm_provider: str` (env `LLM_PROVIDER`, values `openai` (default) | `fake`).
- `aibex.main.create_app(settings: Settings | None = None, llm_provider: LLMProvider | None = None) -> FastAPI`.
  `aibex.main.app = create_app()` stays for uvicorn. Tests build their own app with a temp data dir and a scripted provider.

## LLM provider (`aibex/llm/provider.py`)
```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

class LLMProvider(Protocol):
    def chat(self, messages: list[dict], tools: list[dict], model: str | None = None) -> LLMResponse: ...
```
- `OpenAICompatibleProvider` – e-INFRA / any OpenAI-compatible endpoint. If the model returns no tool call, parse a
  JSON object `{"tool": "<name>", "arguments": {...}}` or `{"patch": [...], "summary": "..."}` from the text (fallback).
- `FakeProvider` (`LLM_PROVIDER=fake`) – deterministic, no network, used by e2e tests and offline demos. Rules on the
  last user message (case-insensitive):
  - `label <G1>[, <G2> ...]` → `update_view` replacing `label.values` of the first `plot` panel of kind `scatter`
  - `padj below <x>` → `update_view` adding filter `{"id": "padj-lt", "table": <table of first scatter>, "field": "padj", "op": "<", "value": x, "enabled": true}`
  - `undo` / `undo <n>` → `undo_view` with steps n (default 1)
  - `add widget` → `create_widget` with a tiny TSX widget showing the row count of its input
  - anything else → text reply "FakeProvider: no rule matched", no change
- Messages use OpenAI chat format; tool results are appended as `{"role": "tool", "tool_call_id": ..., "content": <json string>}`.

## Chat loop (`aibex/llm/chat.py`)
- Tools exposed to the LLM: `describe_bundle()`, `query_data(sql)`, `update_view(patch, summary)`, `undo_view(steps)`,
  `create_widget(id, title, inputs, code)`.
- Max 8 provider calls per user message. A failed `update_view` / `create_widget` returns the validation errors to the LLM
  as the tool result; after **2 failed attempts in a row** the loop stops with an `error` event and the spec is unchanged.
- Privacy rule: no tool result may contain more than **200 rows**; `describe_bundle` returns schema + summary stats only.
  The provider must never receive whole tables.

## REST endpoints (all JSON, prefix `/api`)
| method | path | body | response |
|---|---|---|---|
| GET | `/health` | – | `{status, version, llm_configured, llm_models, data_dir_exists}` |
| GET | `/bundles` | – | `[{id, title, modalities, tables}]` |
| GET | `/bundles/{id}/schema` | – | `{id, title, organism?, tables: {name: {description, key, row_count, columns: {col: {type, description?}}}}, links: [{from, to}]}` |
| POST | `/bundles/{id}/query` | `{sql, limit?}` | `{columns, rows, row_count, truncated}` – read-only single SELECT/WITH; default limit 200, max 5000; else **400** |
| GET | `/bundles/{id}/default-view` | – | a valid spec (from `default_view` in bundle.yaml or generated) |
| POST | `/sessions` | `{bundle}` | `{session_id, spec, version: 0}` (404 unknown bundle) |
| GET | `/sessions/{sid}` | – | `{session_id, spec, version, history: [{version, summary, source}]}` (`source`: `init`/`user`/`llm`) |
| POST | `/sessions/{sid}/patch` | `{patch, summary?}` | `{spec, version}`; invalid → **422** `{detail: {errors: [...]}}`, version unchanged |
| POST | `/sessions/{sid}/undo` | `{steps?: 1}` | `{spec, version}` |
| POST | `/sessions/{sid}/redo` | `{steps?: 1}` | `{spec, version}` |
| POST | `/sessions/{sid}/chat` | `{message}` | SSE stream (default) or, with `?stream=false`, `{reply, spec, version, events}` |
| POST | `/sessions/{sid}/panel-data` | `{panel_id, selection?: [keys]}` | `{columns, rows, truncated}` – filters applied, max 5000 rows |
| POST | `/validate-spec` | spec | `{valid: bool, errors: [...]}` |

`version` increases by 1 with every applied change (patch, chat change, undo, redo).
SSE event types: `token` `{text}`, `tool` `{name, status}`, `spec` `{spec, version, summary}`, `error` `{message}`, `done` `{}`.
The non-stream response's `events` is the list of the same events.

## Panel data shape
- `plot` panels return columns `x`, `y` (when defined), plus `color`, `size`, `label` when set, plus the table key column
  (named as in the bundle, e.g. `gene_id`). `expr` axes are evaluated server-side.
- `table` panels return the listed columns, sorted as specified.
- `widget` panels return `{inputs: {name: {columns, rows}}}` instead; `$selected` in input SQL is bound to the first selected key.

## Spec validation rules (422 / `valid: false` when violated)
- panel ids unique, kebab-case; every panel has exactly one layout item and every layout item a panel
- `table` / `field` references must exist in the bundle schema (`expr` columns too)
- `expr` uses only column names, numbers, `+ - * / ( )` and functions log, log2, log10, ln, abs, sqrt, round, least, greatest, coalesce
- widget `code` ≤ 50 000 characters; must not contain `fetch(`, `XMLHttpRequest`, `WebSocket`, `importScripts`, `document.cookie`, `localStorage`

## Frontend test ids (used by Playwright e2e)
`bundle-select`, `panel-<id>`, `filter-<id>` (checkbox), `table-<id>` (rows are `tbody tr`), `chat-input`, `chat-send`,
`chat-message` (assistant messages), `spec-version` (text = current version number), `history-item`, `undo-button`,
`redo-button`, `widget-frame-<id>` (the iframe; attribute `sandbox="allow-scripts"` exactly), `error-banner`.
