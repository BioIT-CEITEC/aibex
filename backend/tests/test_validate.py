"""Unit tests for semantic spec validation against a bundle + POST /api/validate-spec (T13b)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.main import create_app
from aibex.validate import MAX_WIDGET_CODE, validate_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(d, "toy")
    return d


@pytest.fixture(scope="module")
def bundle(data_dir):
    return load_bundle(data_dir / "toy" / "bundle.yaml")


@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


def full_spec() -> dict:
    return {
        "version": 1,
        "title": "toy",
        "bundle": "toy",
        "filters": [
            {"id": "sig", "table": "de", "field": "padj", "op": "<=", "value": 0.05, "enabled": True},
            {"id": "lfc", "table": "de", "expr": "abs(log2FoldChange) > 1", "enabled": False},
        ],
        "panels": [
            {"id": "volcano", "type": "plot", "title": "Volcano", "table": "de", "kind": "scatter",
             "x": {"field": "log2FoldChange"}, "y": {"expr": "-log10(padj)"},
             "color": {"expr": "CASE WHEN padj < 0.05 THEN 'sig' ELSE 'ns' END"},
             "size": {"field": "baseMean"},
             "label": {"field": "gene_name", "values": [], "top_n": 5, "by": "padj"}},
            {"id": "pca", "type": "plot", "kind": "pca", "title": "PCA", "table": "counts", "top_n": 100,
             "color": {"field": "genotype"}},
            {"id": "heat", "type": "plot", "kind": "heatmap", "title": "Top", "table": "counts",
             "rows": {"top_n": 20, "by": "de.padj"}, "group_by": "genotype"},
            {"id": "genes", "type": "table", "title": "Genes", "table": "de", "columns": ["gene_name", "padj"],
             "sort": [{"field": "padj", "dir": "asc"}]},
            {"id": "notes", "type": "text", "title": "Notes", "markdown": "hi"},
            {"id": "w", "type": "widget", "title": "W",
             "inputs": [{"name": "sites", "sql": "SELECT * FROM editing WHERE gene_id = $selected"}],
             "code": "export default function Widget({data}) { return <div>{data.sites.rows.length}</div> }"},
        ],
        "layout": [{"i": i, "x": 0, "y": n * 8, "w": 6, "h": 8}
                   for n, i in enumerate(["volcano", "pca", "heat", "genes", "notes", "w"])],
        "selection": {"key": "gene_id"},
    }


def test_full_spec_is_valid(bundle):
    spec, errors = validate_spec(full_spec(), bundle)
    assert errors == []
    assert spec is not None


def test_pca_symbol_by_sample_column(bundle):
    """T35: a pca may set the marker shape by a second samples.tsv column."""
    s = full_spec()
    s["panels"][1]["symbol"] = {"field": "genotype", "label": "Genotype"}
    spec, errors = validate_spec(s, bundle)
    assert errors == [] and spec is not None


@pytest.mark.parametrize("idx", [0, 2])  # scatter, heatmap
def test_symbol_only_on_pca(bundle, idx):
    s = full_spec()
    s["panels"][idx]["symbol"] = {"field": "genotype"}
    spec, errors = validate_spec(s, bundle)
    assert spec is None and any("symbol" in e for e in errors), errors


def test_samples_loaded(bundle):
    assert bundle.samples_columns == ["sample", "genotype"]
    assert len(bundle.samples) == 6
    assert bundle.matrix_columns("counts") == ["WT_1", "WT_2", "WT_3", "KO_1", "KO_2", "KO_3"]
    assert bundle.matrix_columns("de") == []


def _mut(path_fn):
    s = full_spec()
    path_fn(s)
    return s


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda s: s.update(bundle="other"), "bundle"),
        (lambda s: s["panels"][0].update(table="nope"), "panels[0].table"),
        (lambda s: s["panels"][0]["x"].update(field="log2FC"), "panels[0].x.field"),
        (lambda s: s["panels"][0]["y"].update(expr="-log10(secret_col)"), "panels[0].y.expr"),
        (lambda s: s["panels"][0]["y"].update(expr="(SELECT 1)"), "panels[0].y.expr"),
        (lambda s: s["panels"][0]["color"].update(expr="abs(gene_name)"), "panels[0].color.expr"),  # type error
        (lambda s: s["panels"][0]["size"].update(field="nope"), "panels[0].size.field"),
        (lambda s: s["panels"][0]["label"].update(field="name"), "panels[0].label.field"),
        (lambda s: s["panels"][0]["label"].update(by="pvalue"), "panels[0].label.by"),
        (lambda s: s["panels"][0].update(facet="nope"), "panels[0].facet"),
        (lambda s: s["panels"][1].update(table="de"), "panels[1].table"),  # not a matrix table
        (lambda s: s["panels"][1]["color"].update(field="batch"), "panels[1].color.field"),
        (lambda s: s["panels"][1].update(symbol={"field": "batch"}), "panels[1].symbol.field"),  # T35
        (lambda s: s["panels"][2].update(group_by="batch"), "panels[2].group_by"),
        (lambda s: s["panels"][2]["rows"].update(by="de.nope"), "panels[2].rows.by"),
        (lambda s: s["panels"][2]["rows"].update(by="editing.delta"), "panels[2].rows.by"),  # not linked
        (lambda s: s["panels"][3]["columns"].append("nope"), "panels[3].columns[2]"),
        (lambda s: s["panels"][3]["sort"][0].update(field="nope"), "panels[3].sort[0].field"),
        (lambda s: s["panels"][5].update(code="fetch('http://x')"), "panels[5].code"),
        (lambda s: s["panels"][5].update(code="new WebSocket('ws://x')"), "panels[5].code"),
        (lambda s: s["panels"][5].update(code="localStorage.x = 1"), "panels[5].code"),
        (lambda s: s["panels"][5].update(code="x" * (MAX_WIDGET_CODE + 1)), "panels[5].code"),
        (lambda s: s["panels"][5]["inputs"][0].update(sql="DROP TABLE de"), "panels[5].inputs[0].sql"),
        (lambda s: s["panels"][5]["inputs"][0].update(sql="SELECT * FROM read_csv('/etc/passwd')"),
         "panels[5].inputs[0].sql"),
        # T40a: only $selected may be a parameter; the input SQL is dry-run against the bundle
        (lambda s: s["panels"][5]["inputs"][0].update(sql="SELECT * FROM editing WHERE gene_id = $gene"),
         "panels[5].inputs[0].sql"),
        (lambda s: s["panels"][5]["inputs"][0].update(sql="SELECT * FROM editing WHERE gene_id = ?"),
         "panels[5].inputs[0].sql"),
        (lambda s: s["panels"][5]["inputs"][0].update(sql="SELECT * FROM nope"), "panels[5].inputs[0].sql"),
        (lambda s: s["panels"][5]["inputs"][0].update(sql="SELECT secret_col FROM editing"),
         "panels[5].inputs[0].sql"),
        (lambda s: s["filters"][0].update(table="nope"), "filters[0].table"),
        (lambda s: s["filters"][0].update(field="nope"), "filters[0].field"),
        (lambda s: s["filters"][1].update(expr="nope > 1"), "filters[1].expr"),
        (lambda s: s["filters"][1].update(expr="padj < (SELECT 1)"), "filters[1].expr"),
        (lambda s: s["selection"].update(key="nope"), "selection.key"),
    ],
)
def test_semantic_errors_are_located(bundle, mutate, needle):
    spec, errors = validate_spec(_mut(mutate), bundle)
    assert spec is None
    assert any(e.startswith(needle) for e in errors), errors


def test_hint_suggests_close_column(bundle):
    _, errors = validate_spec(_mut(lambda s: s["panels"][0]["x"].update(field="log2FoldChang")), bundle)
    assert "did you mean 'log2FoldChange'" in errors[0]


def test_structural_errors_come_first(bundle):
    s = full_spec()
    s["panels"][0]["colour"] = {"field": "padj"}
    s["panels"][0]["table"] = "nope"
    _, errors = validate_spec(s, bundle)
    assert errors and all("colour" in e or "extra" in e.lower() for e in errors)


def test_input_not_mutated(bundle):
    s = full_spec()
    before = copy.deepcopy(s)
    validate_spec(s, bundle)
    assert s == before


def test_endpoint_valid_and_invalid(client):
    r = client.post("/api/validate-spec", json=full_spec())
    assert r.status_code == 200
    assert r.json() == {"valid": True, "errors": []}
    bad = _mut(lambda s: s["panels"][0].update(table="nope"))
    body = client.post("/api/validate-spec", json=bad).json()
    assert body["valid"] is False and body["errors"]


def test_endpoint_unknown_bundle_and_non_object(client):
    body = client.post("/api/validate-spec", json=_mut(lambda s: s.update(bundle="nope"))).json()
    assert body["valid"] is False and "unknown bundle" in body["errors"][0]
    body = client.post("/api/validate-spec", json=[1, 2]).json()
    assert body == {"valid": False, "errors": ["spec must be a JSON object"]}
