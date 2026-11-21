# API and internal contracts (v1)

These contracts are what the acceptance tests (`backend/tests/acceptance/`, Playwright e2e in `frontend-e2e/e2e/`,
moved to `frontend/e2e/` by task T16b) check. Change them only together with the tests and this file.
Decisions behind some rules are recorded as Q1–Q9 in the `PROGRESS.md` Log.

## App factory and settings
- `aibex.config.Settings` – dataclass; fields at least `data_dir: Path`, `frontend_dist: Path`, `llm_base_url`, `llm_api_key`,
  `llm_model_fast`, `llm_model_code`, `llm_provider: str` (env `LLM_PROVIDER`, values `openai` (default) | `fake`).
- `aibex.main.create_app(settings: Settings | None = None, llm_provider: LLMProvider | None = None) -> FastAPI`.
  `aibex.main.app = create_app()` stays for uvicorn. Tests build their own app with a temp data dir and a scripted provider.
  Precedence: an injected `llm_provider` wins; otherwise `settings.llm_provider` selects `OpenAICompatibleProvider` or `FakeProvider`.

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
  JSON object `{"tool": "<name>", "arguments": {...}}` or `{"patch": [...], "summary": "..."}` from the text (fallback;
  a fenced ```` ```json ```` block or a bare object). The `{"patch": ...}` form means `update_view`. The fallback is applied
  by the chat loop, so it works for every provider.
- `FakeProvider` (`LLM_PROVIDER=fake`) – deterministic, no network, used by e2e tests and offline demos. Rules on the
  last user message (case-insensitive):
  - `label <G1>[, <G2> ...]` → `update_view` replacing `label.values` of the first `plot` panel of kind `scatter`
  - `padj below <x>` → `update_view` adding filter `{"id": "padj-lt", "table": <table of first scatter>, "field": "padj", "op": "<", "value": x, "enabled": true}`
  - `undo` / `undo <n>` → `undo_view` with steps n (default 1)
  - `add widget` → `create_widget` id `row-count`, one input `{"name": "rows", "sql": "SELECT * FROM <first table of the bundle> LIMIT 50"}`, a tiny TSX widget showing the row count of that input
  - anything else → text reply "FakeProvider: no rule matched", no change
  - after a tool result it answers with a short text ("FakeProvider: done") so the loop ends.
- Messages use OpenAI chat format; tool results are appended as `{"role": "tool", "tool_call_id": ..., "content": <json string>}`.

## Chat loop (`aibex/llm/chat.py`)
- Tools exposed to the LLM: `describe_bundle()`, `query_data(sql)`, `update_view(patch, summary)`, `undo_view(steps)`,
  `create_widget(id, title, inputs, code)`.
- Tool results (JSON strings):
  - `describe_bundle` → schema (as `GET /bundles/{id}/schema`) plus per-column summary stats: `n_null`; numeric
    `min`, `max`, `mean`; string `n_distinct` and at most 10 example values. Never rows.
  - `query_data` → `{columns, rows, row_count, truncated}`, at most **200** rows.
  - `update_view` / `create_widget` / `undo_view` → `{"ok": true, "version": n}` or `{"ok": false, "errors": [...]}`.
- Context sent with each call: system prompt (rules, spec-format summary), bundle schema, current spec with a panel index
  (`id → index`), the last few turns.
- Max **8** provider calls per user message; when the cap is hit the loop stops with an `error` event ("step limit").
- A failed `update_view` / `create_widget` returns the validation errors to the LLM as the tool result; after
  **2 failed attempts in a row** the loop stops with an `error` event (no further provider call) and the spec is unchanged
  by the failed calls.
- Each applied `update_view` / `create_widget` / `undo_view` is one new version with `source: "llm"` (decided, Q6).
- Privacy rule: no tool result may contain more than **200 rows**; `describe_bundle` returns schema + summary stats only.
  The provider must never receive whole tables.

## REST endpoints (all JSON, prefix `/api`)
| method | path | body | response |
|---|---|---|---|
| GET | `/health` | – | `{status, version, llm_provider, llm_configured, llm_models, data_dir_exists}` |
| GET | `/bundles` | – | `[{id, title, modalities, tables}]`; an entry with a broken bundle.yaml is `{id, error}` |
| GET | `/bundles/{id}/schema` | – | `{id, title, organism?, tables: {name: {description, key, row_count, columns: {col: {type, description?}}}}, links: [{from, to}]}` (404 unknown bundle; 500 `{detail}` with the reason when the bundle cannot be loaded, e.g. missing file, declared column/key/link column not in the data) |
| POST | `/bundles/{id}/query` | `{sql, limit?}` | `{columns, rows, row_count, truncated}` – read-only single SELECT/WITH, else **400** |
| GET | `/bundles/{id}/default-view` | – | a valid spec (from `default_view` in bundle.yaml or generated) |
| GET | `/bundles/{id}/views` | – | `[{name, title}]` saved views (Phase 5) |
| POST | `/bundles/{id}/views` | `{name, spec}` | `{name}`; spec validated (422), name kebab-case (Phase 5) |
| POST | `/sessions` | `{bundle}` | `{session_id, spec, version: 0}` (404 unknown bundle) |
| GET | `/sessions/{sid}` | – | `{session_id, spec, version, history: [{version, summary, source}]}` (`source`: `init`/`user`/`llm`) |
| POST | `/sessions/{sid}/patch` | `{patch, summary?}` | `{spec, version}`; invalid → **422** `{detail: {errors: [...]}}`, version unchanged |
| POST | `/sessions/{sid}/undo` | `{steps?: 1}` | `{spec, version}`; nothing to undo → **409**, version unchanged |
| POST | `/sessions/{sid}/redo` | `{steps?: 1}` | `{spec, version}`; nothing to redo → **409**, version unchanged |
| POST | `/sessions/{sid}/load-view` | `{name}` | `{spec, version}` – loads a saved view as a new, undoable version (Phase 5) |
| POST | `/sessions/{sid}/chat` | `{message}` | SSE stream (default) or, with `?stream=false`, `{reply, spec, version, events}` |
| POST | `/sessions/{sid}/panel-data` | `{panel_id, selection?: [keys]}` | `{columns, rows, truncated}` – filters applied, max 5000 rows; unknown panel **404** |
| POST | `/validate-spec` | spec | `{valid: bool, errors: [...]}` |

Unknown session id → **404** everywhere.

### Query details
- `rows` is a list of arrays aligned with `columns` (same for panel data and widget inputs).
- `limit` defaults to 200; values above 5000 are clamped to 5000. `truncated` is true when more rows exist than returned.
  `row_count` is the total row count of the unlimited query.
- Read-only guard: exactly one statement, of type SELECT (incl. WITH); no file/network table functions (`read_csv`,
  `read_parquet`, `glob`, …), no `ATTACH`, `COPY`, `PRAGMA`, `INSTALL`, `LOAD`, `SET`. Defence in depth: bundle tables are
  exposed from a connection with external access disabled and configuration locked after setup.

### Versions and history
`version` (session counter, not the spec's own `"version": 1` format field) increases by 1 with every applied change
(patch, chat change, undo, redo, load-view). History is an undo stack with a pointer: undo/redo move the pointer by
`steps` and record a new version; a new change after an undo drops the redo part. `history` lists every applied version
in order (`summary` for undo/redo e.g. "undo 2").

### Chat events
SSE event types: `token` `{text}`, `tool` `{name, status}`, `spec` `{spec, version, summary}`, `error` `{message}`, `done` `{}`.
SSE frames are `event: <type>\ndata: <json payload>\n\n`. The non-stream response's `events` is the list of the same
events as objects `{"type": <type>, ...payload}`; `reply` is the final assistant text (or the error message).

## Panel data shape
- `plot` panels return columns `x`, `y` (when defined), plus `color`, `size`, `label` when set, plus the table key column
  (named as in the bundle, e.g. `gene_id`). `expr` axes are evaluated server-side.
- `pca` panels return `x` (PC1), `y` (PC2), `sample`, plus the `samples.tsv` columns, and extra keys `x_label`, `y_label`
  with the explained variance (e.g. `"PC1 (42 %)"`).
- `heatmap` panels return long format: columns `row`, `column`, `value`, `group` (sample group from `group_by`, or null).
- `table` panels return the listed columns, sorted as specified.
- `widget` panels return `{inputs: {name: {columns, rows, truncated}}}` instead; each input max 5000 rows; `$selected` in
  input SQL is bound (as a parameter, never string-formatted) to the first selected key, or NULL when nothing is selected.

## Filters
- A filter is either `{id, table, field, op, value, label?, enabled}` or `{id, table, expr, label?, enabled}` where `expr`
  is a boolean expression (grammar below), e.g. `abs(log2FoldChange) > 1`.
- A filter applies to every panel whose table is the filter's `table`, and also to panels whose table is joined to the
  filter's table by a bundle `link` (semi-join on the link key), so "everywhere" filters reach e.g. the counts heatmap
  and the editing panels (decided, Q2). Links are followed in both directions, one hop.

## Spec validation rules (422 / `valid: false` when violated)
- panel ids unique, kebab-case; every panel has exactly one layout item and every layout item a panel
- structural (`aibex/spec.py`): unknown fields are rejected (typos become repairable errors); filter ids unique and
  kebab-case; axis/`color`/`size` have exactly one of `field`/`expr`; `color` has `palette` or `colorscale`, not both;
  filter `between` needs `[min, max]`, `in` a non-empty list, `contains` a string; layout items fit the 12-column grid
  (`x + w ≤ 12`, `w,h ≥ 1`; react-grid-layout flags `static`/`moved`/`min*`/`max*` allowed); `pca` scale `none|log1p`,
  `heatmap` needs `rows`; widget `language` is `tsx` (default) or `jsx`
- `table` / `field` references must exist in the bundle schema (`expr` columns too); filter `field`s too; also
  `label.field`/`label.by`, `facet`, table `columns`/`sort`, and `selection.key` (a column of at least one table)
- semantic (`aibex/validate.py`): `pca`/`heatmap` tables must be matrix tables (≥ 2 numeric sample columns, matched
  to `samples.tsv` names when present); pca `color.field` and heatmap `group_by` are `samples.tsv` columns; heatmap
  `rows.by` is `<table>.<column>` of the matrix table or a table linked to it; `spec.bundle` must be the bundle validated
  against. `expr` columns match case-insensitively (as in DuckDB) and each `expr` is type-checked by a `LIMIT 0` dry run
  of the compiled SQL (`aibex/expr.py` rebuilds the SQL from tokens; the raw string never runs)
- `POST /validate-spec` always answers 200; an unknown or unloadable bundle is reported as an error (`valid: false`)
- `expr` grammar (decided, Q1): column names, numbers, single-quoted string literals, `NULL`, `TRUE`, `FALSE`, unary minus,
  `+ - * / ( )`, comparisons `< <= > >= = != <>`, `AND OR NOT`, `IS [NOT] NULL`, `CASE WHEN … THEN … [ELSE …] END`, and the
  functions log, log2, log10, ln, abs, sqrt, round, least, greatest, coalesce. Nothing else (no subqueries, no other
  functions, no casts, no `;`). Validate by parsing (e.g. a small tokenizer + allow-list), never by regex on the whole string.
- widget `code` ≤ 50 000 characters; must not contain `fetch(`, `XMLHttpRequest`, `WebSocket`, `importScripts`, `document.cookie`, `localStorage`
- widget input `sql` must pass the read-only query guard
- `plotly` overrides are plain JSON (no functions)

## Default view (generated when bundle.yaml has no `default_view`)
- ≥4 panels, at least one scatter and one table; validates.
- The **first plot panel** (in panel order) is a volcano-like scatter of the DE table with `label: {field: <name column>, values: []}`.
- Column roles (fold change, adjusted p-value, mean expression, gene name) are found by common names
  (DESeq2 / edgeR / limma); never hard-coded in the frontend.

## Level 2 widget runtime
- Rendered as `<iframe sandbox="allow-scripts" srcdoc="…">` (exactly `allow-scripts`, never `allow-same-origin`).
- The srcdoc starts with `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline';
  style-src 'unsafe-inline'; img-src data: blob:">` – the sandbox alone does not block network access.
- React and Plotly (decided, Q8; use a minified dist such as `plotly.js-basic-dist-min`) are inlined into the srcdoc
  (no CDN – the CSP forbids it); the widget gets them as `React` and `Plotly`. The parent compiles TSX (sucrase) and sends
  code + data via `postMessage`; the widget calls `onSelect(keys)` which is posted back to the parent.
- `create_widget` defaults `language` to `tsx`; a new panel is appended to the layout at the bottom (`w: 6, h: 8`).
  Same id as an existing widget replaces that widget (new version); same id as a non-widget panel is an error.

## Frontend conventions
- `/?bundle=<id>` selects the bundle; every page load creates a new session (version 0). Without the parameter the
  first bundle is used.
- Test ids (used by Playwright e2e):
  `bundle-select`, `panel-<id>`, `filter-<id>` (checkbox), `table-<id>` (rows are `tbody tr`), `chat-input`, `chat-send`,
  `chat-message` (assistant messages), `spec-version` (text = current version number), `history-item`, `undo-button`,
  `redo-button`, `widget-frame-<id>` (the iframe; attribute `sandbox="allow-scripts"` exactly), `error-banner`.
- Toggling a filter checkbox or dragging/resizing a panel sends a patch with `source: "user"` (a new, undoable version).
