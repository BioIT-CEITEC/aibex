# AIBEX – Assistant for Integrated Bioinformatics EXecution

*You are the expert. Aibex is your assistant.*

**Aibex View** turns bioinformatics results into an interactive dashboard that biologists can change by
typing what they want ("label the top 10 edited genes", "split the heatmap by genotype"). An LLM edits a
validated, undoable view spec; for things the spec cannot express it writes small sandboxed widgets.
It runs with self-hosted open-weight models (e-INFRA CZ) or commercial APIs.

Status: early prototype (demo, November 2026). Developed by the Bioinformatics Core Facility (BioIT), CEITEC Masaryk University.

## Quick start
```bash
cp .env.example .env          # add your LLM key
make eval-llm                 # pick models
make dev                      # http://localhost:5173 (frontend) / :8000 (API)
```
Docs: [vision](docs/vision.md) · [architecture](docs/architecture.md) · [view spec](docs/spec-format.md) · [results bundles](docs/bundle-format.md) · [deployment](docs/deploy.md)

License: [MIT](LICENSE).
