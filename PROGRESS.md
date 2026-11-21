# PROGRESS – Aibex View

Task list for interactive and overnight work. One task = one focused change of about an hour or less, ending with
passing tests and a commit. The overnight agent takes the **first `[~]` task, else the first `[ ]` task, whose
`after:` tasks are all `[x]`**, and skips tasks marked "– Vojta".
Status markers: `- [ ]` todo · `- [x]` done · `- [!]` blocked (reason in the Log) · `- [~]` partly done (see Log).
IDs in brackets refer to `docs/acceptance.md`; contracts are in `docs/api.md`. "Qn" = decision recorded in the Log.

## Phase 0 – setup (interactive, before the first overnight run)
- [x] T00 Phase 0 deploy done (pod running, URL works) – Vojta
- [x] T01 Node 22+, `uv`, Playwright browsers installed on the Mac (`npx playwright install chromium`); `node`/`npx` on the PATH Claude Code sees (the Playwright MCP currently fails: npx not found) – Vojta
- [x] T02 Acceptance kit copied into the repo; planning session reviewed this list – Vojta
- [x] T03 Answer the open questions Q1–Q9 (answers in the Log; docs and tests updated) – Vojta

## Phase 1 – bundles + dashboard
- [x] T10 `create_app()` factory + `Settings.llm_provider` per docs/api.md; keep `app = create_app()`; `make test` passes
- [x] T11 Bundle loading: DuckDB connection per bundle, a view/table per bundle table, inferred column types (bundle vocabulary), links → `GET /bundles`, `/bundles/{id}/schema` [A1.1, A1.2] (after: T10)
- [x] T12 Read-only query endpoint: statement-type guard (`duckdb.extract_statements`, no new dependency), forbidden table functions, external access disabled + config locked after setup, limit/clamp/`row_count`/`truncated` [A1.3] (after: T11)
- [x] T13a Pydantic spec models for all panel types (plot incl. pca/heatmap fields, table, text, widget), filters, layout; structural checks (kebab-case unique ids, layout ↔ panels) (after: T10)
- [x] T13b Semantic validation against the bundle schema + `expr` parser/allow-list (boolean grammar incl. CASE, expr filters) + widget code/SQL checks; `POST /validate-spec` [A1.5] (after: T11, T12, T13a)
- [x] T14 Default view generator (volcano first with `label`, MA, PCA, top-genes heatmap, table; column roles by common names) [A1.4] (after: T13b)
- [x] T15 Sessions (in memory) + spec store: `POST /sessions`, `GET /sessions/{sid}`, `patch` (422), `undo`/`redo` (409), history with `source` [A2.1 tests: `test_session_*`, `test_*patch*`, `test_undo_*`, `test_new_change_clears_redo`] (after: T14)
- [x] T15b `panel-data` for plot (field/expr axes, color/size/label, key column) and table panels with field and `expr` filters, also propagated through bundle links [A1.6] (after: T15)
- [ ] T15c `panel-data` for `pca` and `heatmap` (matrix tables, samples.tsv, scale) + unit tests on the toy bundle (after: T15b)
- [ ] T16a Frontend scaffold: Vite + React + TS + Tailwind (+ shadcn/ui base), eslint, `typecheck`/`lint` scripts, `/api` proxy to 8000; `make test` runs them (after: T01)
- [ ] T16b Move `frontend-e2e/*` into `frontend/` (`playwright.config.ts`, `e2e/`), `@playwright/test` dev dep; `make e2e` runs (specs may fail until their tasks) (after: T16a)
- [ ] T16c Typed API client, zustand store, `?bundle=` session bootstrap, bundle selector, `spec-version`, error banner [E1.2, E1.3] (after: T15, T16b)
- [ ] T17a Grid layout (react-grid-layout, 12 columns) + panel frame (`panel-<id>`) + table panel (`table-<id>`, sort, paging) (after: T15b, T16c)
- [ ] T17b Plot panel via react-plotly.js: scatter/line/bar/histogram/box/violin, colour, labels as annotations [E1.1] (after: T17a)
- [ ] T17c PCA + heatmap rendering (after: T15c, T17b)
- [ ] T17d Filters bar: checkbox per filter (`filter-<id>`) → patch with source `user` (after: T17a)
- [ ] T17e Linked selection across panels by `selection.key` (click/lasso, highlight) + layout drag/resize written back as a patch (after: T17b)
- [ ] T18 M1 visual pass at 1440×900: screenshots into `logs/screens/`, fix obvious layout issues [M1] (after: T17c, T17d, T17e)
- [ ] T19 `scripts/make_airway_bundle.py` with PEP 723 inline deps (pydeseq2 stays out of the backend), public airway data → `$AIBEX_DATA_DIR/airway/` [A1.7] – needs network; mark `[!]` if it fails offline (after: T11)

## Phase 2 – prompt editing
- [ ] T21a `aibex/llm/provider.py`: `ToolCall`, `LLMResponse`, `LLMProvider`, `OpenAICompatibleProvider` (tools), JSON-in-text fallback parser; unit tests with a mocked client (after: T10)
- [ ] T21b `FakeProvider` rules per docs/api.md + unit tests; provider selection in `create_app` (after: T21a)
- [ ] T22a Tools as plain functions: `describe_bundle` (schema + summary stats, no rows), `query_data` (≤200 rows), `update_view`, `undo_view`; unit tests (after: T13b, T15)
- [ ] T22b Chat loop (max 8 calls, give up after 2 failures, fallback parsing, events) + `POST /sessions/{sid}/chat?stream=false` [A2.2, A2.3] (after: T21b, T22a)
- [ ] T23 SSE streaming for `/chat` + system prompt (spec-format summary, panel index, rules) [A2.4] (after: T22b)
- [ ] T24a Frontend chat panel with streaming, `chat-input`/`chat-send`/`chat-message`, spec refresh on `spec` events [E2.1, E2.4] (after: T23, T17b)
- [ ] T24b History list (`history-item`), undo/redo buttons, version indicator [E2.2, E2.3] (after: T24a, T17d)
- [ ] T25 Live check with the real model (`make accept-live`, ≤3 runs, A2.5); tune the system prompt; results + latency in the Log (after: T23)
- [ ] T26 M2: demo prompts 1–3 and 6 with the real model on the ADAR2 bundle; latency in the Log – Vojta (after: T24b, T25, T32)
- [ ] T27 Morning review: merge Phases 1–2 to `main`, push, `make restart` – Vojta

## Phase 3 – ADAR2
- [x] T29 Put the ADAR2 results at `$AIBEX_DATA_DIR/../raw/adar2-editing`: expression results (DE table, RSEM), editing result tables/counts, and the R analysis code – Vojta
- [ ] T30 Inspect `raw/adar2-editing` freely (data are published): read the R code to learn the filters/normalisation, map files → bundle tables; write assumptions, file sizes and the planned preprocessing to `docs/adar2-notes.md` (in git, no data rows beyond a few examples); do not copy raw files (after: T29)
- [ ] T31 `scripts/convert_adar2.py` (polars, lazy/streaming for big files) → `$AIBEX_DATA_DIR/adar2-editing/bundle.yaml` + tables: `de`, `counts` (matrix), `editing` (only the realistically edited sites, ~4000, filtered as in the R code), and precomputed per-gene editing columns in `de` (`n_edit_sites`, `mean_delta`, `max_abs_delta`); contrast ADAR vs WT in both modalities (Q10); no genome needed [A3.1, A3.2] (after: T30, T11)
- [ ] T32 ADAR2 default view combining expression and editing (editing Δ vs log2FC, sites per gene, linked selection) [A3.3, A3.4] (after: T31, T14)
- [ ] T33 M3: confirm the assumptions in `data/adar2-notes.md`; demo prompt 4 works – Vojta (after: T32, T24b)

## Phase 4 – Level 2 widgets
- [ ] T40a Widget validation (code size/blocklist, input SQL read-only) + `panel-data` input resolution with `$selected` as a bound parameter [A4.2, A4.3] (after: T13b, T15b)
- [ ] T40b `create_widget` tool in the chat loop: layout placement, replace-by-id, undo [A4.1] (after: T40a, T22b)
- [ ] T41a Iframe runtime: srcdoc with CSP + inlined React and Plotly (minified dist), postMessage data/selection bridge (`widget-frame-<id>`) (after: T17a)
- [ ] T41b TSX compile in the browser (sucrase), compile/runtime errors shown in the panel [E4.1] (after: T41a, T40b, T24a)
- [ ] T42 Example widget prompt on ADAR2 ("editing sites along the gene") with the real code model [M4] (after: T41b, T32)

## Phase 5 – polish
- [ ] T50 Loading states for panels and chat, error banner with retry [P5.1] (after: T24b)
- [ ] T51 Saved views per bundle: `/bundles/{id}/views`, `/sessions/{sid}/load-view`, UI save/load; unit tests [P5.2] (after: T15, T24b)
- [ ] T52 Demo-script panel with the 6 demo prompts, click to send [P5.3] (after: T24a)
- [ ] T53 Theme + palette pass (light/dark) [P5.4]; final screenshots of every demo prompt into `logs/screens/` (after: T50, T52)
- [ ] T54 Production build check: `npm run build`, uvicorn serves `frontend/dist` at `/`, health ok; note any deploy change needed (after: T53)
- [ ] T55 Deploy and run all demo prompts on the public URL [P5.5] – Vojta (after: T54)
- [ ] T56 Harness mock on branch `demo/workshop-2026-11` (scope to be decided) – Vojta

## Log
<!-- newest first: date time · task · result · notes / blockers / questions for Vojta -->
- 2026-11-21 · T15b · done · `aibex/panel_data.py`: `panel_data(spec, bundle, panel_id)` for plot (x/y/color/size via
  field or compiled `expr`, `label` text column for `values` (case-insensitive) or `top_n` by `by` among filtered rows,
  `facet`, key column) and table panels (listed columns + key appended if missing, spec sort then key); filters as
  bound parameters (`==`→`=`, `between`, `in`, case-insensitive `contains`) or compiled `expr`, on the panel's table
  and one hop through links in both directions (semi-join). Labelled rows sort first so the 5000 cap keeps them.
  `POST /sessions/{sid}/panel-data` (404 unknown panel/session, 501 pca/heatmap → T15c, widget → T40a, 400 query
  error). `expr.py`: `log*`/`ln` of ≤ 0 and `sqrt` of < 0 now give NULL instead of a DuckDB error (one `padj = 0` row
  would break the whole volcano). Note for T32: genes with `padj = 0` get `y = null` in `-log10(padj)` and are not
  drawn – the ADAR2 default view may want to cap them. Large DE tables (> 5000 genes) are truncated in plots (labelled
  rows kept) – consider raising the cap or filtering in the converter (T31). docs/api.md updated. Tests:
  `tests/test_panel_data.py` (22); `make test` 276 pass; phase-1 acceptance all 34 pass; phase-2 A2.1 still pass,
  others need `aibex.llm.provider` (T21a+). No frontend → no e2e. No new dependencies. Note: Bash `python -c` and
  heredocs are refused by the runner, so ad-hoc checks went into unit tests.
- 2026-11-21 · T15 · done · `aibex/sessions.py`: `SessionStore` (in memory, thread-safe, max 200 sessions) and
  `Session` = undo stack of applied specs + pointer, flat `history` `{version, summary, source}`; `apply_patch(patch,
  summary, source)` (jsonpatch on a copy → `validate_spec`; `PatchError.errors` are repairable messages for T22a),
  `undo`/`redo(steps)` (clamped; `NothingToUndo` only when nothing is possible), `replace_spec` (for load-view, T51).
  Sessions resolve their bundle by id on each use (the registry closes old connections on reload). Endpoints `POST
  /sessions`, `GET /sessions/{sid}`, `POST …/patch` (422 `{detail: {errors}}`), `…/undo`, `…/redo` (409; body optional,
  `steps ≥ 1`). docs/api.md: implementation details added. Tests: `tests/test_sessions.py` (31); `make test` 254 pass;
  phase-2 A2.1 tests pass (6); phase-1: 31 pass, 3 fail = `panel-data` (T15b, expected); other phase-2 failures need
  `aibex.llm.provider` (T21a+). No frontend → no e2e. No new dependencies (jsonpatch already listed).
- 2026-11-21 · T14 · done · `aibex/default_view.py`: `find_role` (case-insensitive DESeq2/edgeR/limma names for
  fc/padj/pvalue/mean/name), `generate_default_view(bundle)` → volcano (first plot, `label: {field: name, values: []}`,
  significance colour via `expr`, quoted identifiers for names like `adj.P.Val`), MA (log10 of raw means), PCA +
  top-30 heatmap on a matrix table linked to DE (colour/group = first samples.tsv annotation), `genes` table sorted by
  padj; histogram fillers keep ≥4 panels; generic view for bundles without a DE table; `selection.key` = DE key.
  `default_view(bundle)` serves the bundle's `default_view` file only if inside the bundle and valid, else the
  generated one; the result is always validated (tables-only fallback). `GET /api/bundles/{id}/default-view`.
  Tests: `tests/test_default_view.py` (14); `make test` 223 pass; phase-1 acceptance 30 pass incl. A1.4, the 4 errors
  need `/sessions` (T15, expected). No frontend yet → no e2e. No new dependencies. Editing panels for ADAR2 are T32.
- 2026-11-21 · T13b · done · `aibex/expr.py`: own tokenizer + recursive-descent parser for the Q1 grammar (CASE WHEN,
  comparisons, AND/OR/NOT, IS [NOT] NULL, string literals, the 10 allowed functions; length ≤ 2000, nesting ≤ 40);
  `compile_expr(expr, columns)` → normalised SQL rebuilt from tokens (identifiers re-quoted, case-insensitive column
  match → canonical name) + referenced columns – T15b should run this SQL, never the raw string.
  `aibex/validate.py`: `validate_spec(data, bundle)` = structural + semantic (tables/fields incl. label/facet/sort/
  selection key, expr parse + `LIMIT 0` DuckDB dry run for type errors, pca/heatmap matrix table + samples.tsv columns
  + `rows.by` linked, widget code size/blocklist + input SQL guard); errors carry a location and a "did you mean"
  hint for LLM repair. `bundles.py` now loads `samples.tsv` (`Bundle.samples_columns`, `samples`,
  `matrix_columns()` – ready for T15c). `POST /api/validate-spec` (always 200; unknown bundle → `valid: false`).
  docs/api.md: semantic rules listed. Tests: `test_expr.py`, `test_validate.py`; `make test` 209 pass; phase-1
  acceptance 29 pass incl. all A1.5, the 5 failing need T14/T15 (expected). No new dependencies.
- 2026-11-21 · T13a · done · `aibex/spec.py`: Pydantic models `Spec`, `Filter` (field/op/value xor `expr`, value
  shape per op), `LayoutItem` (12-col grid), panels as a discriminated union on `type` (`PlotPanel` with per-kind
  checks for scatter/…/pca/heatmap, `TablePanel`, `TextPanel`, `WidgetPanel`), `Axis`/`Color`/`Size`/`Label`/
  `HeatmapRows`. `extra="forbid"` everywhere so LLM typos fail loudly. Structural checks: kebab-case unique panel
  and filter ids, layout ↔ panels (missing/orphan/duplicate), plain-JSON `plotly`. `parse_spec(data)` → `(spec,
  errors)` with readable `loc: msg` strings, never raises; `dump_spec` drops None fields. Semantic checks (bundle
  schema, `expr` grammar, widget code/SQL) and `POST /validate-spec` remain for T13b. docs/api.md: structural rules
  listed. Tests: `tests/test_spec.py` (53); `make test` passes (127); phase-1 acceptance 16 pass, the rest need
  T13b+ endpoints (expected). No new dependencies.
- 2026-11-21 · T12 · done · `aibex/query.py`: `check_readonly` (DuckDB `extract_statements` → exactly one SELECT;
  DuckDB `tokenize` → no call to forbidden functions: `read_*`, `pragma_*`, `glob`, `query`/`query_table`,
  `*_scan`, `getenv`, `duckdb_secrets`, … – names in string literals/comments are ignored), `run_query(cur, sql,
  limit, params)` → `{columns, rows, row_count, truncated}`: limit default 200, clamped to 0..5000, runs the original
  query and fetches limit+1 (order kept); `row_count` via `count(*)` over the query only when truncated; values made
  JSON-safe (NaN/inf → null, dates → ISO). Bound `params` are ready for widget `$selected` (T40a); the guard is meant
  to be reused by `query_data` (T22a) and widget input SQL (T13b). `POST /api/bundles/{id}/query` (400 `{detail}` on
  guard/SQL errors, 404 unknown bundle). External access disabled + config locked was already done in T11.
  Tests: `tests/test_query.py` (43); acceptance A1.1–A1.3 pass (16); the other phase-1 failures are T13b+ endpoints
  (expected). No new dependencies. Note: a Bash heredoc that ran python was refused by the runner, so I used Edit.
- 2026-11-21 · T11 · done · `aibex/bundles.py`: `load_bundle` creates one in-memory DuckDB per bundle and
  materialises every bundle table as a DuckDB table with the same name (parquet/tsv/csv; file paths must stay inside the
  bundle), so tables are joinable directly. Columns: declared type/description win, others inferred → vocabulary
  (`string/int/float/bool/date`); declared columns, `key` and link columns are checked against the data
  (`BundleError` → 500 with the reason). After loading: `enable_external_access=false` + `lock_configuration=true`
  (done here already; T12 still adds the statement guard). `BundleRegistry` on `app.state.bundles` caches per bundle
  and reloads when bundle.yaml's mtime changes; requests use `con.cursor()` (thread safety). New `GET
  /bundles/{id}/schema` (docs/api.md: 500 case added). Tests: `tests/test_bundles.py` (21); acceptance A1.1/A1.2
  pass (3), other phase-1 failures are 404s of T12+ endpoints (expected). `make test` ran fine natively this time
  (no Rosetta issue). No new dependencies.
- 2026-11-21 · T10 · done · `create_app(settings, llm_provider)` factory (state on `app.state`, routes on an `/api`
  router, `app = create_app()` kept); `Settings` reads env at instantiation (not import), new `llm_provider`
  (`openai` default | `fake`, validated), `/health` also reports `llm_provider` (docs/api.md updated). Provider
  construction from settings is left to T21a/T21b. Tests: `tests/test_app_factory.py` (8). Phase-1 acceptance: factory
  fixture works; remaining failures are 404s of T11+ endpoints (expected).
  **Environment issue for Vojta:** in the overnight runner the shell runs as x86_64 (Rosetta) while `backend/.venv`
  has arm64 wheels → `make test` fails at `import pydantic_core` (incompatible architecture). Not caused by code; I did
  not rebuild your `.venv`. Workaround used (ruff via `make test` passed, then):
  `uv run --directory backend --isolated --python cpython-3.12-macos-aarch64 pytest ...` (arm64-only uv-managed
  Python, ephemeral env, `.venv` untouched). Fix: start `scripts/overnight.sh` from a native arm64 terminal
  (check `arch` → `arm64`; maybe the terminal app/`claude` binary runs under Rosetta), or pin the project to a
  uv-managed arm64 Python. Also `uname`/`arch`/pipes with `;` are not in the runner allow-list.

### Decisions (Vojta, 2026-11-21) – answers to Q1–Q9
- **Q1 expr grammar:** yes to both – comparisons, `AND/OR/NOT`, string literals, `CASE WHEN` in `expr`; filters may use a
  boolean `expr`. → docs/api.md, spec-format.md, tests `test_validate_accepts_boolean_expr_in_color_and_filter`, `test_panel_data_filter_expr`.
- **Q2 filter reach:** yes, filters apply everywhere through bundle links. → docs/api.md, test `test_panel_data_filter_propagates_via_link`.
- **Q3 ADAR2 privacy:** not needed – the data are published; agents may read whatever they need. Sufficient inputs:
  the expression results, the resulting editing tables/counts, the R analysis code and the RSEM results.
  Focus is visualisation, not re-analysis.
- **Q4 demo prompt 4:** precompute – most things for the views are precomputed in the converter (per-gene editing columns in `de`).
- **Q5 airway:** keep the public airway script (T19), but run the demo checks (M2) on the ADAR2 bundle.
- **Q6 versions:** one version per applied tool call (as now).
- **Q7 sizes:** ~4000 realistically edited sites, but the raw files can be big → preprocess/filter in the converter,
  following Vojta's R code; final tables are small enough to load into memory.
- **Q8 widget libraries:** React and Plotly inside the sandbox.
- **Q9 genome:** mouse (*Mus musculus*), GRCm38 (mm10). Informative only: nothing in the app uses the genome.
- **Q10 main contrast** (2026-11-21): use **ADAR vs WT** (`input_files/ADAR_vs_WT_DESeq2.tsv`, `DE_RSEM/ADAR_vs_WT`) as the
  bundle's `de` table and `contrast`. It is a use case, not a real analysis – but the editing tables must use the same
  comparison (ADAR vs WT samples) so that expression and editing changes reflect each other in the views.
