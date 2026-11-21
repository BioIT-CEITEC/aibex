"""Discovery of results bundles (see docs/bundle-format.md). Phase 1 extends this with DuckDB views."""

from __future__ import annotations

from pathlib import Path

import yaml


def list_bundles(data_dir: Path) -> list[dict]:
    """Return id/title/modalities for every folder in data_dir that contains a bundle.yaml."""
    bundles: list[dict] = []
    if not data_dir.exists():
        return bundles
    for manifest in sorted(data_dir.glob("*/bundle.yaml")):
        try:
            meta = yaml.safe_load(manifest.read_text()) or {}
        except yaml.YAMLError as exc:  # broken manifest should not take the app down
            bundles.append({"id": manifest.parent.name, "error": f"invalid bundle.yaml: {exc}"})
            continue
        bundles.append(
            {
                "id": meta.get("id", manifest.parent.name),
                "title": meta.get("title", manifest.parent.name),
                "modalities": meta.get("modalities", []),
                "tables": sorted((meta.get("tables") or {}).keys()),
            }
        )
    return bundles
