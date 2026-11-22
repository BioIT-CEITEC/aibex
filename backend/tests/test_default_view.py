"""Unit tests for the default view (T14): role detection, generated panels, bundle-provided default_view."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest
import yaml
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.default_view import default_view, find_role, generate_default_view
from aibex.main import create_app
from aibex.validate import validate_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _toy(d: Path, bundle_id: str = "toy") -> Path:
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make_toy_bundle(d, bundle_id)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    _toy(d)
    return d


@pytest.fixture(scope="module")
def bundle(data_dir):
    return load_bundle(data_dir / "toy" / "bundle.yaml")


def _write_bundle(root: Path, bid: str, tables: dict[str, pl.DataFrame], extra: dict | None = None) -> Path:
    out = root / bid
    (out / "tables").mkdir(parents=True)
    manifest: dict = {"id": bid, "title": bid, "tables": {}}
    for name, df in tables.items():
        df.write_parquet(out / "tables" / f"{name}.parquet")
        manifest["tables"][name] = {"file": f"tables/{name}.parquet", "key": df.columns[0]}
    manifest.update(extra or {})
    (out / "bundle.yaml").write_text(yaml.safe_dump(manifest))
    return out / "bundle.yaml"


@pytest.mark.parametrize(
    ("columns", "role", "expected"),
    [
        (["gene", "log2FoldChange", "padj"], "fc", "log2FoldChange"),
        (["genes", "logFC", "FDR", "logCPM"], "fc", "logFC"),
        (["genes", "logFC", "FDR", "logCPM"], "padj", "FDR"),
        (["ID", "logFC", "AveExpr", "adj.P.Val", "P.Value"], "padj", "adj.P.Val"),
        (["ID", "LOG2FOLDCHANGE"], "fc", "LOG2FOLDCHANGE"),
        (["x", "y"], "fc", None),
    ],
)
def test_find_role(columns, role, expected):
    assert find_role(columns, role) == expected


def test_generated_view_on_toy(bundle):
    spec = generate_default_view(bundle)
    ids = [p["id"] for p in spec["panels"]]
    assert ids == ["volcano", "ma-plot", "pca", "top-genes", "genes"]
    volcano = spec["panels"][0]
    assert volcano["kind"] == "scatter" and volcano["label"] == {"field": "gene_name", "values": []}
    assert volcano["x"]["field"] == "log2FoldChange" and "padj" in volcano["y"]["expr"]
    assert spec["panels"][2]["color"] == {"field": "genotype"}
    assert spec["panels"][3]["rows"]["by"] == "de.padj" and spec["panels"][3]["group_by"] == "genotype"
    assert spec["selection"] == {"key": "gene_id", "linked": True}
    assert "KO vs WT" in volcano["title"]
    _, errors = validate_spec(spec, bundle)
    assert errors == []


def test_layout_fits_grid_without_overlap(bundle):
    layout = generate_default_view(bundle)["layout"]
    cells = set()
    for item in layout:
        assert item["x"] + item["w"] <= 12
        for x in range(item["x"], item["x"] + item["w"]):
            for y in range(item["y"], item["y"] + item["h"]):
                assert (x, y) not in cells
                cells.add((x, y))


def test_limma_names_with_dots_validate(tmp_path):
    df = pl.DataFrame({"ID": ["a", "b", "c"], "logFC": [1.0, -2.0, 0.1], "AveExpr": [5.0, 6.0, 7.0],
                       "adj.P.Val": [0.01, 0.2, 0.9], "symbol": ["A", "B", "C"]})
    b = load_bundle(_write_bundle(tmp_path, "limma", {"res": df}))
    spec = default_view(b)
    assert spec["panels"][0]["id"] == "volcano"
    assert '"adj.P.Val"' in spec["panels"][0]["y"]["expr"]
    assert spec["panels"][0]["label"]["field"] == "symbol"
    assert spec["panels"][1]["x"] == {"field": "AveExpr", "label": "AveExpr"}  # already log scale
    assert len(spec["panels"]) >= 4
    assert validate_spec(spec, b)[1] == []


def test_minimal_de_table_still_gets_four_panels(tmp_path):
    df = pl.DataFrame({"gene_id": ["a", "b"], "log2FoldChange": [1.0, -1.0], "pvalue": [0.01, 0.5]})
    b = load_bundle(_write_bundle(tmp_path, "mini", {"de": df}))
    spec = default_view(b)
    assert len(spec["panels"]) >= 4
    assert spec["panels"][0]["label"]["field"] == "gene_id"
    assert validate_spec(spec, b)[1] == []


def test_bundle_without_de_table_gets_generic_view(tmp_path):
    df = pl.DataFrame({"site_id": ["s1", "s2"], "a": [1.0, 2.0], "b": [3.0, 4.0]})
    b = load_bundle(_write_bundle(tmp_path, "generic", {"sites": df}))
    spec = default_view(b)
    first = spec["panels"][0]
    assert first["kind"] == "scatter" and first["label"]["values"] == []
    assert any(p["type"] == "table" for p in spec["panels"])
    assert validate_spec(spec, b)[1] == []


def test_bundle_default_view_file_is_used(tmp_path):
    root = _toy(tmp_path, "own")
    (root / "views").mkdir()
    own = {"version": 1, "title": "Own view", "bundle": "own", "filters": [],
           "panels": [{"id": "genes", "type": "table", "title": "Genes", "table": "de"}],
           "layout": [{"i": "genes", "x": 0, "y": 0, "w": 12, "h": 8}]}
    (root / "views" / "default.json").write_text(json.dumps(own))
    manifest = yaml.safe_load((root / "bundle.yaml").read_text())
    manifest["default_view"] = "views/default.json"
    (root / "bundle.yaml").write_text(yaml.safe_dump(manifest))
    assert default_view(load_bundle(root / "bundle.yaml"))["title"] == "Own view"


def test_invalid_or_missing_default_view_file_falls_back(tmp_path):
    root = _toy(tmp_path, "bad")
    (root / "views").mkdir()
    (root / "views" / "default.json").write_text(json.dumps({"version": 1, "bundle": "bad", "panels": [
        {"id": "x", "type": "table", "title": "X", "table": "nope"}], "layout": [{"i": "x", "x": 0, "y": 0, "w": 6,
                                                                                  "h": 4}]}))
    manifest = yaml.safe_load((root / "bundle.yaml").read_text())
    manifest["default_view"] = "views/default.json"
    (root / "bundle.yaml").write_text(yaml.safe_dump(manifest))
    spec = default_view(load_bundle(root / "bundle.yaml"))
    assert spec["panels"][0]["id"] == "volcano"
    manifest["default_view"] = "../../etc/passwd"
    (root / "bundle.yaml").write_text(yaml.safe_dump(manifest))
    assert default_view(load_bundle(root / "bundle.yaml"))["panels"][0]["id"] == "volcano"


def test_default_view_endpoint(data_dir):
    client = TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))
    r = client.get("/api/bundles/toy/default-view")
    assert r.status_code == 200
    spec = r.json()
    assert spec["bundle"] == "toy"
    assert client.post("/api/validate-spec", json=spec).json() == {"valid": True, "errors": []}
    assert client.get("/api/bundles/nope/default-view").status_code == 404
