"""T42: widget code written by the code model (`create_widget` with `description`, aibex/llm/widget_code.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aibex.bundles import load_bundle
from aibex.default_view import default_view
from aibex.llm.chat import run_chat
from aibex.llm.provider import LLMError, LLMResponse, ToolCall
from aibex.llm.tools import run_tool
from aibex.llm.widget_code import (
    WIDGET_CODE_PROMPT,
    WidgetCodeError,
    build_messages,
    extract_code,
    input_columns,
    make_code_writer,
)
from aibex.sessions import SessionStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CODE = "export default function Widget({ data }) {\n  return <div>{data.inputs.sites.rows.length}</div>;\n}\n"
INPUTS = [{"name": "sites", "sql": "SELECT site_id, delta FROM editing WHERE gene_id = $selected"}]
DESC = "Show the number of editing sites of the selected gene."


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


class Writer:
    """Stub code model: returns the queued answers in order and records its calls."""

    def __init__(self, *codes):
        self.codes = list(codes)
        self.calls = []

    def __call__(self, description, inputs, previous_code, errors):
        self.calls.append({"description": description, "inputs": inputs, "previous": previous_code, "errors": errors})
        code = self.codes.pop(0)
        if isinstance(code, Exception):
            raise code
        return code


def _widget(session, writer, **kw):
    args = {"id": "site-count", "title": "Sites", "inputs": INPUTS, "description": DESC, **kw}
    return run_tool(session, "create_widget", args, writer)


# --- extract_code ---------------------------------------------------------------------------------------------------
def test_extract_code_from_fence_text_and_bare():
    assert extract_code(f"Here you go:\n```tsx\n{CODE}```\nEnjoy") == CODE
    assert extract_code(f"```\n// helper\n```\n```jsx\n{CODE}```") == CODE  # block with export default wins
    assert extract_code(CODE) == CODE
    assert extract_code(f"```tsx\n{CODE}") == CODE  # unterminated fence


@pytest.mark.parametrize("text", ["", "Sorry, I cannot.", "```tsx\nfunction Widget() {}\n```"])
def test_extract_code_without_component_is_error(text):
    with pytest.raises(WidgetCodeError, match="export default"):
        extract_code(text)


# --- prompt for the code model ---------------------------------------------------------------------------------------
def test_input_columns_without_rows(bundle):
    cols = input_columns(bundle, INPUTS[0]["sql"])
    assert [c for c, _ in cols] == ["site_id", "delta"] and all(t for _, t in cols)


def test_build_messages_has_contract_columns_previous_code_and_errors(bundle):
    msgs = build_messages(bundle, DESC, INPUTS, "export default function Old() {}", ["panels[5].code: bad"])
    assert msgs[0] == {"role": "system", "content": WIDGET_CODE_PROMPT}
    user = msgs[1]["content"]
    assert DESC in user and "data.inputs.sites" in user and "site_id (" in user and "delta (" in user
    assert "function Old" in user and "panels[5].code: bad" in user
    assert "data.inputs.<name>" in WIDGET_CODE_PROMPT and "export default function Widget" in WIDGET_CODE_PROMPT


def test_build_messages_contains_no_rows(bundle):
    user = build_messages(bundle, DESC, [{"name": "all", "sql": "SELECT * FROM editing"}], None, None)[1]["content"]
    rows = bundle.cursor().execute("SELECT site_id FROM editing LIMIT 5").fetchall()
    assert not any(str(r[0]) in user for r in rows)


class RecordingProvider:
    def __init__(self, text="", exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def chat(self, messages, tools, model=None):
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        if self.exc:
            raise self.exc
        return LLMResponse(text=self.text)


def test_make_code_writer_uses_code_model_without_tools(bundle):
    p = RecordingProvider(text=f"```tsx\n{CODE}```")
    assert make_code_writer(bundle, p, "coder")(DESC, INPUTS, None, None) == CODE
    assert p.calls[0]["model"] == "coder" and p.calls[0]["tools"] == []


def test_make_code_writer_provider_failure_is_readable(bundle):
    w = make_code_writer(bundle, RecordingProvider(exc=LLMError("timeout")), "coder")
    with pytest.raises(WidgetCodeError, match="could not be reached: timeout"):
        w(DESC, INPUTS, None, None)


class FlakyCodeModel:
    """The code model ('coder') times out; the chat model answers. Optionally supports with_timeout."""

    def __init__(self):
        self.calls, self.timeouts = [], []

    def with_timeout(self, t):
        self.timeouts.append(t)
        return self

    def chat(self, messages, tools, model=None):
        self.calls.append(model)
        if model == "coder":
            raise LLMError("LLM request failed (APITimeoutError): Request timed out.")
        return LLMResponse(text=f"```tsx\n{CODE}```")


def test_code_model_failure_falls_back_to_chat_model(bundle):
    p = FlakyCodeModel()
    w = make_code_writer(bundle, p, "coder", fallback_model="agentic")
    assert w(DESC, INPUTS, None, None) == CODE
    assert p.calls == ["coder", "agentic"] and p.timeouts == [90.0] and w.used_fallback


def test_fallback_is_reported_in_tool_result(session):
    w = make_code_writer(session.bundle, FlakyCodeModel(), "coder", fallback_model=None)
    out = _widget(session, w)
    assert out.changed and out.result["code_by"] == "chat model (the code model failed)"


def test_with_timeout_copies_provider_with_bounded_client():
    from aibex.llm.provider import OpenAICompatibleProvider

    class Client:
        def with_options(self, **kw):
            self.kw = kw
            return "bounded-client"

    c = Client()
    p = OpenAICompatibleProvider("http://x", "k", "agentic", client=c).with_timeout(90)
    assert c.kw == {"timeout": 90, "max_retries": 0} and p._client == "bounded-client" and p.model == "agentic"


class StreamClient:
    """Fake OpenAI client: `create(stream=True)` yields chunks with `choices[0].delta.content`."""

    def __init__(self, pieces=(), exc=None, on_chunk=None):
        self.pieces, self.exc, self.on_chunk = list(pieces), exc, on_chunk
        self.options, self.kwargs, self.closed = None, None, False
        self.chat = type("Chat", (), {"completions": self})()

    def with_options(self, **kw):
        self.options = kw
        return self

    def create(self, **kw):
        self.kwargs = kw
        if self.exc:
            raise self.exc
        return self

    def __iter__(self):
        for p in self.pieces:
            if self.on_chunk:
                self.on_chunk()
            yield {"choices": [{"delta": {"content": p}}]}
        yield {"choices": [{"delta": {}}]}  # final chunk without content
        yield {"choices": []}  # usage-only chunk

    def close(self):
        self.closed = True


def test_chat_text_streams_and_joins_content():
    from aibex.llm.provider import OpenAICompatibleProvider

    c = StreamClient(["```tsx\n", CODE[:20], CODE[20:], "```"])
    text = OpenAICompatibleProvider("http://x", "k", "agentic", client=c).chat_text(
        [{"role": "user", "content": "hi"}], model="coder", max_seconds=100, idle_seconds=30
    )
    assert extract_code(text) == CODE
    assert c.kwargs["stream"] is True and c.kwargs["model"] == "coder" and "tools" not in c.kwargs
    assert "extra_body" not in c.kwargs
    assert c.options == {"timeout": 30, "max_retries": 0} and c.closed
    OpenAICompatibleProvider("http://x", "k", "m", client=c).chat_text([], extra_body={"reasoning_effort": "low"})
    assert c.kwargs["extra_body"] == {"reasoning_effort": "low"}


def test_chat_text_total_deadline(monkeypatch):
    from aibex.llm import provider as prov

    clock = iter(range(0, 1000, 60))
    monkeypatch.setattr(prov.time, "monotonic", lambda: next(clock))
    c = StreamClient(["a", "b", "c", "d"])
    with pytest.raises(LLMError, match="longer than 100 s"):
        prov.OpenAICompatibleProvider("http://x", "k", "m", client=c).chat_text([], max_seconds=100)
    assert c.closed


def test_chat_text_client_error_is_llm_error():
    from aibex.llm.provider import OpenAICompatibleProvider

    c = StreamClient(exc=TimeoutError("read timed out"))
    with pytest.raises(LLMError, match="TimeoutError"):
        OpenAICompatibleProvider("http://x", "k", "m", client=c).chat_text([])


class StreamingProvider:
    """Has chat_text (like the real provider): coder fails, agentic answers; chat must not be used."""

    def __init__(self, coder_ok=False):
        self.coder_ok, self.calls = coder_ok, []

    def chat(self, messages, tools, model=None):
        raise AssertionError("chat() must not be used when chat_text exists")

    def chat_text(self, messages, model=None, *, max_seconds, idle_seconds, extra_body=None):
        from aibex.llm.widget_code import CODE_EXTRA_BODY

        assert extra_body == CODE_EXTRA_BODY
        self.calls.append((model, max_seconds, idle_seconds))
        if model == "coder" and not self.coder_ok:
            raise LLMError("LLM answer took longer than 150 s")
        return f"```tsx\n{CODE}```"


def test_code_writer_prefers_streaming(bundle):
    from aibex.llm.widget_code import CODE_FALLBACK_MAX, CODE_STREAM_IDLE, CODE_STREAM_MAX

    p = StreamingProvider(coder_ok=True)
    w = make_code_writer(bundle, p, "coder", fallback_model="agentic")
    assert w(DESC, INPUTS, None, None) == CODE and not w.used_fallback
    assert p.calls == [("coder", CODE_STREAM_MAX, CODE_STREAM_IDLE)]

    p = StreamingProvider()
    w = make_code_writer(bundle, p, "coder", fallback_model="agentic")
    assert w(DESC, INPUTS, None, None) == CODE and w.used_fallback
    assert [c[:2] for c in p.calls] == [("coder", CODE_STREAM_MAX), ("agentic", CODE_FALLBACK_MAX)]


# --- create_widget with description ---------------------------------------------------------------------------------
def test_description_uses_code_writer(session):
    w = Writer(CODE)
    out = _widget(session, w)
    assert out.changed and out.result == {"ok": True, "version": 1, "panel_id": "site-count", "code_by": "code model"}
    panel = session.spec["panels"][-1]
    assert panel["code"] == CODE and panel["inputs"] == INPUTS and "description" not in panel
    assert w.calls == [{"description": DESC, "inputs": INPUTS, "previous": None, "errors": None}]


def test_explicit_code_wins_over_description(session):
    w = Writer()
    out = _widget(session, w, code=CODE)
    assert out.changed and "code_by" not in out.result and w.calls == []


def test_rejected_code_is_retried_once_with_errors(session):
    w = Writer(CODE + "fetch('https://x');", CODE)
    out = _widget(session, w)
    assert out.changed and session.version == 1
    assert w.calls[1]["errors"] and "fetch" in " ".join(w.calls[1]["errors"])


def test_rejected_twice_changes_nothing(session):
    bad = CODE + "localStorage.x = 1;"
    out = _widget(session, Writer(bad, bad))
    assert out.failed_change and not out.changed and session.version == 0
    assert "localStorage" in " ".join(out.result["errors"])


def test_bad_input_sql_is_reported_before_calling_the_code_model(session):
    w = Writer(CODE)
    out = _widget(session, w, inputs=[{"name": "sites", "sql": "SELECT nope FROM editing"}])
    assert out.failed_change and w.calls == [] and "inputs[0].sql" in out.result["errors"][0]


def test_code_writer_error_goes_back_to_the_model(session):
    out = _widget(session, Writer(WidgetCodeError("the code model could not be reached: 503")))
    assert out.failed_change and "503" in out.result["errors"][0] and session.version == 0


def test_description_without_code_writer_or_neither_is_error(session):
    out = run_tool(session, "create_widget", {"id": "w", "inputs": INPUTS, "description": DESC})
    assert out.failed_change and "no code model" in out.result["errors"][0]
    out = _widget(session, Writer(), description="")
    assert out.failed_change and "'description'" in out.result["errors"][0]


def test_replace_sends_previous_code(session):
    _widget(session, Writer(CODE))
    w = Writer(CODE.replace("<div>", "<div>n = "))
    out = _widget(session, w, description="Prefix the count with 'n = '.", title="")
    assert out.changed and w.calls[0]["previous"] == CODE
    assert session.history[-1]["summary"] == "replace widget site-count"


# --- chat loop: the code model is called with LLM_MODEL_CODE --------------------------------------------------------
class ScriptedProvider:
    """Chat model: one create_widget call with a description, then a text reply. Code model: answers with CODE."""

    def __init__(self):
        self.calls = []

    def chat(self, messages, tools, model=None):
        self.calls.append({"model": model, "tools": [t["function"]["name"] for t in tools]})
        if not tools:
            return LLMResponse(text=f"```tsx\n{CODE}```")
        if any(m.get("role") == "tool" for m in messages):
            return LLMResponse(text="Added the widget.")
        args = {"id": "site-count", "title": "Sites", "inputs": INPUTS, "description": DESC}
        return LLMResponse(tool_calls=[ToolCall(id="c1", name="create_widget", arguments=args)])


def test_chat_loop_routes_widget_code_to_code_model(session):
    p = ScriptedProvider()
    out = run_chat(session, p, "show the editing sites of the selected gene", model=None, code_model="coder")
    assert session.version == 1 and out.reply == "Added the widget."
    assert [c["model"] for c in p.calls] == [None, "coder", None]
    assert p.calls[1]["tools"] == []
    assert session.spec["panels"][-1]["code"] == CODE


class DeadCodeModel(ScriptedProvider):
    """Like ScriptedProvider, but every call without tools (code writing) times out; the chat model would retry."""

    def chat(self, messages, tools, model=None):
        if not tools:
            self.calls.append({"model": model, "tools": []})
            raise LLMError("LLM request failed (APITimeoutError): Request timed out.")
        self.calls.append({"model": model, "tools": [t["function"]["name"] for t in tools]})
        args = {"id": "site-count", "title": "Sites", "inputs": INPUTS, "description": DESC}
        return LLMResponse(tool_calls=[ToolCall(id=f"c{len(self.calls)}", name="create_widget", arguments=args)])


def test_unreachable_code_model_stops_the_loop_after_one_attempt(session):
    p = DeadCodeModel()
    out = run_chat(session, p, "show the editing sites of the selected gene", model="agentic", code_model="coder")
    # one chat call, then coder + fallback (agentic, no tools) both time out → stop, no second create_widget
    assert [c["model"] for c in p.calls] == ["agentic", "coder", "agentic"]
    assert session.version == 0 and "could not be written" in out.reply and "timed out" in out.reply


def test_unreachable_flag_only_for_provider_failures(bundle):
    w = make_code_writer(bundle, RecordingProvider(exc=LLMError("timeout")), "coder")
    with pytest.raises(WidgetCodeError) as info:
        w(DESC, INPUTS, None, None)
    assert info.value.unreachable
    w = make_code_writer(bundle, RecordingProvider(text="no code here"), "coder")
    with pytest.raises(WidgetCodeError) as info:
        w(DESC, INPUTS, None, None)
    assert not info.value.unreachable


def test_chat_endpoint_passes_llm_model_code(tmp_path):
    from fastapi.testclient import TestClient

    from aibex.config import Settings
    from aibex.main import create_app

    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(tmp_path, "toy")
    p = ScriptedProvider()
    c = TestClient(create_app(Settings(data_dir=tmp_path, llm_model_code="my-coder"), llm_provider=p))
    sid = c.post("/api/sessions", json={"bundle": "toy"}).json()["session_id"]
    r = c.post(f"/api/sessions/{sid}/chat?stream=false", json={"message": "widget please"})
    assert r.status_code == 200 and r.json()["version"] == 1, json.dumps(r.json())[:500]
    assert p.calls[1]["model"] == "my-coder"
