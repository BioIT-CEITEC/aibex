"""Unit tests for aibex.llm.provider (T21a) – mocked client, no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aibex.config import Settings
from aibex.llm.provider import (
    LLMError,
    LLMProvider,
    LLMResponse,
    OpenAICompatibleProvider,
    ToolCall,
    parse_text_fallback,
    response_from_completion,
    with_text_fallback,
)

PATCH = [{"op": "replace", "path": "/panels/0/title", "value": "Volcano"}]


# --- fake OpenAI client ----------------------------------------------------------------------------------------


def _tc(name, arguments, call_id="call_1"):
    return SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def _completion(content=None, tool_calls=None):
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(index=0, message=msg, finish_reason="stop")])


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls: list[dict] = []
        self._result = result
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


def _provider(result=None, error=None):
    client = FakeClient(result, error)
    return OpenAICompatibleProvider("http://x/v1", "k", "agentic", client=client), client


# --- dataclasses / protocol ------------------------------------------------------------------------------------


def test_dataclass_defaults():
    r = LLMResponse()
    assert r.text == "" and r.tool_calls == []
    assert LLMResponse().tool_calls is not r.tool_calls
    assert ToolCall(id="a", name="b", arguments={}).name == "b"


def test_provider_satisfies_protocol():
    p, _ = _provider(_completion("hi"))
    proto: LLMProvider = p  # static check; runtime: has chat()
    assert callable(proto.chat)


# --- OpenAICompatibleProvider ----------------------------------------------------------------------------------


def test_chat_text_reply():
    p, client = _provider(_completion("Hello"))
    r = p.chat([{"role": "user", "content": "hi"}], [])
    assert r == LLMResponse(text="Hello", tool_calls=[])
    sent = client.calls[0]
    assert sent["model"] == "agentic"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "tools" not in sent and "tool_choice" not in sent
    assert sent["temperature"] == 0.0


def test_chat_sends_tools_and_model_override():
    tools = [{"type": "function", "function": {"name": "describe_bundle", "parameters": {"type": "object"}}}]
    p, client = _provider(_completion("x"))
    p.chat([{"role": "user", "content": "hi"}], tools, model="coder")
    sent = client.calls[0]
    assert sent["model"] == "coder"
    assert sent["tools"] == tools and sent["tool_choice"] == "auto"


def test_chat_tool_calls_parsed():
    p, _ = _provider(
        _completion(
            None,
            [
                _tc("update_view", json.dumps({"patch": PATCH, "summary": "rename"}), "c1"),
                _tc("describe_bundle", "", "c2"),
            ],
        )
    )
    r = p.chat([], [])
    assert r.text == ""
    assert r.tool_calls == [
        ToolCall(id="c1", name="update_view", arguments={"patch": PATCH, "summary": "rename"}),
        ToolCall(id="c2", name="describe_bundle", arguments={}),
    ]


def test_tool_call_bad_json_arguments_kept_for_error_report():
    p, _ = _provider(_completion(None, [_tc("update_view", '{"patch": [')]))
    (call,) = p.chat([], []).tool_calls
    assert call.name == "update_view"
    assert call.arguments == {"_invalid_arguments": '{"patch": ['}


def test_tool_call_arguments_in_fence_or_non_object():
    p, _ = _provider(
        _completion(
            None,
            [_tc("query_data", '```json\n{"sql": "SELECT 1"}\n```', "a"), _tc("query_data", "[1, 2]", "b")],
        )
    )
    a, b = p.chat([], []).tool_calls
    assert a.arguments == {"sql": "SELECT 1"}
    assert b.arguments == {"_invalid_arguments": "[1, 2]"}


def test_tool_call_missing_id_gets_one_and_nameless_dropped():
    p, _ = _provider(_completion(None, [_tc("undo_view", '{"steps": 2}', None), _tc("", "{}", "x")]))
    (call,) = p.chat([], []).tool_calls
    assert call.id == "call-1" and call.arguments == {"steps": 2}


def test_provider_does_not_apply_fallback_itself():
    text = "```json\n" + json.dumps({"patch": PATCH}) + "\n```"
    p, _ = _provider(_completion(text))
    r = p.chat([], [])
    assert r.tool_calls == [] and r.text == text


def test_chat_errors_become_llm_error():
    p, _ = _provider(error=ConnectionError("connection refused\n  at host"))
    with pytest.raises(LLMError, match="ConnectionError.*connection refused at host"):
        p.chat([], [])


def test_empty_choices_is_llm_error():
    p, _ = _provider(SimpleNamespace(choices=[]))
    with pytest.raises(LLMError):
        p.chat([], [])


def test_response_from_dict_completion():
    comp = {
        "choices": [
            {
                "message": {
                    "content": "ok",
                    "tool_calls": [
                        {"id": "d1", "function": {"name": "undo_view", "arguments": '{"steps": 1}'}}
                    ],
                }
            }
        ]
    }
    assert response_from_completion(comp) == LLMResponse(
        text="ok", tool_calls=[ToolCall(id="d1", name="undo_view", arguments={"steps": 1})]
    )


def test_from_settings(tmp_path):
    s = Settings(
        data_dir=tmp_path,
        llm_base_url="http://llm/v1",
        llm_api_key="secret",
        llm_model_fast="fast-m",
        llm_provider="openai",
    )
    p = OpenAICompatibleProvider.from_settings(s, client=FakeClient(_completion("x")))
    assert p.model == "fast-m" and p.base_url == "http://llm/v1"


def test_real_sdk_client_constructed_without_network(tmp_path):
    s = Settings(data_dir=tmp_path, llm_api_key="", llm_provider="openai")
    p = OpenAICompatibleProvider.from_settings(s)
    assert p.model == s.llm_model_fast


# --- text fallback ---------------------------------------------------------------------------------------------


def test_fallback_fenced_patch():
    text = "Here is the change:\n```json\n" + json.dumps({"patch": PATCH, "summary": "rename"}) + "\n```"
    assert parse_text_fallback(text) == [
        ToolCall(id="fallback-1", name="update_view", arguments={"patch": PATCH, "summary": "rename"})
    ]


def test_fallback_bare_tool_object_with_surrounding_text():
    text = 'Sure. {"tool": "undo_view", "arguments": {"steps": 2}} Done.'
    assert parse_text_fallback(text) == [ToolCall(id="fallback-1", name="undo_view", arguments={"steps": 2})]


def test_fallback_tool_without_arguments_and_string_arguments():
    assert parse_text_fallback('{"tool": "describe_bundle"}')[0].arguments == {}
    calls = parse_text_fallback('{"tool": "query_data", "arguments": "{\\"sql\\": \\"SELECT 1\\"}"}')
    assert calls[0].arguments == {"sql": "SELECT 1"}


def test_fallback_patch_without_summary():
    (call,) = parse_text_fallback(json.dumps({"patch": PATCH}))
    assert call.arguments == {"patch": PATCH}


def test_fallback_fence_without_language_and_multiple_objects():
    text = (
        "```\n"
        + json.dumps({"tool": "describe_bundle", "arguments": {}})
        + "\n```\nthen\n```json\n"
        + json.dumps({"patch": PATCH})
        + "\n```"
    )
    calls = parse_text_fallback(text)
    assert [c.name for c in calls] == ["describe_bundle", "update_view"]
    assert [c.id for c in calls] == ["fallback-1", "fallback-2"]


def test_fallback_fence_preferred_over_bare_braces():
    text = "Set {x} like this:\n```json\n" + json.dumps({"patch": PATCH}) + "\n```"
    assert [c.name for c in parse_text_fallback(text)] == ["update_view"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I am not sure what you mean.",
        "Use {curly} braces",
        '{"foo": 1}',
        '{"patch": "not a list"}',
        '{"tool": "", "arguments": {}}',
        '{"tool": "x", "arguments": [1]}',
        "```json\n{broken\n```",
        "[1, 2, 3]",
    ],
)
def test_fallback_nothing_usable(text):
    assert parse_text_fallback(text) == []


def test_with_text_fallback():
    real = LLMResponse(tool_calls=[ToolCall(id="c", name="describe_bundle", arguments={})])
    assert with_text_fallback(real) is real
    plain = LLMResponse(text="no json here")
    assert with_text_fallback(plain) is plain
    out = with_text_fallback(LLMResponse(text=json.dumps({"patch": PATCH})))
    assert out.tool_calls[0].name == "update_view" and out.text
