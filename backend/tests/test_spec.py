"""Unit tests for the structural spec models (T13a, docs/spec-format.md)."""

from __future__ import annotations

import copy

import pytest

from aibex.spec import PlotPanel, Spec, TablePanel, WidgetPanel, dump_spec, parse_spec


def full_spec() -> dict:
    """One panel of every type, both filter shapes, theme and selection – mirrors docs/spec-format.md."""
    return {
        "version": 1,
        "title": "ADAR2: expression and editing",
        "bundle": "toy",
        "theme": {"palette": "default", "dark": False},
        "filters": [
            {"id": "sig", "table": "de", "field": "padj", "op": "<=", "value": 0.05, "label": "padj ≤ 0.05",
             "enabled": True},
            {"id": "lfc", "table": "de", "expr": "abs(log2FoldChange) > 1", "enabled": False},
            {"id": "range", "table": "de", "field": "baseMean", "op": "between", "value": [10, 1000]},
            {"id": "genes", "table": "de", "field": "gene_name", "op": "in", "value": ["A", "B"]},
        ],
        "panels": [
            {
                "id": "volcano", "type": "plot", "title": "Volcano", "table": "de", "kind": "scatter",
                "x": {"field": "log2FoldChange", "label": "log2 FC"},
                "y": {"expr": "-log10(padj)", "label": "-log10 padj"},
                "color": {"expr": "CASE WHEN padj < 0.05 THEN 'sig' ELSE 'ns' END",
                          "palette": {"sig": "#d62728", "ns": "#bbbbbb"}},
                "size": None,
                "label": {"field": "gene_name", "values": ["Gria2"], "top_n": 10, "by": "padj"},
                "facet": None,
                "plotly": {"layout": {"showlegend": False}},
            },
            {"id": "pca", "type": "plot", "kind": "pca", "title": "PCA", "table": "counts", "top_n": 500,
             "scale": "log1p", "color": {"field": "genotype"}},
            {"id": "top-genes", "type": "plot", "kind": "heatmap", "title": "Top", "table": "counts",
             "rows": {"top_n": 30, "by": "de.padj", "values": []}, "group_by": "genotype", "scale": "row-z"},
            {"id": "genes-table", "type": "table", "title": "Genes", "table": "de",
             "columns": ["gene_name", "padj"], "sort": [{"field": "padj", "dir": "asc"}], "page_size": 25},
            {"id": "notes", "type": "text", "title": "Notes", "markdown": "Hello"},
            {"id": "editing-lollipop", "type": "widget", "title": "W",
             "inputs": [{"name": "sites", "sql": "SELECT 1"}],
             "code": "export default function Widget() { return null }"},
        ],
        "layout": [
            {"i": "volcano", "x": 0, "y": 0, "w": 6, "h": 9},
            {"i": "pca", "x": 6, "y": 0, "w": 6, "h": 9},
            {"i": "top-genes", "x": 0, "y": 9, "w": 6, "h": 9},
            {"i": "genes-table", "x": 6, "y": 9, "w": 6, "h": 9, "moved": False, "static": False},
            {"i": "notes", "x": 0, "y": 18, "w": 12, "h": 3},
            {"i": "editing-lollipop", "x": 0, "y": 21, "w": 6, "h": 8},
        ],
        "selection": {"key": "gene_id", "linked": True},
    }


def test_full_spec_is_valid():
    spec, errors = parse_spec(full_spec())
    assert errors == []
    assert isinstance(spec, Spec)
    kinds = [type(p) for p in spec.panels]
    assert kinds == [PlotPanel, PlotPanel, PlotPanel, TablePanel, type(spec.panels[4]), WidgetPanel]
    assert spec.panels[5].language == "tsx"


def test_minimal_spec_and_acceptance_example_valid():
    assert parse_spec({"bundle": "toy"})[1] == []
    s = {
        "version": 1, "title": "t", "bundle": "toy", "filters": [],
        "panels": [
            {"id": "volcano", "type": "plot", "title": "Volcano", "table": "de", "kind": "scatter",
             "x": {"field": "log2FoldChange"}, "y": {"expr": "-log10(padj)"},
             "label": {"field": "gene_name", "values": []}},
            {"id": "genes", "type": "table", "title": "Genes", "table": "de", "columns": ["gene_name", "padj"]},
        ],
        "layout": [{"i": "volcano", "x": 0, "y": 0, "w": 6, "h": 8}, {"i": "genes", "x": 6, "y": 0, "w": 6, "h": 8}],
    }
    assert parse_spec(s)[1] == []


def test_dump_roundtrip():
    spec, _ = parse_spec(full_spec())
    dumped = dump_spec(spec)
    assert "size" not in dumped["panels"][0]  # None dropped
    again, errors = parse_spec(dumped)
    assert errors == [] and dump_spec(again) == dumped


def _mut(path_fn):
    s = full_spec()
    path_fn(s)
    return s


BAD = {
    "not an object": lambda s: s.clear() or s.update(bundle=1),
    "wrong version": lambda s: s.update(version=2),
    "missing bundle": lambda s: s.pop("bundle"),
    "unknown top-level field": lambda s: s.update(colour="red"),
    "unknown panel type": lambda s: s["panels"][4].update(type="image"),
    "unknown panel field (typo)": lambda s: s["panels"][0].update(lable={"field": "x"}),
    "unknown plot kind": lambda s: s["panels"][0].update(kind="pie"),
    "id not kebab (camel)": lambda s: (s["panels"][4].update(id="myNotes"), s["layout"][4].update(i="myNotes")),
    "id not kebab (underscore)": lambda s: (s["panels"][4].update(id="my_notes"), s["layout"][4].update(i="my_notes")),
    "id with double dash": lambda s: (s["panels"][4].update(id="a--b"), s["layout"][4].update(i="a--b")),
    "duplicate panel id": lambda s: s["panels"][4].update(id="volcano"),
    "panel without layout": lambda s: s["layout"].pop(),
    "layout without panel": lambda s: s["layout"].append({"i": "ghost", "x": 0, "y": 40, "w": 2, "h": 2}),
    "two layout items for a panel": lambda s: s["layout"].append({"i": "notes", "x": 0, "y": 40, "w": 2, "h": 2}),
    "layout exceeds 12 columns": lambda s: s["layout"][0].update(x=8, w=6),
    "layout zero width": lambda s: s["layout"][0].update(w=0),
    "layout unknown key": lambda s: s["layout"][0].update(color="red"),
    "axis with field and expr": lambda s: s["panels"][0]["x"].update(expr="1"),
    "axis with neither": lambda s: s["panels"][0].update(x={"label": "x"}),
    "color palette and colorscale": lambda s: s["panels"][0]["color"].update(colorscale="Viridis"),
    "scatter without axes": lambda s: (s["panels"][0].pop("x"), s["panels"][0].pop("y")),
    "scatter with matrix fields": lambda s: s["panels"][0].update(rows={"values": ["a"]}),
    "label top_n without by": lambda s: s["panels"][0]["label"].pop("by"),
    "plotly not plain JSON": lambda s: s["panels"][0].update(plotly={"f": float("nan")}),
    "plotly with object": lambda s: s["panels"][0].update(plotly={"f": object()}),
    "pca row-z scale": lambda s: s["panels"][1].update(scale="row-z"),
    "pca color expr": lambda s: s["panels"][1].update(color={"expr": "1"}),
    "pca with x": lambda s: s["panels"][1].update(x={"field": "a"}),
    "heatmap without rows": lambda s: s["panels"][2].pop("rows"),
    "heatmap rows empty": lambda s: s["panels"][2].update(rows={"values": []}),
    "heatmap rows.by not table.column": lambda s: s["panels"][2]["rows"].update(by="padj"),
    "table bad sort dir": lambda s: s["panels"][3]["sort"][0].update(dir="up"),
    "table empty columns": lambda s: s["panels"][3].update(columns=[]),
    "table duplicate columns": lambda s: s["panels"][3].update(columns=["a", "a"]),
    "table page_size 0": lambda s: s["panels"][3].update(page_size=0),
    "widget without code": lambda s: s["panels"][5].pop("code"),
    "widget bad language": lambda s: s["panels"][5].update(language="python"),
    "widget duplicate input": lambda s: s["panels"][5]["inputs"].append({"name": "sites", "sql": "SELECT 2"}),
    "widget input bad name": lambda s: s["panels"][5]["inputs"][0].update(name="1 x"),
    "filter field and expr": lambda s: s["filters"][0].update(expr="padj < 1"),
    "filter without op": lambda s: s["filters"][0].pop("op"),
    "filter bad op": lambda s: s["filters"][0].update(op="~"),
    "filter between scalar": lambda s: s["filters"][2].update(value=5),
    "filter in empty": lambda s: s["filters"][3].update(value=[]),
    "filter scalar op with list": lambda s: s["filters"][0].update(value=[1]),
    "filter duplicate id": lambda s: s["filters"][1].update(id="sig"),
    "filter id not kebab": lambda s: s["filters"][1].update(id="Big FC"),
}


@pytest.mark.parametrize("name", list(BAD))
def test_structural_errors(name):
    s = _mut(BAD[name])
    spec, errors = parse_spec(s)
    assert spec is None, name
    assert errors and all(isinstance(e, str) and e for e in errors)


def test_non_dict_input():
    assert parse_spec([1, 2]) == (None, ["spec must be a JSON object"])
    assert parse_spec(None)[0] is None


def test_errors_are_readable():
    s = full_spec()
    s["panels"][1].update(id="volcano")
    _, errors = parse_spec(s)
    assert any("duplicate panel ids: volcano" in e for e in errors)
    s = full_spec()
    s["layout"].pop()
    _, errors = parse_spec(s)
    assert any("panels without a layout item: editing-lollipop" in e for e in errors)
    s = full_spec()
    s["panels"][0]["x"].update(expr="1")
    _, errors = parse_spec(s)
    assert any(e.startswith("panels.0.plot") and "exactly one of 'field' or 'expr'" in e for e in errors), errors
    assert not any("Value error" in e for e in errors)


def test_input_not_mutated():
    s = full_spec()
    before = copy.deepcopy(s)
    parse_spec(s)
    assert s == before
