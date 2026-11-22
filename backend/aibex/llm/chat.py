"""Chat loop: one user message → provider calls + tool calls → events. Contract: docs/api.md → "Chat loop".

`chat_events(session, provider, message)` is a generator of event dicts `{"type": ..., ...payload}` (types `token`,
`tool`, `spec`, `error`, `done`); the `/chat` endpoint streams them as SSE or collects them (`run_chat`).

Rules:
- every provider call gets a fresh context: system prompt + the bundle schema, the current spec and a panel index as
  JSON (FakeProvider reads them from there), the last few chat turns, then the messages of this turn;
- a reply without tool calls is parsed for a JSON tool call (`with_text_fallback`); if none, the text is the reply and
  nothing changes;
- max 8 provider calls per message (then `error` "step limit");
- a rejected `update_view`/`create_widget` sends the errors back as the tool result; 2 rejected attempts in a row
  (an applied change resets the count) stop the loop with an `error` event and no further provider call;
- provider failures (`LLMError` or anything else) become an `error` event; the loop never raises.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from aibex.llm.prompts import SYSTEM_PROMPT, panel_index_text
from aibex.llm.provider import LLMProvider, LLMResponse, with_text_fallback
from aibex.llm.tools import TOOL_SCHEMAS, run_tool
from aibex.llm.widget_code import make_code_writer
from aibex.sessions import Session

MAX_PROVIDER_CALLS = 8
MAX_FAILED_CHANGES = 2  # rejected update_view/create_widget in a row
HISTORY_MESSAGES = 6  # earlier chat messages (user + assistant) sent as context
MAX_TRANSCRIPT = 40  # chat messages kept per session
MAX_REPLY_IN_HISTORY = 2000


@dataclass
class ChatResult:
    reply: str
    events: list[dict] = field(default_factory=list)


def _context_message(session: Session) -> dict:
    """System prompt + schema, current spec and panel index as one fenced JSON block (no table rows)."""
    spec = session.spec
    panel_index = {p.get("id"): i for i, p in enumerate(spec.get("panels", [])) if isinstance(p, dict)}
    context = {"schema": session.bundle.schema(), "spec": spec, "panel_index": panel_index}
    body = json.dumps(context, ensure_ascii=False, default=str)
    return {
        "role": "system",
        "content": (
            f"{SYSTEM_PROMPT}\n\n# Current panels (index: id)\n{panel_index_text(spec)}\n\n"
            f"# Current bundle schema, view spec and panel index (JSON)\n```json\n{body}\n```"
        ),
    }


def _assistant_message(response: LLMResponse) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": response.text or None}
    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False, default=str)},
            }
            for c in response.tool_calls
        ]
    return msg


def _remember(session: Session, message: str, reply: str) -> None:
    with session.lock:
        session.chat.append({"role": "user", "content": message})
        session.chat.append({"role": "assistant", "content": reply[:MAX_REPLY_IN_HISTORY]})
        del session.chat[:-MAX_TRANSCRIPT]


def chat_events(
    session: Session, provider: LLMProvider, message: str, model: str | None = None, code_model: str | None = None
) -> Iterator[dict]:
    """Run the loop for one user message, yielding events; always ends with `done`. Never raises.

    `code_model` is the model that writes widget code when `create_widget` gets a `description` (T42).
    """
    state = {"reply": ""}
    try:
        yield from _loop(session, provider, message, model, code_model, state)
    except Exception as exc:  # noqa: BLE001 – the loop must never crash the request
        state["reply"] = f"Chat failed: {type(exc).__name__}: {str(exc)[:300]}"
        yield {"type": "error", "message": state["reply"]}
    _remember(session, message, state["reply"])
    yield {"type": "done"}


def _loop(
    session: Session, provider: LLMProvider, message: str, model: str | None, code_model: str | None, state: dict
) -> Iterator[dict]:
    code_writer = make_code_writer(session.bundle, provider, code_model, fallback_model=model)
    with session.lock:
        earlier = [dict(m) for m in session.chat[-HISTORY_MESSAGES:]]
    turn: list[dict] = [{"role": "user", "content": message}]
    failed = 0
    for n_call in range(1, MAX_PROVIDER_CALLS + 1):
        messages = [_context_message(session), *earlier, *turn]
        try:
            response = with_text_fallback(provider.chat(messages, TOOL_SCHEMAS, model=model))
        except Exception as exc:  # noqa: BLE001 – LLMError or a broken provider: report, change nothing more
            state["reply"] = f"The language model could not be reached: {exc}"
            yield {"type": "error", "message": state["reply"]}
            return
        if not response.tool_calls:
            state["reply"] = response.text.strip() or "(the model returned an empty reply)"
            yield {"type": "token", "text": state["reply"]}
            return
        turn.append(_assistant_message(response))
        for call in response.tool_calls:
            yield {"type": "tool", "name": call.name, "status": "running"}
            outcome = run_tool(session, call.name, call.arguments, code_writer)
            turn.append({"role": "tool", "tool_call_id": call.id, "content": outcome.content()})
            ok = outcome.result.get("ok", True) is not False
            yield {"type": "tool", "name": call.name, "status": "ok" if ok else "error"}
            if outcome.changed:
                failed = 0
                yield {"type": "spec", "spec": session.spec, "version": session.version, "summary": outcome.summary}
            elif outcome.failed_change:
                failed += 1
                if failed >= MAX_FAILED_CHANGES:
                    errors = "; ".join(str(e) for e in outcome.result.get("errors", []))[:500]
                    state["reply"] = (
                        f"I could not make a valid change after {failed} attempts; the rejected changes were not "
                        f"applied. Last error: {errors}"
                    )
                    yield {"type": "error", "message": state["reply"]}
                    return
        if n_call == MAX_PROVIDER_CALLS:
            state["reply"] = (
                f"Stopped: step limit of {MAX_PROVIDER_CALLS} model calls reached. "
                "Changes applied so far are kept (use undo to revert them)."
            )
            yield {"type": "error", "message": state["reply"]}
            return


def run_chat(
    session: Session, provider: LLMProvider, message: str, model: str | None = None, code_model: str | None = None
) -> ChatResult:
    """Collect the events of one chat turn; `reply` = final text or the error message."""
    events = list(chat_events(session, provider, message, model, code_model))
    reply = ""
    for e in events:
        if e["type"] == "token":
            reply += e["text"]
        elif e["type"] == "error":
            reply = e["message"]
    return ChatResult(reply=reply, events=events)


def sse_frame(event: dict) -> str:
    """`event: <type>\\ndata: <json payload>\\n\\n` (docs/api.md → "Chat events")."""
    payload = {k: v for k, v in event.items() if k != "type"}
    return f"event: {event['type']}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
