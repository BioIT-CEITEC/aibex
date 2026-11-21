# PROGRESS – Aibex View

Task list for interactive and overnight work. One task = one focused change of about an hour or less, ending with
passing tests and a commit. The overnight agent takes the **first unchecked task whose dependencies are done**.
Status markers: `- [ ]` todo · `- [x]` done · `- [!]` blocked (reason in the Log) · `- [~]` partly done (see Log).
Test IDs refer to `docs/acceptance.md`.

## Phase 0 – setup (interactive, before the first overnight run)
- [ ] T00 Phase 0 deploy done (pod running, URL works) – Vojta
- [ ] T01 Node 22+, `uv`, Playwright browsers installed on the Mac (`npx playwright install chromium`) – Vojta
- [ ] T02 Acceptance kit copied into the repo; planning session reviewed this list – Vojta

## Phase 1 – bundles + dashboard
- [ ] T10 `create_app()` factory + `Settings` fields per docs/api.md; keep `app = create_app()`; existing tests pass
- [ ] T11 Bundle loading: DuckDB connection per bundle, views per table, inferred columns, links → `GET /bundles`, `/schema` (A1.1, A1.2)
- [ ] T12 Read-only query endpoint with SQL guard (sqlglot or DuckDB parser) and caps (A1.3)
- [ ] T13 Pydantic spec models + `POST /validate-spec` incl. expr allow-list (A1.5)
- [ ] T14 Default view generator from bundle schema (volcano, MA, PCA from counts, top-genes heatmap, table) (A1.4)
- [ ] T15 Sessions (in memory) + `POST /sessions`, `GET /sessions/{sid}` + `panel-data` with filters/expr (A1.6)
- [ ] T16 Frontend scaffold: Vite + React + TS + Tailwind + shadcn/ui + zustand; API client; dev proxy; test ids per docs/api.md
- [ ] T17 Spec renderer: grid layout, plot panels (react-plotly.js: scatter, bar, box, violin, histogram, heatmap, pca), table panel, filters bar, linked selection
- [ ] T18 Move `frontend-e2e/*` into `frontend/`, Playwright set up; E1.1–E1.3 pass; M1 screenshot
- [ ] T19 `scripts/make_airway_bundle.py` (public data, pydeseq2) (A1.7) – needs network; mark `[!]` if it fails offline

## Phase 2 – prompt editing
- [ ] T20 Spec store: versioned history, `patch` / `undo` / `redo` endpoints (A2.1)
- [ ] T21 Provider adapter: `LLMProvider`, `OpenAICompatibleProvider` (tools + JSON fallback), `FakeProvider` rules (docs/api.md)
- [ ] T22 Chat loop + tools (`describe_bundle`, `query_data`, `update_view`, `undo_view`), repair logic, privacy caps (A2.2, A2.3)
- [ ] T23 `POST /chat` SSE + `?stream=false` (A2.4); system prompt with spec-format summary and panel index
- [ ] T24 Frontend chat panel (streaming), history list, undo/redo buttons, spec-version indicator; E2.1–E2.4 pass
- [ ] T25 Live check with the real model (`-m live`, A2.5); tune the system prompt; write results + latency to the Log

## Phase 3 – ADAR2
- [ ] T30 Inspect `raw/adar2-editing` (path = `$AIBEX_DATA_DIR/../raw/adar2-editing`); write assumptions to `data/adar2-notes.md` (outside git); do not copy raw files
- [ ] T31 `scripts/convert_adar2.py` → `$AIBEX_DATA_DIR/adar2-editing/bundle.yaml` + tables (A3.1, A3.2)
- [ ] T32 ADAR2 default view combining expression and editing (editing Δ vs log2FC, sites per gene, linked selection) (A3.3, A3.4)

## Phase 4 – Level 2 widgets
- [ ] T40 `create_widget` tool + widget validation + inputs resolution with `$selected` (A4.1–A4.3)
- [ ] T41 Browser TSX compile (sucrase) + sandboxed iframe runtime + postMessage data bridge; E4.1 passes
- [ ] T42 Example widget prompt on ADAR2 ("editing sites along the gene"), check with the real code model (M4)

## Phase 5 – polish
- [ ] T50 Loading states, error banner with retry (P5.1)
- [ ] T51 Saved views per bundle (P5.2)
- [ ] T52 Demo-script panel with the 6 demo prompts (P5.3)
- [ ] T53 Theme + palette pass (P5.4); final screenshots of every demo prompt into `logs/screens/`

## Log
<!-- newest first: date time · task · result · notes / blockers / questions for Vojta -->
