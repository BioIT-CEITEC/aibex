# Architecture – Aibex View

```
 Browser (React)                         Backend (FastAPI, Python)                 LLM (e-INFRA CZ, OpenAI-compatible)
 ┌───────────────────────────┐   /api    ┌──────────────────────────────┐  tools  ┌──────────────────────────┐
 │ Dashboard renderer        │◀────────▶│ Bundles: DuckDB over tables   │◀──────▶│ fast model: spec edits   │
 │  (spec → plots/tables)    │          │ Spec store + history (undo)   │        │ code model: widgets      │
 │ Chat panel (SSE stream)   │          │ Chat loop: prompt → tools     │        └──────────────────────────┘
 │ Sandboxed widget iframes  │          │  describe_bundle / query_data │
 │ History / undo / diff     │          │  update_view / create_widget  │
 └───────────────────────────┘          └──────────────────────────────┘
```

## Request flow for a prompt
1. User types "colour the volcano by editing change and label the top 10 genes".
2. Frontend POSTs `{session_id, message}` to `/api/chat` and listens to an SSE stream.
3. Backend builds the LLM context: system prompt (rules, spec format summary), bundle schema
   (tables, columns, types, small summary stats – **not raw rows**), current spec with a panel index, the last few turns.
4. The LLM calls tools. `query_data` runs read-only SQL in DuckDB (timeouts, 200-row cap). `update_view` sends a JSON Patch.
5. Backend applies the patch to a copy of the spec, validates it (Pydantic + references to existing tables/columns).
   Invalid → error message back to the LLM (max 2 repair attempts). Valid → new spec version pushed to history.
6. SSE events to the browser: `token` (assistant text), `tool` (what is happening), `spec` (new spec version), `error`, `done`.
7. The frontend re-renders from the new spec; the history panel shows the change summary with undo.

## Levels
- **Level 1** – LLM edits the spec only. Fast, safe, covers most requests.
- **Level 2** – LLM writes a `widget` panel (TSX) for things the spec cannot express. Compiled in the browser
  (e.g. sucrase/esbuild-wasm) and executed in `<iframe sandbox="allow-scripts">`; data via `postMessage`.
- **Level 3 (later)** – a coding agent (Claude Agent SDK / Claude Code headless) extends the framework itself
  (new panel types) inside a constrained folder, rebuilds, and hot-reloads. Not in scope for the first demo.

## State
- Sessions in memory (dict) for the demo; spec history per session. Saved views can be written as JSON files
  under `data/views/` (and later to a DB).

## Deployment
Single pod on kuba-cluster (namespace `bystry-ns`): the init containers clone the public repo and build the
frontend; the main container runs uvicorn and serves both API and static files. Data comes from a PVC mounted at `/data`.
See `deploy.md`.
