"""System prompt (`aibex/llm/prompts.py`, T23): stays in sync with the code it describes, examples are valid."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from aibex.bundles import load_bundle
from aibex.default_view import default_view
from aibex.expr import ALLOWED_FUNCTIONS
from aibex.llm.chat import run_chat
from aibex.llm.fake import FakeProvider, find_context
from aibex.llm.prompts import SYSTEM_PROMPT, panel_index_text
from aibex.llm.provider import LLMResponse
from aibex.llm.tools import TOOL_SCHEMAS
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


def test_prompt_names_every_tool():
    for t in TOOL_SCHEMAS:
        name = t["function"]["name"]
        if name == "create_widget":  # added to the prompt with T40b
            continue
        assert f"{name}(" in SYSTEM_PROMPT


def test_prompt_lists_exactly_the_allowed_expr_functions():
    m = re.search(r"only the functions (.+?)\.", SYSTEM_PROMPT, re.DOTALL)
    assert m
    listed = {f.strip() for f in m.group(1).replace("\n", " ").split(",")}
    assert listed == set(ALLOWED_FUNCTIONS)


def test_prompt_keeps_core_rules():
    for phrase in ("JSON Patch", "panel index", "200 rows", "never invent", "layout", "kebab-case"):
        assert phrase.lower() in SYSTEM_PROMPT.lower(), phrase
    assert "```" not in SYSTEM_PROMPT  # a stray fence would confuse JSON extraction from the context message


@pytest.mark.parametrize(
    "op",
    [
        {"op": "add", "path": "/filters/-", "value": {"id": "sig", "table": "de", "field": "padj", "op": "<=",
                                                      "value": 0.05, "label": "padj <= 0.05", "enabled": True}},
        {"op": "add", "path": "/filters/-", "value": {"id": "lfc", "table": "de", "expr": "abs(log2FoldChange) > 1",
                                                      "label": "|log2FC| > 1", "enabled": True}},
    ],
)
def test_prompt_filter_examples_validate(session, op):
    session.apply_patch([op])
    assert session.version == 1


def test_prompt_colour_and_plotly_examples_validate(session):
    i = next(k for k, p in enumerate(session.spec["panels"]) if p.get("kind") == "scatter")
    session.apply_patch(
        [
            {"op": "add", "path": f"/panels/{i}/color", "value": {
                "expr": "CASE WHEN padj < 0.05 THEN 'significant' ELSE 'n.s.' END",
                "palette": {"significant": "#d62728", "n.s.": "#bbbbbb"}}},
            {"op": "add", "path": f"/panels/{i}/plotly",
             "value": {"layout": {"yaxis": {"type": "log"}}, "trace": {"marker": {"opacity": 0.5}}}},
        ]
    )
    assert session.version == 1


def test_panel_index_text(session):
    lines = panel_index_text(session.spec).splitlines()
    assert len(lines) == len(session.spec["panels"])
    p0 = session.spec["panels"][0]
    assert lines[0].startswith(f"0: {p0['id']} (")
    assert panel_index_text({"panels": []}) == "(no panels)"


def test_context_message_contains_prompt_index_and_is_readable_by_fake(session):
    calls = []

    class Spy:
        def chat(self, messages, tools, model=None):
            calls.append(messages)
            return LLMResponse(text="ok")

    run_chat(session, Spy(), "hello")
    system = calls[0][0]["content"]
    assert system.startswith(SYSTEM_PROMPT)
    assert panel_index_text(session.spec) in system
    spec, schema = find_context(calls[0])
    assert spec == session.spec and schema and "de" in schema["tables"]
    # and the fake still drives a full change through the real prompt
    run_chat(session, FakeProvider(), "padj below 0.01")
    assert session.version == 1
    assert json.dumps(session.spec).count("padj-lt") == 1
