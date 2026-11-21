"""Shared fixtures for the acceptance tests (contracts in docs/api.md, criteria in docs/acceptance.md).

Run one phase:  cd backend && uv run pytest tests/acceptance -m phase1
Live LLM tests (need LLM_API_KEY in .env and network):  uv run pytest tests/acceptance -m live
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def pytest_configure(config):
    for m in ["phase1", "phase2", "phase3", "phase4", "live"]:
        config.addinivalue_line("markers", f"{m}: acceptance tests for {m}")


def pytest_collection_modifyitems(config, items):
    if os.getenv("LLM_API_KEY") or (Path(__file__).resolve().parents[3] / ".env").exists():
        return
    skip = pytest.mark.skip(reason="no LLM credentials")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def _load_toy_module():
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    _load_toy_module().make_toy_bundle(d, "toy")
    return d


class ScriptedProvider:
    """LLM provider returning queued responses; records every call (for privacy assertions)."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def queue(self, *responses):
        self.responses.extend(responses)

    def chat(self, messages, tools, model=None):
        from aibex.llm.provider import LLMResponse

        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "model": model})
        if not self.responses:
            return LLMResponse(text="(no more scripted responses)")
        return self.responses.pop(0)


@pytest.fixture()
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture()
def client(data_dir, provider):
    from fastapi.testclient import TestClient

    from aibex.config import Settings
    from aibex.main import create_app

    app = create_app(Settings(data_dir=data_dir, llm_provider="fake"), llm_provider=provider)
    return TestClient(app)


@pytest.fixture()
def session(client):
    r = client.post("/api/sessions", json={"bundle": "toy"})
    assert r.status_code == 200, r.text
    return r.json()


def tool_call(name, arguments, call_id="call_1"):
    from aibex.llm.provider import LLMResponse, ToolCall

    return LLMResponse(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def text(t):
    from aibex.llm.provider import LLMResponse

    return LLMResponse(text=t)


def panel_index(spec, panel_id):
    return next(i for i, p in enumerate(spec["panels"]) if p["id"] == panel_id)


def first_scatter(spec):
    return next(i for i, p in enumerate(spec["panels"]) if p["type"] == "plot" and p.get("kind") == "scatter")


class _Helpers:
    tool_call = staticmethod(tool_call)
    text = staticmethod(text)
    panel_index = staticmethod(panel_index)
    first_scatter = staticmethod(first_scatter)


@pytest.fixture()
def h():
    """Helper functions: h.tool_call(name, args), h.text(t), h.panel_index(spec, id), h.first_scatter(spec)."""
    return _Helpers
