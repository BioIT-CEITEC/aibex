# CLAUDE.md – AIBEX

AIBEX = **Assistant for Integrated Bioinformatics EXecution**. The user is the expert; AIBEX is the assistant.
This repo currently builds **Aibex View**: a web app that shows bioinformatics results as an interactive
dashboard which biologists can **change by typing prompts**. An LLM edits a declarative *view spec* (Level 1)
and, if needed, writes small sandboxed widgets (Level 2).

Read before larger changes: `docs/architecture.md`, `docs/spec-format.md`, `docs/bundle-format.md`, `docs/deploy.md`, `docs/roadmap.md` (phases + demo prompts).
The long-term vision (harness: intake → resources → compute → analysis → view) is in `docs/vision.md` – do not build it in `main` yet.

## Goal right now
A convincing demo for next week, not production software. Prefer simple, working, visible progress.
Keep it robust enough to survive a live demo: validate every LLM output, never crash on a bad answer, always allow undo.

## Layout
```
backend/      Python 3.12, FastAPI, package `aibex` (uv project)
  aibex/main.py          app factory, serves API under /api and the built frontend at /
  aibex/bundles.py       results-bundle loading (DuckDB views over tables)
  aibex/spec.py          Pydantic models of the view spec + validation
  aibex/llm/             provider adapter (OpenAI-compatible) + tools + prompts
frontend/     React + Vite + TypeScript (create in Phase 1), Tailwind, shadcn/ui, react-plotly.js, react-grid-layout, zustand
scripts/      one-off tools (llm_eval.py, bundle converters)
deploy/k8s/   Kubernetes manifests for kuba-cluster (namespace bystry-ns)
docs/         design docs (keep them updated when you change a contract)
data/         LOCAL ONLY, gitignored. Bundles live here or under AIBEX_DATA_DIR.
```

## Commands
- `make dev` – backend (port 8000, reload) + frontend dev server (port 5173, proxies /api)
- `make test` – backend tests (pytest) + frontend typecheck/lint
- `make eval-llm` – compare e-INFRA models on tool calling (`scripts/llm_eval.py`)
- `make deploy` / `make restart` / `make logs` – cluster (see docs/deploy.md); `make upload-data BUNDLE=...`
- Python: always `uv run ...` / `uv add ...` inside `backend/`. Node: `npm` inside `frontend/`.

## Core contracts (do not break silently)
1. **View spec** (`docs/spec-format.md`) is the single source of truth for what the UI shows. The frontend renders only from the spec. Every LLM change is an RFC 6902 JSON Patch on the spec, validated by Pydantic before it is applied. Keep a history stack (undo/redo) of applied specs.
2. **Results bundle** (`docs/bundle-format.md`) is how data enters. Never hard-code dataset column names in UI code; read them from `bundle.yaml`.
3. **LLM data access** goes only through tools: `describe_bundle`, `query_data` (read-only DuckDB SQL, results capped at 200 rows, aggregates preferred), `update_view` (JSON Patch), `create_widget` (Level 2). The LLM never receives full raw tables. This mirrors the "only partial results leave the secure environment" principle – keep it.
4. **LLM provider** is behind `aibex/llm/provider.py` (OpenAI-compatible chat completions with tools). Config only via env: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_FAST`, `LLM_MODEL_CODE`. Default backend is the e-INFRA CZ service (`https://llm.ai.e-infra.cz/v1`). If a model returns no tool call, fall back to parsing a JSON block from the text; if that fails, show the message and change nothing.
5. **Level 2 widgets** run only inside a sandboxed `<iframe sandbox="allow-scripts">` with no network; data is passed by `postMessage` from the parent. Generated code is stored with the spec (`panels[].widget`) and can be undone like any other change.

## Rules
- Secrets: never read, print or commit `.env`. Never put keys in code, manifests or logs. `.env.example` documents the variables.
- Data: `data/` and any real dataset are gitignored. The ADAR2 data are unpublished – never commit them, never paste their contents into issues/PRs.
- Kubernetes: only namespace `bystry-ns`. Never `kubectl delete` anything you did not create in this repo; ask before `apply`. Pods must follow the security context in `deploy/k8s/deployment.yaml` (non-root, drop ALL, seccomp RuntimeDefault, explicit limits).
- Keep dependencies modest; ask before adding heavy frameworks.
- After UI work, check it visually with the Playwright MCP (screenshot the page) before saying it works.
- Small commits with clear messages; work on a feature branch, merge to `main` when a phase works.
- Branches: `main` = Aibex View framework. `demo/workshop-2026-11` = harness mock, demo-only wiring, experiments.
- Language in UI and docs: English. Be honest in the UI: label mock/demo parts as such.
