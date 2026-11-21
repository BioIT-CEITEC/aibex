"""Unit tests for panel data (T15b): plot/table panels, filters (field, expr, via links), labels, cap, endpoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import aibex.panel_data as pd_mod
from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.expr import compile_expr
from aibex.main import create_app
from aibex.panel_data import PanelDataUnsupported, PanelNotFound, panel_data
from aibex.validate import validate_spec

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


def _spec(panels: list[dict], filters: list[dict] | None = None) -> dict:
    return {
        "version": 1,
        "bundle": "toy",
        "filters": filters or [],
        "panels": panels,
        "layout": [{"i": p["id"], "x": 0, "y": i * 4, "w": 6, "h": 4} for i, p in enumerate(panels)],
    }


VOLCANO = {
    "id": "volcano", "type": "plot", "table": "de", "kind": "scatter",
    "x": {"field": "log2FoldChange"}, "y": {"expr": "-log10(padj)"},
    "color": {"expr": "CASE WHEN padj < 0.05 THEN 'sig' ELSE 'ns' END"},
    "label": {"field": "gene_name", "values": []},
}
GENES = {"id": "genes", "type": "table", "table": "de", "columns": ["gene_name", "padj"],
         "sort": [{"field": "padj", "dir": "asc"}]}
SITES = {"id": "sites", "type": "table", "table": "editing", "columns": ["site_id", "gene_id", "delta"]}


def _data(bundle, panels, filters=None, panel_id=None):
    spec, errors = validate_spec(_spec(panels, filters), bundle)
    assert not errors, errors
    return panel_data(spec, bundle, panel_id or panels[0]["id"])


def _col(d, name):
    i = d["columns"].index(name)
    return [r[i] for r in d["rows"]]


def _q(bundle, sql):
    return bundle.cursor().execute(sql).fetchall()


# --- plot panels -----------------------------------------------------------------------------------------------
def test_scatter_columns_and_expr_evaluated(bundle):
    d = _data(bundle, [VOLCANO])
    assert d["columns"] == ["x", "y", "color", "label", "gene_id"]
    assert len(d["rows"]) == 200 and d["truncated"] is False
    (n_sig,) = _q(bundle, "SELECT count(*) FROM de WHERE padj < 0.05")[0]
    assert _col(d, "color").count("sig") == n_sig
    assert all(v is None for v in _col(d, "label"))
    assert all(y is None or y >= 0 for y in _col(d, "y"))


def test_label_values_case_insensitive_and_first(bundle):
    p = dict(VOLCANO, label={"field": "gene_name", "values": ["gene_150", "GENE_007"]})
    d = _data(bundle, [p])
    labels = _col(d, "label")
    assert labels[:2] == ["Gene_007", "Gene_150"]
    assert sum(v is not None for v in labels) == 2


def test_label_top_n_by_ranks_filtered_rows(bundle):
    p = dict(VOLCANO, label={"field": "gene_name", "top_n": 5, "by": "padj"})
    d = _data(bundle, [p])
    top5 = {r[0] for r in _q(bundle, "SELECT gene_name FROM de ORDER BY padj LIMIT 5")}
    assert set(_col(d, "label")[:5]) == top5
    assert sum(v is not None for v in _col(d, "label")) == 5
    # with a filter excluding the best genes the top 5 are taken among the remaining rows
    d2 = _data(bundle, [p], [{"id": "f", "table": "de", "field": "padj", "op": ">", "value": 1e-3}])
    top5f = {r[0] for r in _q(bundle, "SELECT gene_name FROM de WHERE padj > 1e-3 ORDER BY padj LIMIT 5")}
    assert {v for v in _col(d2, "label") if v is not None} == top5f


def test_histogram_x_only_with_size_and_facet(bundle):
    p = {"id": "h", "type": "plot", "table": "editing", "kind": "histogram", "x": {"field": "delta"},
         "size": {"expr": "abs(delta)"}, "facet": "chrom"}
    d = _data(bundle, [p])
    assert d["columns"] == ["x", "size", "facet", "site_id"]
    assert len(d["rows"]) == 300


def test_cap_truncates_and_keeps_labelled_rows(bundle, monkeypatch):
    monkeypatch.setattr(pd_mod, "MAX_ROWS", 50)
    p = dict(VOLCANO, label={"field": "gene_name", "values": ["Gene_199"]})
    d = _data(bundle, [p])
    assert len(d["rows"]) == 50 and d["truncated"] is True
    assert _col(d, "label")[0] == "Gene_199"


def test_log_of_zero_is_null_not_an_error():
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (0.0), (-1.0), (0.01), (NULL)) v(p)")
    for fn, expected in [("-log10(p)", [None, None, 2.0, None]), ("sqrt(p)", [0.0, None, 0.1, None]),
                         ("ln(p) < 0", [None, None, True, None]), ("log(10, p)", [None, None, -2.0, None])]:
        got = [r[0] for r in con.execute(f"SELECT {compile_expr(fn, ['p']).sql} FROM t").fetchall()]
        assert got == [pytest.approx(e) if isinstance(e, float) else e for e in expected], fn


# --- table panels ----------------------------------------------------------------------------------------------
def test_table_listed_columns_sort_and_key_appended(bundle):
    d = _data(bundle, [GENES])
    assert d["columns"] == ["gene_name", "padj", "gene_id"]
    padj = _col(d, "padj")
    assert padj == sorted(padj)
    d2 = _data(bundle, [SITES])
    assert d2["columns"] == ["site_id", "gene_id", "delta"]  # key already listed → not repeated


def test_table_all_columns_desc(bundle):
    p = {"id": "e", "type": "table", "table": "editing", "sort": [{"field": "delta", "dir": "desc"}]}
    d = _data(bundle, [p])
    assert d["columns"] == list(bundle.tables["editing"]["columns"])
    delta = _col(d, "delta")
    assert delta == sorted(delta, reverse=True)


# --- filters ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("flt", "where"),
    [
        ({"field": "padj", "op": "<=", "value": 0.01}, "padj <= 0.01"),
        ({"field": "padj", "op": ">=", "value": 0.5}, "padj >= 0.5"),
        ({"field": "log2FoldChange", "op": "between", "value": [-0.5, 0.5]}, "log2FoldChange BETWEEN -0.5 AND 0.5"),
        ({"field": "gene_name", "op": "in", "value": ["Gene_001", "Gene_002", "nope"]},
         "gene_name IN ('Gene_001', 'Gene_002')"),
        ({"field": "gene_name", "op": "contains", "value": "gene_01"}, "gene_name LIKE '%Gene_01%'"),
        ({"field": "gene_name", "op": "==", "value": "Gene_010"}, "gene_name = 'Gene_010'"),
        ({"field": "gene_name", "op": "!=", "value": "Gene_010"}, "gene_name <> 'Gene_010'"),
        ({"expr": "abs(log2FoldChange) > 1 AND padj < 0.05"}, "abs(log2FoldChange) > 1 AND padj < 0.05"),
    ],
)
def test_filter_ops(bundle, flt, where):
    d = _data(bundle, [GENES], [{"id": "f", "table": "de", **flt}])
    expected = {r[0] for r in _q(bundle, f"SELECT gene_id FROM de WHERE {where}")}
    assert set(_col(d, "gene_id")) == expected
    assert 0 < len(expected) < 200


def test_disabled_filter_ignored_and_filters_combine(bundle):
    flts = [{"id": "a", "table": "de", "field": "padj", "op": "<", "value": 0.05},
            {"id": "b", "table": "de", "field": "log2FoldChange", "op": ">", "value": 0},
            {"id": "c", "table": "de", "field": "padj", "op": "<", "value": 0, "enabled": False}]
    d = _data(bundle, [GENES], flts)
    expected = {r[0] for r in _q(bundle, "SELECT gene_id FROM de WHERE padj < 0.05 AND log2FoldChange > 0")}
    assert set(_col(d, "gene_id")) == expected


def test_filter_on_linked_table_both_directions(bundle):
    # de → editing (editing.gene_id -> de.gene_id)
    d = _data(bundle, [SITES], [{"id": "f", "table": "de", "expr": "padj < 0.001"}])
    sig = {r[0] for r in _q(bundle, "SELECT gene_id FROM de WHERE padj < 0.001")}
    assert 0 < len(d["rows"]) < 300 and set(_col(d, "gene_id")) <= sig
    # editing → de (reverse direction): genes with at least one strongly changed site
    d2 = _data(bundle, [VOLCANO], [{"id": "f", "table": "editing", "field": "delta", "op": "<", "value": -0.5}])
    genes = {r[0] for r in _q(bundle, "SELECT DISTINCT gene_id FROM editing WHERE delta < -0.5")}
    assert set(_col(d2, "gene_id")) == genes and 0 < len(genes) < 200


def test_filter_does_not_reach_two_hops(bundle):
    # counts and editing are both linked to de, but not to each other (one hop only)
    d = _data(bundle, [SITES], [{"id": "f", "table": "counts", "field": "KO_1", "op": "<", "value": 0}])
    assert len(d["rows"]) == 300


# --- unsupported / errors --------------------------------------------------------------------------------------
def test_text_panel_empty_unknown_panel_and_unsupported(bundle):
    text = {"id": "notes", "type": "text", "markdown": "hi"}
    pca = {"id": "pca", "type": "plot", "kind": "pca", "table": "counts"}
    spec, errors = validate_spec(_spec([text, pca]), bundle)
    assert not errors, errors
    assert panel_data(spec, bundle, "notes") == {"columns": [], "rows": [], "truncated": False}
    with pytest.raises(PanelNotFound):
        panel_data(spec, bundle, "nope")
    # pca/heatmap are implemented since T15c (tests/test_matrix_panels.py); widgets still answer 501 (T40a)
    assert panel_data(spec, bundle, "pca")["columns"][:3] == ["x", "y", "sample"]
    assert issubclass(PanelDataUnsupported, ValueError)


# --- endpoint --------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


def test_endpoint_follows_current_spec_and_undo(client):
    sid = client.post("/api/sessions", json={"bundle": "toy"}).json()["session_id"]
    add = [{"op": "add", "path": "/panels/-", "value": SITES},
           {"op": "add", "path": "/layout/-", "value": {"i": "sites", "x": 0, "y": 99, "w": 6, "h": 4}}]
    assert client.post(f"/api/sessions/{sid}/patch", json={"patch": add}).status_code == 200
    url = f"/api/sessions/{sid}/panel-data"
    assert len(client.post(url, json={"panel_id": "sites"}).json()["rows"]) == 300
    flt = [{"op": "add", "path": "/filters/-",
            "value": {"id": "f", "table": "editing", "field": "delta", "op": ">", "value": 0}}]
    assert client.post(f"/api/sessions/{sid}/patch", json={"patch": flt}).status_code == 200
    n = len(client.post(url, json={"panel_id": "sites", "selection": ["x"]}).json()["rows"])
    assert n < 300
    assert client.post(f"/api/sessions/{sid}/undo").status_code == 200
    assert len(client.post(url, json={"panel_id": "sites"}).json()["rows"]) == 300


def test_endpoint_errors(client):
    sid = client.post("/api/sessions", json={"bundle": "toy"}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/panel-data", json={"panel_id": "nope"}).status_code == 404
    assert client.post("/api/sessions/nope/panel-data", json={"panel_id": "x"}).status_code == 404
    assert client.post(f"/api/sessions/{sid}/panel-data", json={}).status_code == 422
