"""Chat loop (`aibex/llm/chat.py`, docs/api.md → "Chat loop") and the `/chat` endpoint, beyond the A2.2–A2.4 tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.default_view import default_view
from aibex.llm.chat import MAX_PROVIDER_CALLS, chat_events, run_chat, sse_frame
from aibex.llm.fake import DONE, NO_RULE, FakeProvider
from aibex.llm.provider import LLMError, LLMResponse, ToolCall
from aibex.main import create_app
from aibex.sessions import SessionStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _toy(d: Path) -> None:
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(d, "toy")


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    _toy(d)
    return d


@pytest.fixture(scope="module")
def bundle(data_dir):
    return load_bundle(data_dir / "toy" / "bundle.yaml")


@pytest.fixture()
def session(bundle):
    return SessionStore().create("toy", default_view(bundle), lambda _id: bundle)


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools, model=None):
        self.calls.append([dict(m) for m in messages])
        r = self.responses.pop(0) if self.responses else LLMResponse(text="(end)")
        if isinstance(r, Exception):
            raise r
        return r


def _call(name, args, cid="c1"):
    return LLMResponse(tool_calls=[ToolCall(id=cid, name=name, arguments=args)])


def _scatter(spec):
    return next(i for i, p in enumerate(spec["panels"]) if p["type"] == "plot" and p.get("kind") == "scatter")


def _title_patch(i, value):
    return {"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": value}], "summary": f"title {value}"}


def _bad_patch(i):
    return {"patch": [{"op": "replace", "path": f"/panels/{i}/table", "value": "nope"}], "summary": "bad"}


# --- loop ------------------------------------------------------------------------------------------------------
def test_fake_provider_label_end_to_end(session):
    out = run_chat(session, FakeProvider(), "label Gene_001, Gene_002")
    i = _scatter(session.spec)
    assert session.spec["panels"][i]["label"]["values"] == ["Gene_001", "Gene_002"]
    assert session.version == 1 and session.history[-1]["source"] == "llm"
    assert out.reply == DONE
    assert [e["type"] for e in out.events] == ["tool", "tool", "spec", "token", "done"]


def test_fake_provider_no_rule_changes_nothing(session):
    out = run_chat(session, FakeProvider(), "make it pretty")
    assert out.reply == NO_RULE and session.version == 0
    assert not any(e["type"] == "spec" for e in out.events)


def test_context_embeds_schema_spec_and_panel_index(session):
    p = Scripted(LLMResponse(text="hi"))
    run_chat(session, p, "hello")
    system = p.calls[0][0]
    assert system["role"] == "system"
    ctx = json.loads(system["content"].split("```json\n", 1)[1].rsplit("```", 1)[0])
    assert ctx["spec"] == session.spec
    assert ctx["schema"]["tables"] and "rows" not in json.dumps(ctx["schema"])
    assert ctx["panel_index"] == {pp["id"]: k for k, pp in enumerate(session.spec["panels"])}
    assert p.calls[0][-1] == {"role": "user", "content": "hello"}


def test_context_refreshes_spec_after_a_change(session):
    i = _scatter(session.spec)
    p = Scripted(_call("update_view", _title_patch(i, "Renamed")), LLMResponse(text="ok"))
    run_chat(session, p, "rename")
    assert "Renamed" not in p.calls[0][0]["content"]
    assert "Renamed" in p.calls[1][0]["content"]
    # assistant tool-call message + tool result follow the user message in OpenAI format
    assistant, tool = p.calls[1][-2], p.calls[1][-1]
    assert assistant["tool_calls"][0]["function"]["name"] == "update_view"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"])["patch"]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "c1"
    assert json.loads(tool["content"]) == {"ok": True, "version": 1}


def test_earlier_turns_are_sent_as_context(session):
    run_chat(session, Scripted(LLMResponse(text="first answer")), "first question")
    p = Scripted(LLMResponse(text="second answer"))
    run_chat(session, p, "second question")
    roles = [(m["role"], m.get("content")) for m in p.calls[0][1:]]
    assert roles == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "second question"),
    ]


def test_provider_error_becomes_error_event(session):
    out = run_chat(session, Scripted(LLMError("LLM request failed (APIConnectionError): boom")), "hi")
    assert [e["type"] for e in out.events] == ["error", "done"]
    assert "boom" in out.reply and session.version == 0


def test_unexpected_provider_exception_does_not_raise(session):
    out = run_chat(session, Scripted(RuntimeError("kaputt")), "hi")
    assert out.events[-1] == {"type": "done"}
    assert "kaputt" in out.reply


def test_success_resets_failure_count(session):
    i = _scatter(session.spec)
    p = Scripted(
        _call("update_view", _bad_patch(i), "c1"),
        _call("update_view", _title_patch(i, "A"), "c2"),
        _call("update_view", _bad_patch(i), "c3"),
        LLMResponse(text="gave up on the last one"),
    )
    out = run_chat(session, p, "do things")
    assert len(p.calls) == 4
    assert session.version == 1
    assert not any(e["type"] == "error" for e in out.events)


def test_query_failures_do_not_count(session):
    p = Scripted(
        _call("query_data", {"sql": "DROP TABLE genes"}, "c1"),
        _call("query_data", {"sql": "nope"}, "c2"),
        _call("query_data", {"sql": "also nope"}, "c3"),
        LLMResponse(text="could not query"),
    )
    out = run_chat(session, p, "query")
    assert len(p.calls) == 4 and out.reply == "could not query"


def test_two_failures_in_one_response_stop_immediately(session):
    i = _scatter(session.spec)
    two = LLMResponse(
        tool_calls=[
            ToolCall(id="a", name="update_view", arguments=_bad_patch(i)),
            ToolCall(id="b", name="update_view", arguments=_bad_patch(i)),
        ]
    )
    p = Scripted(two, LLMResponse(text="never"))
    out = run_chat(session, p, "break")
    assert len(p.calls) == 1 and session.version == 0
    assert any(e["type"] == "error" for e in out.events)


def test_step_limit_keeps_applied_changes(session):
    i = _scatter(session.spec)
    p = Scripted(*[_call("update_view", _title_patch(i, f"T{k}"), f"c{k}") for k in range(10)])
    out = run_chat(session, p, "loop")
    assert len(p.calls) == MAX_PROVIDER_CALLS
    assert session.version == MAX_PROVIDER_CALLS
    assert out.events[-2]["type"] == "error" and "step limit" in out.reply


def test_empty_text_reply(session):
    out = run_chat(session, Scripted(LLMResponse(text="  ")), "hi")
    assert out.reply and session.version == 0


def test_events_always_end_with_done(session):
    events = list(chat_events(session, Scripted(LLMResponse(text="x")), "hi"))
    assert events[-1] == {"type": "done"}


def test_sse_frame_format():
    assert sse_frame({"type": "tool", "name": "query_data", "status": "ok"}) == (
        'event: tool\ndata: {"name": "query_data", "status": "ok"}\n\n'
    )
    assert sse_frame({"type": "done"}) == "event: done\ndata: {}\n\n"


# --- endpoint --------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


def _sid(client):
    return client.post("/api/sessions", json={"bundle": "toy"}).json()["session_id"]


def test_chat_endpoint_non_stream_with_fake(client):
    sid = _sid(client)
    r = client.post(f"/api/sessions/{sid}/chat?stream=false", json={"message": "padj below 0.05"})
    assert r.status_code == 200
    out = r.json()
    assert set(out) == {"reply", "spec", "version", "events"}
    assert out["version"] == 1
    assert any(f["id"] == "padj-lt" for f in out["spec"]["filters"])
    assert client.get(f"/api/sessions/{sid}").json()["history"][-1]["source"] == "llm"


def test_chat_endpoint_stream_frames(client):
    sid = _sid(client)
    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"message": "label Gene_003"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    frames = [f for f in body.split("\n\n") if f]
    types = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert types[-1] == "done" and "spec" in types
    spec_frame = frames[types.index("spec")]
    payload = json.loads(spec_frame.split("\n", 1)[1].removeprefix("data: "))
    assert payload["version"] == 1 and payload["summary"]


def test_chat_endpoint_errors(client):
    assert client.post("/api/sessions/nope/chat?stream=false", json={"message": "hi"}).status_code == 404
    sid = _sid(client)
    assert client.post(f"/api/sessions/{sid}/chat?stream=false", json={"message": ""}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/chat?stream=false", json={}).status_code == 422
