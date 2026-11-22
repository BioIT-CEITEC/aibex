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


def test_plot_carries_selection_key_of_linked_table(bundle):
    # editing sites (key site_id) take part in a gene_id selection: gene_id comes before the table key
    p = {"id": "sites-plot", "type": "plot", "table": "editing", "kind": "scatter",
         "x": {"field": "edit_wt"}, "y": {"field": "edit_ko"}}
    raw = dict(_spec([p, VOLCANO]), selection={"key": "gene_id", "linked": True})
    spec, errors = validate_spec(raw, bundle)
    assert not errors, errors
    d = panel_data(spec, bundle, "sites-plot")
    assert d["columns"] == ["x", "y", "gene_id", "site_id"]
    (n_join,) = _q(bundle, "SELECT count(*) FROM editing e JOIN de d ON e.gene_id = d.gene_id")[0]
    assert sum(g is not None for g in _col(d, "gene_id")) == n_join
    # the key column of the selection's own table is not repeated; no selection / not linked → table key only
    assert panel_data(spec, bundle, "volcano")["columns"] == ["x", "y", "color", "label", "gene_id"]
    unlinked, _ = validate_spec(dict(raw, selection={"key": "gene_id", "linked": False}), bundle)
    assert panel_data(unlinked, bundle, "sites-plot")["columns"] == ["x", "y", "site_id"]


def test_cap_truncates_and_keeps_labelled_rows(bundle, monkeypatch):
    monkeypatch.setattr(pd_mod, "MAX_PLOT_ROWS", 50)
    p = dict(VOLCANO, label={"field": "gene_name", "values": ["Gene_199"]})
    d = _data(bundle, [p])
    assert len(d["rows"]) == 50 and d["truncated"] is True
    assert _col(d, "label")[0] == "Gene_199"


def test_plot_cap_keeps_most_significant_rows(bundle, monkeypatch):
    # T34/Q11: after labelled rows, plot rows are ordered by padj ascending (nulls last), so the cap drops n.s. genes
    monkeypatch.setattr(pd_mod, "MAX_PLOT_ROWS", 20)
    d = _data(bundle, [dict(VOLCANO, y={"field": "padj"})])
    assert d["columns"] == ["x", "y", "color", "label", "gene_id"]  # the hidden rank column is not returned
    best = [r[0] for r in _q(bundle, "SELECT padj FROM de ORDER BY padj ASC NULLS LAST, gene_id LIMIT 20")]
    assert _col(d, "y") == pytest.approx(best) and d["truncated"] is True
    ids = [r[0] for r in _q(bundle, "SELECT gene_id FROM de ORDER BY padj ASC NULLS LAST, gene_id LIMIT 20")]
    assert _col(d, "gene_id") == ids


def test_plot_rank_follows_label_by(bundle, monkeypatch):
    monkeypatch.setattr(pd_mod, "MAX_PLOT_ROWS", 10)
    p = dict(VOLCANO, x={"field": "baseMean"}, label={"field": "gene_name", "top_n": 3, "by": "baseMean"})
    d = _data(bundle, [p])
    best = [r[0] for r in _q(bundle, "SELECT baseMean FROM de ORDER BY baseMean ASC NULLS LAST, gene_id LIMIT 10")]
    assert _col(d, "x") == pytest.approx(best)
    assert all(v is not None for v in _col(d, "label")[:3])


def test_plot_cap_is_separate_from_table_cap(bundle, monkeypatch):
    monkeypatch.setattr(pd_mod, "MAX_ROWS", 50)
    assert len(_data(bundle, [VOLCANO])["rows"]) == 200
    assert len(_data(bundle, [GENES])["rows"]) == 50
    assert pd_mod.MAX_PLOT_ROWS >= 40000 > pd_mod.MAX_ROWS


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
    # pca/heatmap are implemented since T15c (tests/test_matrix_panels.py), widgets since T40a (below)
    assert panel_data(spec, bundle, "pca")["columns"][:3] == ["x", "y", "sample"]
    assert issubclass(PanelDataUnsupported, ValueError)


# --- widget inputs (T40a) --------------------------------------------------------------------------------------
def _widget(*inputs: tuple[str, str]) -> dict:
    return {"id": "w", "type": "widget", "title": "W",
            "inputs": [{"name": n, "sql": s} for n, s in inputs],
            "code": "export default function Widget() { return null }"}


def test_widget_inputs_resolved(bundle):
    w = _widget(("sites", "SELECT site_id, delta FROM editing ORDER BY site_id LIMIT 50"),
                ("n", "SELECT count(*) AS n FROM de"))
    d = _data(bundle, [w])
    assert set(d) == {"inputs"}
    assert d["inputs"]["sites"]["columns"] == ["site_id", "delta"]
    assert len(d["inputs"]["sites"]["rows"]) == 50 and d["inputs"]["sites"]["truncated"] is False
    assert d["inputs"]["n"]["rows"] == [[200]]


def test_widget_input_capped_at_5000(bundle):
    d = _data(bundle, [_widget(("many", "SELECT range AS i FROM range(6000)"))])
    assert len(d["inputs"]["many"]["rows"]) == 5000 and d["inputs"]["many"]["truncated"] is True


def test_widget_selected_is_bound_parameter(bundle):
    w = _widget(("sites", "SELECT site_id FROM editing WHERE gene_id = $selected OR $selected IS NULL"))
    spec, errors = validate_spec(_spec([w]), bundle)
    assert not errors, errors
    all_rows = panel_data(spec, bundle, "w")["inputs"]["sites"]["rows"]
    assert len(all_rows) == 300  # nothing selected → NULL
    (gene,) = _q(bundle, "SELECT gene_id FROM editing LIMIT 1")[0]
    (n,) = _q(bundle, f"SELECT count(*) FROM editing WHERE gene_id = '{gene}'")[0]
    one = panel_data(spec, bundle, "w", selection=[gene, "ignored-second-key"])["inputs"]["sites"]["rows"]
    assert len(one) == n >= 1
    # a malicious "key" is a value, never SQL
    evil = panel_data(spec, bundle, "w", selection=["x' OR '1'='1"])["inputs"]["sites"]["rows"]
    assert evil == []


def test_widget_filters_do_not_apply(bundle):
    w = _widget(("sites", "SELECT site_id FROM editing"))
    flt = [{"id": "f", "table": "editing", "field": "delta", "op": ">", "value": 0}]
    assert len(_data(bundle, [w], flt)["inputs"]["sites"]["rows"]) == 300


def test_widget_input_runtime_error_is_panel_error(bundle):
    w = _widget(("bad", "SELECT CAST(site_id AS INTEGER) AS x FROM editing"))  # binds fine, fails at run time
    spec, errors = validate_spec(_spec([w]), bundle)
    assert not errors, errors
    with pytest.raises(pd_mod.PanelDataError, match="input 'bad'"):
        panel_data(spec, bundle, "w")


# --- endpoint --------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


def test_endpoint_widget_inputs_with_selection(client, bundle):
    sid = client.post("/api/sessions", json={"bundle": "toy"}).json()["session_id"]
    w = _widget(("sites", "SELECT site_id FROM editing WHERE gene_id = $selected"))
    add = [{"op": "add", "path": "/panels/-", "value": w},
           {"op": "add", "path": "/layout/-", "value": {"i": "w", "x": 0, "y": 99, "w": 6, "h": 8}}]
    assert client.post(f"/api/sessions/{sid}/patch", json={"patch": add}).status_code == 200
    url = f"/api/sessions/{sid}/panel-data"
    r = client.post(url, json={"panel_id": "w"})
    assert r.status_code == 200 and r.json()["inputs"]["sites"]["rows"] == []
    (gene,) = _q(bundle, "SELECT gene_id FROM editing LIMIT 1")[0]
    r = client.post(url, json={"panel_id": "w", "selection": [gene]})
    assert r.status_code == 200 and len(r.json()["inputs"]["sites"]["rows"]) >= 1


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
