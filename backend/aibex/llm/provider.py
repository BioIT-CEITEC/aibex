"""LLM provider adapter (docs/api.md, "LLM provider").

`LLMProvider` is the only interface the chat loop talks to. `OpenAICompatibleProvider` wraps any OpenAI-compatible
chat-completions endpoint (default: e-INFRA CZ). `parse_text_fallback` turns a JSON object in a text reply into tool
calls for models that do not call tools; the chat loop applies it (`with_text_fallback`), so it works for every provider.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from aibex.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(Protocol):
    def chat(self, messages: list[dict], tools: list[dict], model: str | None = None) -> LLMResponse: ...


class LLMError(RuntimeError):
    """The provider call failed (network, auth, bad response). The message is safe to show (no secrets)."""


# ---------------------------------------------------------------------------------------------------------------
# JSON-in-text fallback

_FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)```", re.DOTALL)
_MAX_TEXT = 200_000  # do not scan huge replies character by character


def _json_objects(text: str) -> list[Any]:
    """JSON objects found in `text`: fenced ```json blocks first, then bare top-level `{...}` objects."""
    found: list[Any] = []
    for block in _FENCE_RE.findall(text):
        block = block.strip()
        try:
            found.append(json.loads(block))
        except json.JSONDecodeError:
            found.extend(_bare_objects(block))
    if found:
        return found
    return _bare_objects(text)


def _bare_objects(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    out: list[Any] = []
    i = text.find("{")
    while 0 <= i < len(text):
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        out.append(obj)
        i = text.find("{", end)
    return out


def _as_tool_call(obj: Any, n: int) -> ToolCall | None:
    if not isinstance(obj, dict):
        return None
    call_id = f"fallback-{n}"
    tool = obj.get("tool")
    if isinstance(tool, str) and tool.strip():
        args = obj.get("arguments", {})
        if isinstance(args, str):  # some models double-encode
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        if not isinstance(args, dict):
            return None
        return ToolCall(id=call_id, name=tool.strip(), arguments=args)
    if isinstance(obj.get("patch"), list):
        args = {"patch": obj["patch"]}
        if isinstance(obj.get("summary"), str):
            args["summary"] = obj["summary"]
        return ToolCall(id=call_id, name="update_view", arguments=args)
    return None


def parse_text_fallback(text: str) -> list[ToolCall]:
    """Tool calls encoded as JSON in a text reply (docs/api.md fallback).

    Accepted objects: `{"tool": "<name>", "arguments": {...}}` and `{"patch": [...], "summary": "..."}` (= update_view),
    inside a fenced ```json block or bare in the text. Returns [] when nothing usable is found; never raises.
    """
    if not text or "{" not in text:
        return []
    calls: list[ToolCall] = []
    for obj in _json_objects(text[:_MAX_TEXT]):
        call = _as_tool_call(obj, len(calls) + 1)
        if call is not None:
            calls.append(call)
    return calls


def with_text_fallback(response: LLMResponse) -> LLMResponse:
    """`response` unchanged if it has tool calls, else with tool calls parsed from its text (if any)."""
    if response.tool_calls:
        return response
    calls = parse_text_fallback(response.text)
    if not calls:
        return response
    return LLMResponse(text=response.text, tool_calls=calls)


# ---------------------------------------------------------------------------------------------------------------
# OpenAI-compatible provider


def _parse_arguments(raw: Any) -> dict:
    """Tool-call arguments as a dict. Invalid JSON gives `{"_invalid_arguments": raw}` so the tool can report it."""
    if isinstance(raw, dict):
        return raw
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            objs = _json_objects(raw)  # tolerate fences or trailing text around the object
            value = objs[0] if objs else None
        if isinstance(value, dict):
            return value
    return {"_invalid_arguments": str(raw)[:2000]}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute or key access (SDK objects or plain dicts)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def response_from_completion(completion: Any) -> LLMResponse:
    """Convert an OpenAI chat-completion (SDK object or dict) into an `LLMResponse`."""
    choices = _get(completion, "choices") or []
    if not choices:
        raise LLMError("LLM returned no choices")
    message = _get(choices[0], "message")
    if message is None:
        raise LLMError("LLM returned no message")
    text = _get(message, "content") or ""
    if not isinstance(text, str):
        text = str(text)
    calls: list[ToolCall] = []
    for n, tc in enumerate(_get(message, "tool_calls") or [], start=1):
        fn = _get(tc, "function")
        name = _get(fn, "name") if fn is not None else None
        if not name:
            continue
        calls.append(
            ToolCall(
                id=_get(tc, "id") or f"call-{n}",
                name=str(name),
                arguments=_parse_arguments(_get(fn, "arguments")),
            )
        )
    return LLMResponse(text=text, tool_calls=calls)


class OpenAICompatibleProvider:
    """Chat completions with tools against any OpenAI-compatible endpoint (e-INFRA CZ by default)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        client: Any | None = None,
        timeout: float = 120.0,
        temperature: float = 0.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        if client is None:
            from openai import OpenAI

            # max_retries=1: a live demo should fail fast rather than hang on the shared service
            client = OpenAI(base_url=base_url, api_key=api_key or "missing", timeout=timeout, max_retries=1)
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> OpenAICompatibleProvider:
        return cls(settings.llm_base_url, settings.llm_api_key, settings.llm_model_fast, **kwargs)

    def with_timeout(self, timeout: float) -> OpenAICompatibleProvider:
        """A copy with a shorter request timeout and no retry (used for the code model, T42)."""
        client = self._client.with_options(timeout=timeout, max_retries=0)
        return OpenAICompatibleProvider(self.base_url, "", self.model, client=client, timeout=timeout,
                                        temperature=self.temperature)

    def chat(self, messages: list[dict], tools: list[dict], model: str | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # any SDK/network error becomes a readable LLMError
            raise LLMError(f"LLM request failed ({type(exc).__name__}): {_short(exc)}") from exc
        return response_from_completion(completion)

    def chat_text(
        self,
        messages: list[dict],
        model: str | None = None,
        *,
        max_seconds: float = 150.0,
        idle_seconds: float = 60.0,
        extra_body: dict | None = None,
    ) -> str:
        """Text-only answer, streamed (T42, widget code). No tools, no retry.

        A non-streamed request must finish the whole answer within the read timeout, which a long code answer on the
        shared service often does not. Streamed, only `idle_seconds` without a new chunk (incl. the first) or more than
        `max_seconds` in total ends the call with an `LLMError`.
        """
        start = time.monotonic()
        parts: list[str] = []
        reasoning = n_chunks = 0
        try:
            client = self._client.with_options(timeout=idle_seconds, max_retries=0)
            stream = client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=self.temperature,
                stream=True,
                **({"extra_body": extra_body} if extra_body else {}),
            )
            try:
                for chunk in stream:
                    n_chunks += 1
                    for choice in _get(chunk, "choices") or []:
                        delta = _get(choice, "delta")
                        if delta is None:
                            continue
                        text = _get(delta, "content")
                        if text:
                            parts.append(str(text))
                        # reasoning models (vLLM / OpenAI-compatible) stream their thinking separately
                        think = _get(delta, "reasoning_content") or _get(delta, "reasoning")
                        if think:
                            reasoning += len(str(think))
                    if time.monotonic() - start > max_seconds:
                        raise LLMError(
                            f"LLM answer took longer than {max_seconds:.0f} s ({len(''.join(parts))} answer chars, "
                            f"{reasoning} reasoning chars, {n_chunks} chunks so far)"
                        )
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
        except LLMError:
            raise
        except Exception as exc:  # any SDK/network error becomes a readable LLMError
            raise LLMError(f"LLM request failed ({type(exc).__name__}): {_short(exc)}") from exc
        return "".join(parts)


def provider_from_settings(settings: Settings) -> LLMProvider:
    """`FakeProvider` for `llm_provider == "fake"`, else `OpenAICompatibleProvider` (no network call here)."""
    if settings.llm_provider == "fake":
        from aibex.llm.fake import FakeProvider

        return FakeProvider()
    return OpenAICompatibleProvider.from_settings(settings)


def _short(exc: Exception, limit: int = 300) -> str:
    msg = " ".join(str(exc).split())
    return msg[:limit] + ("…" if len(msg) > limit else "")
