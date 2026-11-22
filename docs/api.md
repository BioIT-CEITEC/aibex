# API and internal contracts (v1)

These contracts are what the acceptance tests (`backend/tests/acceptance/`, Playwright e2e in `frontend/e2e/`)
check. Change them only together with the tests and this file.
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
  - Implementation (T21b, `aibex/llm/fake.py`): it sees only `messages`, so it reads the current spec and bundle schema
    from the context: any JSON object (fenced ```` ```json ```` block or bare, possibly nested such as
    `{"spec": {...}, "schema": {...}}`) in a system/user message, newest message first; a spec is an object with
    `bundle` + a `panels` list, a schema an object with a `tables` object. **The chat loop (T22b/T23) must embed the
    current spec and the schema as JSON in that way.** Without them the label/padj/widget rules reply "no rule matched…"
    with a reason. Details: gene names split on commas/whitespace/"and", case kept; a second `padj below` replaces
    filter `padj-lt`; if the first scatter has no `label` object one is added with `selection.key` as field; `undo`
    must be the whole message (`undo`, `undo 3`). Tool-call ids `fake-<n>`.
- Selection: `provider_from_settings(settings)` in `provider.py`; `create_app` uses it unless a provider is injected.
- Implementation (T21a): `parse_text_fallback(text) -> list[ToolCall]` (ids `fallback-<n>`, never raises) and
  `with_text_fallback(response)` for the chat loop; the provider itself does not apply it. Tool-call arguments that are
  not a JSON object become `{"_invalid_arguments": "<raw>"}` so the tool can report the error to the model. Any SDK or
  network failure raises `LLMError` (readable message, no secrets). `OpenAICompatibleProvider.from_settings(settings)`
  uses `llm_base_url`, `llm_api_key`, `llm_model_fast`; `chat(..., model=...)` overrides the model (e.g. the code model);
  `temperature=0`, `tool_choice="auto"` when tools are given, SDK `max_retries=1`, timeout 120 s.
- Messages use OpenAI chat format; tool results are appended as `{"role": "tool", "tool_call_id": ..., "content": <json string>}`.

## Chat loop (`aibex/llm/chat.py`)
- Tools exposed to the LLM: `describe_bundle()`, `query_data(sql)`, `update_view(patch, summary)`, `undo_view(steps)`,
  `create_widget(id, title, inputs, description | code)`.
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
- Implementation (T40b) of `create_widget(id, title, inputs, code[, language])`: builds a `widget` panel and applies it
  as one JSON Patch through the normal session validation (so code size/blocklist, read-only input SQL, `$selected`
  only and the `LIMIT 0` dry run all apply). New id → `add /panels/-` + `add /layout/-` with `{x: 0, y: <bottom of the
  grid>, w: 6, h: 8}`, summary `add widget <id>`; id of an existing widget → `test` + `replace /panels/<i>` (layout
  kept, an empty title keeps the old title), summary `replace widget <id>`; id of a non-widget panel → error. Result
  `{"ok": true, "version": n, "panel_id": id}`. `inputs` may be omitted (= `[]`) or double-encoded as a JSON string.
  Undo is the normal session undo.
- Implementation (T42, `aibex/llm/widget_code.py`): `create_widget(id, title, inputs, description?, code?[,
  language])` – `code` is optional now. Without `code` but with `description`, the **code model** (`llm_model_code`)
  writes the TSX: the inputs are checked first (guard + dry run; errors go back to the chat model without calling the
  code model), then one `provider.chat(messages, tools=[], model=llm_model_code)` with a widget-code system prompt
  (runtime contract) and a user message with the description, each input's name, SQL and result columns/types (from
  `LIMIT 0` – no rows) and, when a widget is replaced, its current code. The code is taken from the fenced block with
  `export default` (else the text). Code rejected by the validation (only `.code` errors) is sent back to the code
  model once with the errors. Result adds `"code_by": "code model"`. The description is not stored in the spec. An
  explicit `code` wins (FakeProvider still passes code). `chat_events`/`run_chat` take `code_model`; `/chat` passes
  `settings.llm_model_code`. The code-model call is **streamed** (`OpenAICompatibleProvider.chat_text`, no tools, no
  retry) with low-reasoning hints in the request body (`reasoning_effort: "low"`,
  `chat_template_kwargs.enable_thinking: false`, `CODE_EXTRA_BODY`): without them the e-INFRA reasoning models streamed
  >30 000 reasoning chars and no code within 150 s. Limits: 60 s without a chunk, 150 s in total (code model) / 90 s
  (fallback). Providers without `chat_text` get one bounded `chat` call (90 s, no retry, `with_timeout`). When the code
  model fails or times out, the chat model writes the code from the same messages and the result says
  `"code_by": "chat model (the code model failed)"`. Only when both fail (time-out/network) is the `create_widget`
  rejected, and then the chat loop stops at once with an `error` event ("The widget could not be written: …"; nothing
  changed) instead of letting the chat model retry, which would double the wait. A code answer without a component
  (no `export default`) is an ordinary failed attempt. The widget-code prompt also names the mistakes the live model
  made on ADAR2: rows (even of a one-row input) are arrays, so read them via `columns.indexOf`; trace x/y are flat
  arrays (`null` between line segments); subplot axes need `domain` + `anchor`; about 150 lines at most. Visual check
  without an LLM call: the live test saves the widget to `logs/widgets/live-widget-editing-adar2.json`, and
  `make e2e E2E_REAL_DATA=<data dir> ARGS=e2e/real-adar2-widget.spec.ts` renders it on ADAR2 with a gene selected.
- Implementation (T22a, `aibex/llm/tools.py`): `TOOL_SCHEMAS` (OpenAI function definitions), plain functions `describe_bundle(bundle)`, `query_data(bundle, sql)`,
  `update_view(session, patch, summary)`, `undo_view(session, steps)` and the dispatcher
  `run_tool(session, name, arguments) -> ToolOutcome(name, result, changed, failed_change, summary)`; `content()` is
  the JSON string for the tool message. Tools never raise: errors are `{"ok": false, "errors": [...]}`.
  `failed_change` is set only for rejected `update_view`/`create_widget` (incl. invalid/missing arguments) – that is
  what the "2 failures in a row" rule counts; failed `query_data`/`undo_view` do not count. `describe_bundle` adds
  `columns.<col>.stats` (`n_null`; int/float `min`/`max`/`mean`; date `min`/`max`; bool `n_true`; string `n_distinct`
  + ≤10 most frequent `examples`, cut at 80 chars), `matrix: true` on genes × samples tables, and `samples`
  (`n`, ≤10 distinct values per samples.tsv column). `query_data` adds `note` when truncated. `update_view` accepts a
  double-encoded patch string or a single op object; an empty summary falls back to the op list.
- Implementation (T22b, `aibex/llm/chat.py`): `chat_events(session, provider, message)` yields event dicts and always
  ends with `done`; `run_chat` collects them (non-stream response), `sse_frame` formats them. Each provider call gets
  one `system` message = system prompt + a fenced ```` ```json ```` block `{"schema", "spec", "panel_index"}` rebuilt
  from the *current* spec (so it is fresh after a change), then the last 6 chat messages of the session
  (`Session.chat`, plain user/assistant text), then this turn (user message, assistant `tool_calls` messages in OpenAI
  format, tool results). `with_text_fallback` is applied to every response. Event order per tool call: `tool`
  `{status: "running"}`, `tool` `{status: "ok"|"error"}`, then `spec` if it applied a change; the final text is one
  `token` event. "2 failures in a row": an applied change resets the count; failed `query_data`/`describe_bundle`/
  `undo_view` neither count nor reset; two rejected calls in one response also stop. At the step limit, changes
  applied earlier in the turn are kept (undoable). Provider errors (`LLMError` or any exception) → `error` event.
  `message` must be 1–8000 characters (else 422).
- System prompt (T23, `aibex/llm/prompts.py`): `SYSTEM_PROMPT` = role, tools, a compact summary of
  docs/spec-format.md (filters, plot/pca/heatmap/table/text panels, `expr` grammar, layout, plotly overrides),
  rules (schema columns only, minimal changes, never invent data, ask when unclear, short plain-text answer, JSON
  fallback). The system message is the prompt + `# Current panels` (one line per panel: `index: id (type/kind,
  table) "title"`, `panel_index_text`) + the fenced JSON `{schema, spec, panel_index}`. The prompt itself contains no
  ``` fences. `tests/test_prompts.py` keeps it in sync (tool names, expr function allow-list, examples validate).
  **Update the prompt when docs/spec-format.md changes**. `create_widget` (T40b) is described there as a last resort
  when no plot/table/text panel fits, with the input/`$selected`/`data.inputs.<name>` contract.
- SSE: `StreamingResponse` (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`); events are sent
  as they happen (tool/spec per step). The final reply is one `token` event (no per-token streaming from the provider
  yet).

## REST endpoints (all JSON, prefix `/api`)
| method | path | body | response |
|---|---|---|---|
| GET | `/health` | – | `{status, version, llm_provider, llm_configured, llm_models, data_dir_exists}` |
| GET | `/bundles` | – | `[{id, title, modalities, tables}]`; an entry with a broken bundle.yaml is `{id, error}` |
| GET | `/bundles/{id}/schema` | – | `{id, title, organism?, tables: {name: {description, key, row_count, columns: {col: {type, description?}}}}, links: [{from, to}]}` (404 unknown bundle; 500 `{detail}` with the reason when the bundle cannot be loaded, e.g. missing file, declared column/key/link column not in the data) |
| POST | `/bundles/{id}/query` | `{sql, limit?}` | `{columns, rows, row_count, truncated}` – read-only single SELECT/WITH, else **400** |
| GET | `/bundles/{id}/default-view` | – | a valid spec (from `default_view` in bundle.yaml or generated) |
| GET | `/bundles/{id}/views` | – | `[{name, title}]` saved views (Phase 5) |
| POST | `/bundles/{id}/views` | `{name, spec, title?}` | `{name}`; spec validated (422), name kebab-case (Phase 5) |
| POST | `/sessions` | `{bundle}` | `{session_id, spec, version: 0}` (404 unknown bundle) |
| GET | `/sessions/{sid}` | – | `{session_id, spec, version, history: [{version, summary, source}], can_undo, can_redo}` (`source`: `init`/`user`/`llm`; `can_undo`/`can_redo` = steps available) |
| POST | `/sessions/{sid}/patch` | `{patch, summary?}` | `{spec, version}`; invalid → **422** `{detail: {errors: [...]}}`, version unchanged |
| POST | `/sessions/{sid}/undo` | `{steps?: 1}` | `{spec, version}`; nothing to undo → **409**, version unchanged |
| POST | `/sessions/{sid}/redo` | `{steps?: 1}` | `{spec, version}`; nothing to redo → **409**, version unchanged |
| POST | `/sessions/{sid}/load-view` | `{name}` | `{spec, version}` – loads a saved view as a new, undoable version (Phase 5) |
| POST | `/sessions/{sid}/chat` | `{message}` | SSE stream (default) or, with `?stream=false`, `{reply, spec, version, events}` |
| POST | `/sessions/{sid}/panel-data` | `{panel_id, selection?: [keys]}` | `{columns, rows, truncated}` – filters applied, max 5000 rows (plot panels 40 000); unknown panel **404** |
| POST | `/validate-spec` | spec | `{valid: bool, errors: [...]}` |

Unknown session id → **404** everywhere.

### Saved views (T51, `aibex/views.py`)
- Stored as plain specs in `<bundle>/views/<name>.json` (docs/bundle-format.md), written atomically. Saving under an
  existing name overwrites it. Name: kebab-case `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, max 64 chars, else **422**.
- `POST /bundles/{id}/views`: the spec is validated like `/validate-spec` (422 `{detail: {errors}}`); `spec.bundle`
  must be the bundle id (or missing). Optional `title` (1–200 chars) is stored as the spec's `title`. The file the
  bundle names as `default_view` cannot be overwritten (422). A write error (read-only data dir) is **500**.
- `GET /bundles/{id}/views`: `[{name, title}]` sorted by name; `title` = the spec's title (else the name). Files with
  a non-kebab name or unreadable JSON are skipped.
- `POST /sessions/{sid}/load-view`: applies the view via `replace_spec` as one version, summary `load view <name>`,
  source `user` (undoable). Unknown view **404**; invalid name or a stored spec that no longer validates **422**,
  version unchanged.

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
Implementation `aibex/sessions.py` (in memory, lost on restart, oldest dropped beyond 200 sessions): the initial entry
is `{version: 0, summary: "initial view", source: "init"}`; `POST /patch` records `source: "user"` (default summary
lists the ops); `steps` must be ≥ 1 (else 422) and is clamped to what can be undone/redone (`undo 5` with 2 changes
undoes 2); 409 only when nothing at all can be undone/redone. The undo/redo body may be omitted (steps 1).
A patch is applied to a copy and the result is validated structurally + semantically (as `/validate-spec`); a patch
that cannot be applied (bad path, failed `test` op) is also a 422 with readable errors.

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
- Implementation details (`aibex/panel_data.py`): plot `label` holds the label text for rows to be labelled
  (`values` matched case-insensitively, or the `top_n` rows ascending by `by` among the filtered rows), else null;
  plot panels are capped at **40 000** rows (T34, Q11 proposed default; tables and widget inputs stay at 5000):
  labelled rows come first, then rows ascending by `label.by` when set, else by the table's adjusted p-value / p-value
  column (same common names as the default view; nulls last), then by the key – so a cap drops the least interesting
  rows; `facet` is returned as column `facet` when set.
  Plot panels on a table that has the spec's `selection.key` as a non-key column (e.g. `gene_id` on editing sites, key
  `site_id`) also return that column, placed before the table key, so their points take part in the linked selection
  (T32; only when `selection.linked`).
  Table panels append the table key column at the end when it is not listed (needed for linked selection); rows are
  ordered by the key after the spec's `sort`. `text` panels return empty data. `pca`/`heatmap`
  (`aibex/matrix_panels.py`): filters reach the matrix rows like any panel; PCA drops rows with a missing value, scales,
  keeps the `top_n` most variable rows, centres them and projects the samples (columns in samples.tsv order; PC sign
  fixed so the largest loading is positive; fewer than 2 varying rows → 400). Heatmap `row` is the matrix key; explicit
  `values` match the key case-insensitively and keep their order; `top_n` ranks by `min(<by column>)` per linked key,
  ties by key; `row-z` uses the sample SD (SD 0 → 0); columns are grouped by `group_by` (first appearance) keeping
  samples.tsv order; only whole rows fit under the 5000-row cap (`truncated: true`). `selection` is accepted for
  every panel but only used by widget inputs. A failing panel query (incl. a failing widget input) answers
  **400** `{detail}`. In `expr`, `log`/`log2`/`log10`/`ln` of values ≤ 0 and `sqrt` of negative values
  give null instead of a DuckDB error (e.g. `-log10(padj)` with `padj = 0`).
- `widget` panels return `{inputs: {name: {columns, rows, truncated}}}` instead; each input max 5000 rows; `$selected` in
  input SQL is bound (as a parameter, never string-formatted) to the first selected key, or NULL when nothing is selected.
  Implementation `aibex/widgets.py` (T40a): inputs run through the read-only guard (`run_query`); spec filters do not
  apply to widget inputs (free-form SQL – the widget's SQL decides what it shows).

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
- widget input `sql` must pass the read-only query guard, use no parameter other than `$selected` (no `?`, `$1`,
  `$other`), and bind in a `LIMIT 0` dry run against the bundle (unknown tables/columns are reported)
- `plotly` overrides are plain JSON (no functions)

## Default view (generated when bundle.yaml has no `default_view`)
- ≥4 panels, at least one scatter and one table; validates.
- The **first plot panel** (in panel order) is a volcano-like scatter of the DE table with `label: {field: <name column>, values: []}`.
- Column roles (fold change, adjusted p-value, mean expression, gene name) are found by common names
  (DESeq2 / edgeR / limma); never hard-coded in the frontend.
- Implementation `aibex/default_view.py`: panels `volcano`, `ma-plot` (when a mean column exists), `pca` + `top-genes`
  heatmap (when a matrix table exists; heatmap only if linked to the DE table), `genes` table; histograms fill up to 4
  panels. A bundle `default_view` file is used only if it lies inside the bundle and validates, else the generated view
  is served (a warning is logged). Bundles without a DE-like table get a generic scatter/histogram/table view.

## Level 2 widget runtime
- Rendered as `<iframe sandbox="allow-scripts" srcdoc="…">` (exactly `allow-scripts`, never `allow-same-origin`).
- The srcdoc starts with `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline';
  style-src 'unsafe-inline'; img-src data: blob:">` – the sandbox alone does not block network access.
- React and Plotly (decided, Q8; use a minified dist such as `plotly.js-basic-dist-min`) are inlined into the srcdoc
  (no CDN – the CSP forbids it); the widget gets them as `React` and `Plotly`. The parent compiles TSX (sucrase) and sends
  code + data via `postMessage`; the widget calls `onSelect(keys)` which is posted back to the parent.
- Implementation (T41a): `frontend/src/widget-runtime/` – `runtime.tsx` (bundled with React into one IIFE string by
  `frontend/widget-runtime-plugin.ts`, a nested Vite build exposed as `virtual:aibex-widget-runtime`), `srcdoc.ts`
  (CSP meta + `plotly.js-basic-dist-min` + runtime, loaded lazily so the ~1.4 MB chunk is fetched only when a spec has
  a widget), `protocol.ts`. Messages carry `aibex: 1`; both sides check the *source* window (the frame's origin is
  opaque, so the parent posts with `'*'`). Parent → frame `{type: "render", code, data, selection}` (`data` = the
  widget's `panel-data` response `{inputs: {...}}`, `selection` = linked selection keys). Frame → parent `ready`,
  `rendered`, `select {keys}` (→ store selection, view state, no version), `error {phase: load|render, message}`
  (shown in the panel as `widget-error-<id>` and inside the frame). The runtime evaluates CommonJS-style JS
  (`exports.default = Widget`; `require` only for react/react-dom/plotly) through an inline `<script>` element – the
  CSP has no `'unsafe-eval'`. Widgets whose input SQL uses `$selected` refetch `panel-data` with the selection.
- Implementation (T41b): the parent compiles `panels[].code` with sucrase (`frontend/src/widget-runtime/compile.ts`,
  transforms `typescript` (tsx only) + `jsx` (classic runtime → `React.createElement`) + `imports` (ESM →
  `exports`/`require`)); the compiler is a lazy chunk loaded together with the srcdoc. A compile error is sent to the
  frame as a module that throws `Compile error (<language>): <message> (<line>:<col>)`, so it shows like a load error
  (in the frame and as `widget-error-<id>`).
- `create_widget` defaults `language` to `tsx`; a new panel is appended to the layout at the bottom (`w: 6, h: 8`).
  Same id as an existing widget replaces that widget (new version); same id as a non-widget panel is an error.

## Frontend conventions
- `/?bundle=<id>` selects the bundle; every page load creates a new session (version 0). Without the parameter the
  first bundle is used.
- Test ids (used by Playwright e2e):
  `bundle-select`, `panel-<id>`, `filter-<id>` (checkbox), `table-<id>` (rows are `tbody tr`), `chat-input`, `chat-send`,
  `chat-message` (assistant messages), `spec-version` (text = current version number), `history-item`, `undo-button`,
  `redo-button`, `widget-frame-<id>` (the iframe; attribute `sandbox="allow-scripts"` exactly), `error-banner`.
- Chat panel (T24a, right sidebar): Enter sends (Shift+Enter = newline), one turn at a time. The client reads the SSE
  stream with `fetch` (`chatStream` in `lib/api.ts`, not `EventSource`, because it is a POST). Each assistant bubble
  (`chat-message`) shows the turn's tool steps, applied changes (`→ version n: summary`), the reply text and any
  `error` event; a `spec` event replaces the store spec at once and refreshes the history. User bubbles are
  `chat-user-message`. A request failure (unreachable, 422) puts the text back into the input. The transcript is view
  state and is cleared when a new session starts.
- History (T24b): header shows `undo-button` / `redo-button` (disabled from `can_undo`/`can_redo` of
  `GET /sessions/{sid}`, refreshed after every change; Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z / Ctrl+Y outside text fields)
  next to `spec-version`. The sidebar "History" section lists every version newest first (`history-item`, with
  `data-version`, source badge `init`/`you`/`AI` and summary); the current one is marked `data-current="true"`.
- Toggling a filter checkbox or dragging/resizing a panel sends a patch with `source: "user"` (a new, undoable version).
  Drag/resize (title bar / bottom-right corner) patches only the changed `x/y/w/h` of every moved item, each guarded by
  a `test` on `/layout/<k>/i`; summary `move|resize panel <id> (+n shifted)`.
- Linked selection (T17e) is view state in the frontend store, not part of the spec (no version). It holds values of
  `spec.selection.key` (off when `selection` is missing or `linked: false`). A panel takes part when its panel-data has
  a column of that name: table rows (click; shift/ctrl/cmd-click toggles; selected rows `data-selected`, listed first),
  scatter/line/bar points (click, box/lasso; others fade, selected get a ring). Heatmap rows are treated as values of
  the key (matrix key, e.g. `gene_id`): click selects the row, selected rows are outlined. PCA (samples) does not take
  part. Header shows `selection-bar` with `selection-clear`; a new session clears the selection.
