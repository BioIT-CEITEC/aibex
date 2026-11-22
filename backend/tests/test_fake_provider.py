"""FakeProvider rules (docs/api.md → "LLM provider") and provider selection in create_app."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.default_view import default_view
from aibex.llm.fake import DONE, NO_RULE, FakeProvider, find_context
from aibex.llm.provider import OpenAICompatibleProvider, provider_from_settings
from aibex.main import create_app
from aibex.sessions import SessionStore
from aibex.validate import validate_spec

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
def spec(bundle):
    return default_view(bundle)


def _messages(spec, schema, prompt, fenced=True):
    ctx = json.dumps({"spec": spec, "schema": schema})
    system = f"You are AIBEX.\n```json\n{ctx}\n```" if fenced else f"Context: {ctx} end."
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


def _ask(spec, bundle, prompt, **kw):
    return FakeProvider().chat(_messages(spec, bundle.schema(), prompt, **kw), tools=[])


def _apply(bundle, spec, call):
    """Apply an update_view call through the real session store (validated JSON Patch)."""
    s = SessionStore().create("toy", spec, lambda _id: bundle)
    s.apply_patch(call.arguments["patch"], call.arguments.get("summary"), source="llm")
    return s.spec


def _first_scatter(spec):
    return next(i for i, p in enumerate(spec["panels"]) if p["type"] == "plot" and p.get("kind") == "scatter")


# --- rules -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("prompt", ["Label Gene_001, Gene_002", "label gene_001 and Gene_002.", "LABEL Gene_001 Gene_002"])
def test_label_rule_replaces_values(spec, bundle, prompt):
    r = _ask(spec, bundle, prompt)
    assert r.text == "" and len(r.tool_calls) == 1
    call = r.tool_calls[0]
    assert call.name == "update_view"
    i = _first_scatter(spec)
    (op,) = call.arguments["patch"]
    assert op["op"] == "replace" and op["path"] == f"/panels/{i}/label/values"
    assert [g.lower() for g in op["value"]] == ["gene_001", "gene_002"]
    new = _apply(bundle, spec, call)
    assert len(new["panels"][i]["label"]["values"]) == 2


def test_label_keeps_gene_case(spec, bundle):
    (call,) = _ask(spec, bundle, "label Gria2, CYFIP2").tool_calls
    assert call.arguments["patch"][0]["value"] == ["Gria2", "CYFIP2"]


def test_label_without_label_object_uses_selection_key(spec, bundle):
    i = _first_scatter(spec)
    del spec["panels"][i]["label"]
    spec["selection"] = {"key": "gene_id"}
    (call,) = _ask(spec, bundle, "label Gene_003").tool_calls
    (op,) = call.arguments["patch"]
    assert op == {"op": "add", "path": f"/panels/{i}/label", "value": {"field": "gene_id", "values": ["Gene_003"]}}


def test_padj_rule_adds_filter_that_validates(spec, bundle):
    (call,) = _ask(spec, bundle, "Show only padj below 0.001 please").tool_calls
    assert call.name == "update_view"
    (op,) = call.arguments["patch"]
    table = spec["panels"][_first_scatter(spec)]["table"]
    assert op["op"] == "add" and op["path"] == "/filters/-"
    assert op["value"] == {"id": "padj-lt", "table": table, "field": "padj", "op": "<", "value": 0.001, "enabled": True}
    new = _apply(bundle, spec, call)
    assert [f["id"] for f in new["filters"]] == ["padj-lt"]


def test_padj_rule_twice_replaces_filter(spec, bundle):
    (call,) = _ask(spec, bundle, "padj below 0.01").tool_calls
    spec2 = _apply(bundle, spec, call)
    (call2,) = _ask(spec2, bundle, "padj below 1e-5").tool_calls
    (op,) = call2.arguments["patch"]
    assert op["op"] == "replace" and op["path"] == "/filters/0" and op["value"]["value"] == 1e-5
    assert len(_apply(bundle, spec2, call2)["filters"]) == 1


@pytest.mark.parametrize("prompt,steps", [("undo", 1), ("Undo 3", 3), ("  UNDO!", 1)])
def test_undo_rule(spec, bundle, prompt, steps):
    (call,) = _ask(spec, bundle, prompt).tool_calls
    assert call.name == "undo_view" and call.arguments == {"steps": steps}


def test_add_widget_rule(spec, bundle):
    (call,) = _ask(spec, bundle, "add widget").tool_calls
    assert call.name == "create_widget"
    args = call.arguments
    assert args["id"] == "row-count"
    first_table = next(iter(bundle.schema()["tables"]))
    assert args["inputs"] == [{"name": "rows", "sql": f"SELECT * FROM {first_table} LIMIT 50"}]
    assert "export default function Widget" in args["code"]
    # the widget panel validates (layout placement itself is the create_widget tool's job, T40b)
    spec["panels"].append({"type": "widget", **{k: args[k] for k in ("id", "title", "inputs", "code")}})
    spec["layout"].append({"i": "row-count", "x": 0, "y": 100, "w": 6, "h": 8})
    _, errors = validate_spec(spec, bundle)
    assert errors == []


@pytest.mark.parametrize("prompt", ["tell me a joke", "", "relabel nothing?"])
def test_no_rule_matched(spec, bundle, prompt):
    r = _ask(spec, bundle, prompt)  # "relabel" is not the word "label"
    assert r.tool_calls == [] and NO_RULE in r.text


def test_after_tool_result_answers_done(spec, bundle):
    msgs = _messages(spec, bundle.schema(), "label Gene_001")
    msgs += [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "fake-1", "type": "function"}]},
        {"role": "tool", "tool_call_id": "fake-1", "content": json.dumps({"ok": True, "version": 1})},
    ]
    r = FakeProvider().chat(msgs, tools=[])
    assert r.text == DONE and r.tool_calls == []


def test_uses_last_user_message(spec, bundle):
    msgs = _messages(spec, bundle.schema(), "label Gene_001")
    msgs += [{"role": "assistant", "content": DONE}, {"role": "user", "content": "undo"}]
    (call,) = FakeProvider().chat(msgs, tools=[]).tool_calls
    assert call.name == "undo_view"


def test_bare_json_context_is_found(spec, bundle):
    (call,) = _ask(spec, bundle, "label Gene_007", fenced=False).tool_calls
    assert call.name == "update_view"


def test_newest_spec_wins(spec, bundle):
    old = json.loads(json.dumps(spec))
    old["panels"][_first_scatter(old)]["kind"] = "line"  # no scatter in the old spec
    msgs = [{"role": "system", "content": json.dumps({"spec": old})}, {"role": "user", "content": json.dumps(spec)}]
    found, _ = find_context(msgs)
    assert found == spec


def test_without_context_no_change(spec, bundle):
    r = FakeProvider().chat([{"role": "user", "content": "label Gene_001"}], tools=[])
    assert r.tool_calls == [] and NO_RULE in r.text
    r = FakeProvider().chat([{"role": "user", "content": "add widget"}], tools=[])
    assert r.tool_calls == [] and NO_RULE in r.text


def test_content_parts_are_read(spec, bundle):
    msgs = _messages(spec, bundle.schema(), "x")
    msgs[-1]["content"] = [{"type": "text", "text": "undo 2"}]
    (call,) = FakeProvider().chat(msgs, tools=[]).tool_calls
    assert call.arguments == {"steps": 2}


# --- provider selection ----------------------------------------------------------------------------------------
def test_provider_from_settings(tmp_path):
    assert isinstance(provider_from_settings(Settings(data_dir=tmp_path, llm_provider="fake")), FakeProvider)
    p = provider_from_settings(Settings(data_dir=tmp_path, llm_provider="openai", llm_api_key=""))
    assert isinstance(p, OpenAICompatibleProvider)


def test_create_app_selects_provider(tmp_path):
    assert isinstance(create_app(Settings(data_dir=tmp_path, llm_provider="fake")).state.llm_provider, FakeProvider)
    app = create_app(Settings(data_dir=tmp_path, llm_provider="openai", llm_api_key=""))
    assert isinstance(app.state.llm_provider, OpenAICompatibleProvider)


def test_injected_provider_wins(tmp_path):
    injected = FakeProvider()
    assert create_app(Settings(data_dir=tmp_path, llm_provider="openai"), llm_provider=injected).state.llm_provider is injected
