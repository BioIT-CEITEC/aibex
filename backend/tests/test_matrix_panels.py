"""Unit tests for pca/heatmap panel data (T15c) on the toy bundle: matrix rows, samples.tsv, scale, filters, cap."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import aibex.matrix_panels as mp
from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.main import create_app
from aibex.matrix_panels import jacobi_eigen
from aibex.panel_data import PanelDataError, panel_data
from aibex.validate import validate_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLES = ["WT_1", "WT_2", "WT_3", "KO_1", "KO_2", "KO_3"]


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


def _spec(panels: list[dict], filters: list[dict] | None = None) -> dict:
    return {
        "version": 1, "bundle": "toy", "filters": filters or [], "panels": panels,
        "layout": [{"i": p["id"], "x": 0, "y": i * 4, "w": 6, "h": 4} for i, p in enumerate(panels)],
    }


def _data(bundle, panel, filters=None):
    spec, errors = validate_spec(_spec([panel], filters), bundle)
    assert not errors, errors
    return panel_data(spec, bundle, panel["id"])


def _col(d, name):
    i = d["columns"].index(name)
    return [r[i] for r in d["rows"]]


def _q(bundle, sql):
    return bundle.cursor().execute(sql).fetchall()


PCA = {"id": "pca", "type": "plot", "kind": "pca", "table": "counts", "color": {"field": "genotype"}}
HEAT = {"id": "top-genes", "type": "plot", "kind": "heatmap", "table": "counts",
        "rows": {"top_n": 10, "by": "de.padj"}, "group_by": "genotype"}


# --- Jacobi ------------------------------------------------------------------------------------------------------
def test_jacobi_eigen_known_matrix():
    vals, vecs = jacobi_eigen([[2.0, 1.0], [1.0, 2.0]])
    assert vals == pytest.approx([3.0, 1.0])
    v0 = [vecs[0][0], vecs[1][0]]
    assert abs(v0[0]) == pytest.approx(1 / math.sqrt(2)) and v0[0] == pytest.approx(v0[1])


def test_jacobi_eigen_reconstructs_matrix():
    a = [[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 1.0]]
    vals, vecs = jacobi_eigen(a)
    assert vals == sorted(vals, reverse=True)
    for i in range(3):
        for j in range(3):
            rec = sum(vecs[i][k] * vals[k] * vecs[j][k] for k in range(3))
            assert rec == pytest.approx(a[i][j], abs=1e-9)


# --- PCA ---------------------------------------------------------------------------------------------------------
def test_pca_shape_labels_and_annotations(bundle):
    d = _data(bundle, PCA)
    assert d["columns"] == ["x", "y", "sample", "genotype"]
    assert _col(d, "sample") == SAMPLES
    assert _col(d, "genotype") == ["WT"] * 3 + ["KO"] * 3
    assert d["truncated"] is False
    assert d["x_label"].startswith("PC1 (") and d["x_label"].endswith(" %)")
    assert d["y_label"].startswith("PC2 (")
    p1 = int(d["x_label"][5:-3])
    p2 = int(d["y_label"][5:-3])
    assert 0 <= p2 <= p1 <= 100 and p1 + p2 <= 101


def test_pca_pc1_separates_genotypes(bundle):
    # toy KO samples are shifted by log2FC per gene → PC1 splits WT from KO
    x = _col(_data(bundle, PCA), "x")
    wt, ko = x[:3], x[3:]
    assert max(wt) < min(ko) or max(ko) < min(wt)
    assert sum(x) == pytest.approx(0, abs=1e-6)  # scores of centred data


def test_pca_is_deterministic_and_scale_matters(bundle):
    a = _data(bundle, PCA)
    assert _data(bundle, PCA) == a
    b = _data(bundle, dict(PCA, scale="none"))
    assert _col(a, "x") != pytest.approx(_col(b, "x"))


def test_pca_top_n_and_filter_via_link(bundle):
    full = _data(bundle, PCA)
    few = _data(bundle, dict(PCA, top_n=5))
    assert _col(few, "x") != pytest.approx(_col(full, "x"))
    # a filter on de reaches counts through the link; filtering to 1 gene leaves too little for a PCA
    with pytest.raises(PanelDataError, match="at least 2"):
        _data(bundle, PCA, [{"id": "one", "table": "de", "field": "gene_name", "op": "==", "value": "Gene_001"}])
    some = _data(bundle, PCA, [{"id": "sig", "table": "de", "field": "padj", "op": "<", "value": 0.05}])
    assert _col(some, "x") != pytest.approx(_col(full, "x"))


# --- heatmap -----------------------------------------------------------------------------------------------------
def test_heatmap_top_n_by_linked_column(bundle):
    d = _data(bundle, HEAT)
    assert d["columns"] == ["row", "column", "value", "group"]
    assert len(d["rows"]) == 10 * 6 and d["truncated"] is False
    top = [r[0] for r in _q(bundle, "SELECT gene_id FROM de ORDER BY padj LIMIT 10")]
    rows = _col(d, "row")
    assert list(dict.fromkeys(rows)) == top
    # columns grouped by genotype in samples.tsv order of first appearance
    assert _col(d, "column")[:6] == SAMPLES
    assert _col(d, "group")[:6] == ["WT"] * 3 + ["KO"] * 3


def test_heatmap_row_z_default(bundle):
    d = _data(bundle, HEAT)
    for i in range(0, len(d["rows"]), 6):
        vals = [r[2] for r in d["rows"][i:i + 6]]
        assert sum(vals) == pytest.approx(0, abs=1e-9)
        sd = math.sqrt(sum(v * v for v in vals) / 5)
        assert sd == pytest.approx(1) or sd == 0


def test_heatmap_scale_none_and_log1p_match_counts(bundle):
    gid = _q(bundle, "SELECT gene_id FROM de ORDER BY padj LIMIT 1")[0][0]
    raw = _q(bundle, f"SELECT {', '.join(SAMPLES)} FROM counts WHERE gene_id = '{gid}'")[0]
    d = _data(bundle, dict(HEAT, rows={"top_n": 1, "by": "de.padj"}, scale="none"))
    assert [r[2] for r in d["rows"]] == pytest.approx([float(v) for v in raw])
    d2 = _data(bundle, dict(HEAT, rows={"top_n": 1, "by": "de.padj"}, scale="log1p"))
    assert [r[2] for r in d2["rows"]] == pytest.approx([math.log1p(v) for v in raw])


def test_heatmap_explicit_values_order_and_case(bundle):
    ids = ["ENSMUSG00000000150", "ensmusg00000000007", "ENSMUSG99999999999"]
    d = _data(bundle, dict(HEAT, rows={"values": ids}))
    assert list(dict.fromkeys(_col(d, "row"))) == ["ENSMUSG00000000150", "ENSMUSG00000000007"]


def test_heatmap_by_own_column_without_group(bundle):
    p = {"id": "h", "type": "plot", "kind": "heatmap", "table": "counts", "rows": {"top_n": 3, "by": "counts.KO_1"}}
    d = _data(bundle, p)
    top = [r[0] for r in _q(bundle, "SELECT gene_id FROM counts ORDER BY KO_1, gene_id LIMIT 3")]
    assert list(dict.fromkeys(_col(d, "row"))) == top
    assert all(g is None for g in _col(d, "group"))


def test_heatmap_filter_via_link(bundle):
    f = [{"id": "up", "table": "de", "field": "log2FoldChange", "op": ">", "value": 0}]
    d = _data(bundle, dict(HEAT, rows={"top_n": 50, "by": "de.padj"}), f)
    allowed = {r[0] for r in _q(bundle, "SELECT gene_id FROM de WHERE log2FoldChange > 0")}
    assert set(_col(d, "row")) <= allowed and len(set(_col(d, "row"))) == 50


def test_heatmap_cap_keeps_whole_rows(bundle, monkeypatch):
    monkeypatch.setattr(mp, "MAX_ROWS", 20)  # 6 samples → 3 whole rows
    d = _data(bundle, HEAT)
    assert len(d["rows"]) == 18 and d["truncated"] is True


# --- endpoint ----------------------------------------------------------------------------------------------------
def test_endpoint_default_view_pca_and_heatmap(data_dir):
    client = TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))
    s = client.post("/api/sessions", json={"bundle": "toy"}).json()
    kinds = {p["id"]: p.get("kind") for p in s["spec"]["panels"]}
    for pid, kind in kinds.items():
        if kind not in ("pca", "heatmap"):
            continue
        r = client.post(f"/api/sessions/{s['session_id']}/panel-data", json={"panel_id": pid})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows"]
        if kind == "pca":
            assert "x_label" in body and "y_label" in body
        else:
            assert body["columns"] == ["row", "column", "value", "group"]
    assert "pca" in kinds.values() and "heatmap" in kinds.values()
