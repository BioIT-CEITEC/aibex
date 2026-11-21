# Roadmap – first demo (November 2026)

Each phase ends with something visible and a commit/merge to `main`. Use plan mode for each phase.

| Phase | Goal | Done when |
|---|---|---|
| 0 | Skeleton runs locally and on the cluster | `make dev` serves the placeholder; `make deploy` → https://aibex.dyn.cloud.e-infra.cz shows it; `make eval-llm` picked models |
| 1 | Bundles + spec-driven dashboard | airway bundle loads; `GET /api/bundles/{id}/schema`, `POST /api/query` (read-only); React app renders a default spec (volcano, MA, PCA, heatmap, table) with global filters and linked selection |
| 2 | Prompt editing (Level 1) | Chat panel with SSE; LLM tools `describe_bundle`, `query_data`, `update_view`; patches validated; history with undo/redo and a short change log; works with the e-INFRA model chosen in Phase 0 |
| 3 | Real use case | ADAR2-KO RNA-seq + RNA-editing bundle via `scripts/convert_adar2.py`; cross-modality views (editing Δ vs log2FC, sites per gene, linked selection between modalities) |
| 4 | Level 2 widgets | `create_widget` tool; TSX compiled in the browser, run in a sandboxed iframe; data via postMessage; undoable |
| 5 | Demo polish | Saved views, a scripted demo (5–6 prompts), error states, loading states; harness mock on branch `demo/workshop-2026-11` |

## Demo prompts to make work (acceptance tests)
1. "Label the 10 most significant genes in the volcano plot."
2. "Only show genes with padj < 0.01 and |log2FC| > 1 everywhere."
3. "Add a heatmap of the top 30 genes, samples grouped by genotype."
4. "Colour genes in the volcano by their editing change." (needs both modalities)
5. "For the selected gene, show its editing sites along the transcript." (Level 2 widget)
6. "Undo the last two changes."
