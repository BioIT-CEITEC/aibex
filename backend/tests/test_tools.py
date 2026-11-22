"""LLM tools as plain functions (T22a, docs/api.md → "Chat loop"): describe_bundle, query_data, update_view, undo_view."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aibex.bundles import load_bundle
from aibex.default_view import default_view
from aibex.llm.tools import (
    MAX_TOOL_ROWS,
    TOOL_NAMES,
    TOOL_SCHEMAS,
    describe_bundle,
    query_data,
    run_tool,
    undo_view,
    update_view,
)
from aibex.sessions import SessionStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(d, "toy")
    return load_bundle(d / "toy" / "bundle.yaml")


@pytest.fixture()
def session(bundle):
    return SessionStore().create("toy", default_view(bundle), lambda _id: bundle)


def _title_patch(session, title="New title"):
    return [{"op": "replace", "path": "/panels/0/title", "value": title}]


# --- schemas --------------------------------------------------------------------------------------------------------
def test_tool_schemas_are_openai_functions():
    assert TOOL_NAMES == ["describe_bundle", "query_data", "update_view", "create_widget", "undo_view"]
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
    json.dumps(TOOL_SCHEMAS)  # serialisable


# --- describe_bundle ------------------------------------------------------------------------------------------------
def test_describe_bundle_schema_and_stats(bundle):
    d = describe_bundle(bundle)
    assert d["id"] == "toy" and set(d["tables"]) == {"de", "counts", "editing"}
    assert d["links"] == bundle.schema()["links"]
    de = d["tables"]["de"]
    assert de["row_count"] == 200 and de["key"] == "gene_id"
    lfc = de["columns"]["log2FoldChange"]
    assert lfc["type"] == "float"
    assert set(lfc["stats"]) == {"n_null", "min", "max", "mean"}
    assert lfc["stats"]["min"] <= lfc["stats"]["mean"] <= lfc["stats"]["max"]
    name = de["columns"]["gene_name"]["stats"]
    assert set(name) == {"n_null", "n_distinct", "examples"}
    assert name["n_distinct"] > 10 and len(name["examples"]) == 10
    pos = d["tables"]["editing"]["columns"]["position"]
    assert pos["type"] == "int" and isinstance(pos["stats"]["min"], int)
    assert d["tables"]["counts"].get("matrix") is True
    assert "matrix" not in de
    assert d["samples"]["n"] == len(bundle.samples)
    assert "genotype" in d["samples"]["columns"]


def test_describe_bundle_contains_no_rows(bundle):
    d = describe_bundle(bundle)
    sent = json.dumps(d)
    assert "rows" not in sent
    # 300 unique site ids: only the ≤10 examples may appear
    n_sites = sum(1 for k in range(1, 301) if f"site_{k:04d}" in sent)
    assert n_sites <= 10
    # does not mutate the bundle's own schema
    assert "stats" not in json.dumps(bundle.schema())


def test_describe_bundle_counts_nulls(bundle):
    cur = bundle.cursor()
    (expected,) = cur.execute('SELECT count(*) - count(padj) FROM "de"').fetchone()
    assert describe_bundle(bundle)["tables"]["de"]["columns"]["padj"]["stats"]["n_null"] == expected


# --- query_data -----------------------------------------------------------------------------------------------------
def test_query_data_caps_at_200_rows(bundle):
    out = query_data(bundle, "SELECT * FROM editing")
    assert len(out["rows"]) == MAX_TOOL_ROWS == 200
    assert out["truncated"] is True and out["row_count"] == 300
    assert "note" in out
    assert out["columns"][0] == "site_id"


def test_query_data_cap_cannot_be_raised_by_sql_limit(bundle):
    out = query_data(bundle, "SELECT * FROM editing LIMIT 1000")
    assert len(out["rows"]) == 200 and out["truncated"]


def test_query_data_aggregate(bundle):
    out = query_data(bundle, "SELECT count(*) AS n FROM de WHERE padj < 0.05")
    assert out["columns"] == ["n"] and len(out["rows"]) == 1 and out["truncated"] is False
    assert "note" not in out


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE de",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT 1; SELECT 2",
        "",
        None,
        42,
        "SELEC nonsense",
    ],
)
def test_query_data_rejects_bad_sql(bundle, sql):
    out = query_data(bundle, sql)
    assert out["ok"] is False and out["errors"] and isinstance(out["errors"][0], str)


def test_query_data_unknown_column_is_error(bundle):
    out = query_data(bundle, "SELECT nope FROM de")
    assert out["ok"] is False and "nope" in out["errors"][0]


# --- update_view / undo_view ----------------------------------------------------------------------------------------
def test_update_view_applies_with_source_llm(session):
    out = update_view(session, _title_patch(session), "rename the first panel")
    assert out.result == {"ok": True, "version": 1}
    assert out.changed and not out.failed_change
    assert out.summary == "rename the first panel"
    assert session.spec["panels"][0]["title"] == "New title"
    assert session.history[-1] == {"version": 1, "summary": "rename the first panel", "source": "llm"}


def test_update_view_invalid_patch_returns_errors_and_changes_nothing(session):
    before = session.spec
    out = update_view(session, [{"op": "replace", "path": "/panels/0/table", "value": "nope"}], "bad")
    assert out.result["ok"] is False and any("nope" in e for e in out.result["errors"])
    assert out.failed_change and not out.changed
    assert session.version == 0 and session.spec == before


@pytest.mark.parametrize(
    "patch", [[], "not json", {"no": "op"}, [{"op": "replace", "path": "/nope/0", "value": 1}]]
)
def test_update_view_malformed_patch(session, patch):
    out = update_view(session, patch, "x")
    assert out.result["ok"] is False and out.failed_change and session.version == 0


def test_update_view_accepts_double_encoded_and_single_op(session):
    out = update_view(session, json.dumps(_title_patch(session, "A")), None)
    assert out.result["ok"] and session.spec["panels"][0]["title"] == "A"
    assert out.summary  # default summary lists the ops
    out = update_view(session, _title_patch(session, "B")[0], "single op")
    assert out.result == {"ok": True, "version": 2}


def test_undo_view(session):
    update_view(session, _title_patch(session, "A"), "a")
    update_view(session, _title_patch(session, "B"), "b")
    out = undo_view(session, 2)
    assert out.result == {"ok": True, "version": 3} and out.changed
    assert session.spec["panels"][0]["title"] != "A"
    assert session.history[-1] == {"version": 3, "summary": "undo 2", "source": "llm"}


def test_undo_view_nothing_to_undo_and_bad_steps(session):
    out = undo_view(session)
    assert out.result["ok"] is False and not out.changed and not out.failed_change
    for bad in (0, -1, "x", [1]):
        out = undo_view(session, bad)
        assert out.result["ok"] is False
    assert session.version == 0


# --- run_tool dispatcher --------------------------------------------------------------------------------------------
def test_run_tool_dispatches(session):
    assert "tables" in run_tool(session, "describe_bundle", {}).result
    assert len(run_tool(session, "query_data", {"sql": "SELECT * FROM de"}).result["rows"]) == 200
    out = run_tool(session, "update_view", {"patch": _title_patch(session), "summary": "t"})
    assert out.changed and session.version == 1
    out = run_tool(session, "undo_view", {})
    assert out.changed and session.version == 2
    json.loads(out.content())


def test_run_tool_never_raises(session):
    out = run_tool(session, "make_coffee", {})
    assert (
        out.result["ok"] is False and "describe_bundle" in out.result["errors"][0] and not out.failed_change
    )
    out = run_tool(session, "update_view", {"_invalid_arguments": "{patch: oops"})
    assert out.result["ok"] is False and out.failed_change
    out = run_tool(session, "update_view", {"summary": "no patch"})
    assert out.result["ok"] is False and out.failed_change
    out = run_tool(session, "query_data", None)
    assert out.result["ok"] is False and not out.failed_change
    out = run_tool(session, "create_widget", {"id": "w"})
    assert out.result["ok"] is False and out.failed_change
    assert session.version == 0


def test_run_tool_catches_unexpected_errors(session, monkeypatch):
    from aibex.llm import tools

    def boom(_bundle):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(tools, "describe_bundle", boom)
    out = run_tool(session, "describe_bundle", {})
    assert out.result["ok"] is False and "disk on fire" in out.result["errors"][0]


# --- create_widget (T40b) -------------------------------------------------------------------------------------------
W_CODE = "export default function Widget({ data }) {\n  return <div>{data.inputs.sites.rows.length}</div>;\n}\n"
W_INPUTS = [{"name": "sites", "sql": "SELECT site_id, delta FROM editing LIMIT 10"}]


def _widget(session, **kw):
    args = {"id": "site-count", "title": "Site count", "inputs": W_INPUTS, "code": W_CODE, **kw}
    return run_tool(session, "create_widget", args)


def test_create_widget_appends_panel_and_bottom_layout(session):
    before = session.spec
    bottom = max(it["y"] + it["h"] for it in before["layout"])
    out = _widget(session)
    assert out.result == {"ok": True, "version": 1, "panel_id": "site-count"} and out.changed
    spec = session.spec
    assert len(spec["panels"]) == len(before["panels"]) + 1
    w = spec["panels"][-1]
    assert w == {
        "id": "site-count",
        "type": "widget",
        "title": "Site count",
        "inputs": W_INPUTS,
        "code": W_CODE,
        "language": "tsx",
    }
    assert spec["layout"][-1] == {"i": "site-count", "x": 0, "y": bottom, "w": 6, "h": 8}
    assert spec["layout"][:-1] == before["layout"]  # other panels untouched
    assert session.history[-1] == {"version": 1, "summary": "add widget site-count", "source": "llm"}


def test_create_widget_same_id_replaces_widget(session):
    _widget(session)
    n_panels, layout = len(session.spec["panels"]), session.spec["layout"]
    out = _widget(session, code=W_CODE.replace("<div>", "<div>n = "), title="")
    assert out.changed and session.version == 2
    spec = session.spec
    assert len(spec["panels"]) == n_panels and spec["layout"] == layout
    w = next(p for p in spec["panels"] if p["id"] == "site-count")
    assert "n = " in w["code"] and w["title"] == "Site count"  # empty title keeps the old one
    assert session.history[-1]["summary"] == "replace widget site-count"
    session.undo(1)
    assert "n = " not in next(p for p in session.spec["panels"] if p["id"] == "site-count")["code"]


def test_create_widget_id_of_non_widget_panel_is_error(session):
    plot_id = session.spec["panels"][0]["id"]
    out = _widget(session, id=plot_id)
    assert out.result["ok"] is False and out.failed_change and "already used" in out.result["errors"][0]
    assert session.version == 0


@pytest.mark.parametrize(
    "kw,needle",
    [
        ({"code": W_CODE + "fetch('https://x');"}, "fetch"),
        ({"code": W_CODE + "//" + "x" * 60_000}, ""),
        ({"inputs": [{"name": "sites", "sql": "DROP TABLE editing"}]}, ""),
        ({"inputs": [{"name": "sites", "sql": "SELECT * FROM nope"}]}, ""),
        ({"inputs": [{"name": "sites", "sql": "SELECT * FROM editing WHERE gene_id = $gene"}]}, ""),
        ({"id": "Not Kebab"}, ""),
        ({"language": "python"}, ""),
        ({"code": ""}, "code"),
        ({"inputs": "not json"}, "inputs"),
    ],
)
def test_create_widget_rejects_bad_widgets(session, kw, needle):
    before = session.spec
    out = _widget(session, **kw)
    assert out.result["ok"] is False and out.failed_change and not out.changed
    assert out.result["errors"] and needle in " ".join(out.result["errors"])
    assert session.version == 0 and session.spec == before


def test_create_widget_tolerates_encoded_inputs_and_defaults(session):
    out = run_tool(session, "create_widget", {"id": "w-one", "inputs": json.dumps(W_INPUTS), "code": W_CODE})
    assert out.changed
    w = session.spec["panels"][-1]
    assert w["inputs"] == W_INPUTS and w["language"] == "tsx" and w["title"] == ""
    out = run_tool(session, "create_widget", {"id": "w-two", "code": W_CODE})  # no inputs = no data
    assert out.changed and session.spec["panels"][-1]["inputs"] == []


def test_fake_add_widget_end_to_end(session):
    """FakeProvider 'add widget' → chat loop → create_widget applied (the e2e E4.1 path)."""
    from aibex.llm.chat import run_chat
    from aibex.llm.fake import FakeProvider

    out = run_chat(session, FakeProvider(), "add widget")
    assert session.version == 1, out
    assert any(p["id"] == "row-count" and p["type"] == "widget" for p in session.spec["panels"])
    assert any(it["i"] == "row-count" for it in session.spec["layout"])
