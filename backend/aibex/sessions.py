"""In-memory sessions with a validated spec store and undo/redo history. Contract: docs/api.md ("Versions and history").

A session holds an undo stack of applied specs (`_stack`) with a pointer (`_pos`) to the current one, plus a flat
`history` list with one entry per applied version (init, patches, chat changes, undo, redo). Undo/redo move the pointer
and record a new version; a new change after an undo drops the redo part of the stack. Every change is a RFC 6902
JSON Patch that is validated (structural + semantic) before it is applied; an invalid patch changes nothing.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonpatch

from aibex.bundles import Bundle
from aibex.validate import validate_spec

Source = Literal["init", "user", "llm"]

MAX_SESSIONS = 200  # in-memory store; the oldest sessions are dropped beyond this


class SessionNotFound(KeyError):
    pass


class PatchError(ValueError):
    """The patch cannot be applied or the result does not validate; `errors` are readable, repairable messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class NothingToUndo(ValueError):
    pass


@dataclass
class Session:
    session_id: str
    bundle_id: str
    get_bundle: Callable[[str], Bundle] = field(repr=False)
    _stack: list[dict] = field(default_factory=list)
    _pos: int = 0
    version: int = 0
    history: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def bundle(self) -> Bundle:
        """The current bundle, resolved on each use (the registry reloads changed bundles and closes old ones)."""
        return self.get_bundle(self.bundle_id)

    @property
    def spec(self) -> dict:
        """A copy of the current spec (callers may mutate it freely)."""
        return copy.deepcopy(self._stack[self._pos])

    @property
    def can_undo(self) -> int:
        return self._pos

    @property
    def can_redo(self) -> int:
        return len(self._stack) - 1 - self._pos

    def _record(self, summary: str, source: Source) -> None:
        self.history.append({"version": self.version, "summary": summary, "source": source})

    def apply_patch(self, patch: Any, summary: str | None = None, source: Source = "user") -> dict:
        """Validate and apply a JSON Patch; returns the new spec. Raises PatchError, state unchanged on failure."""
        with self.lock:
            new_spec = check_patch(self._stack[self._pos], patch, self.bundle)
            del self._stack[self._pos + 1 :]
            self._stack.append(new_spec)
            self._pos += 1
            self.version += 1
            self._record(summary or _describe_patch(patch), source)
            return self.spec

    def replace_spec(self, spec: dict, summary: str, source: Source = "user") -> dict:
        """Apply a whole new spec as one undoable version (e.g. load-view); validated like a patch."""
        return self.apply_patch([{"op": "replace", "path": "", "value": spec}], summary, source)

    def undo(self, steps: int = 1, source: Source = "user") -> dict:
        """Move back `steps` applied changes (clamped to what exists); NothingToUndo when at the initial spec."""
        with self.lock:
            if self._pos == 0:
                raise NothingToUndo("nothing to undo")
            n = min(max(1, steps), self._pos)
            self._pos -= n
            self.version += 1
            self._record("undo" if n == 1 else f"undo {n}", source)
            return self.spec

    def redo(self, steps: int = 1, source: Source = "user") -> dict:
        """Move forward `steps` undone changes (clamped); NothingToUndo when there is nothing to redo."""
        with self.lock:
            if self.can_redo == 0:
                raise NothingToUndo("nothing to redo")
            n = min(max(1, steps), self.can_redo)
            self._pos += n
            self.version += 1
            self._record("redo" if n == 1 else f"redo {n}", source)
            return self.spec

    def state(self) -> dict:
        with self.lock:
            return {
                "session_id": self.session_id,
                "spec": self.spec,
                "version": self.version,
                "history": [dict(h) for h in self.history],
            }


def _describe_patch(patch: Any) -> str:
    try:
        ops = [f"{op['op']} {op['path'] or '/'}" for op in patch]
    except (TypeError, KeyError):
        return "patch"
    return ", ".join(ops[:3]) + (f" (+{len(ops) - 3} more)" if len(ops) > 3 else "") or "patch"


def check_patch(spec: dict, patch: Any, bundle: Bundle) -> dict:
    """Apply `patch` to a copy of `spec` and validate the result; returns the new spec or raises PatchError."""
    if not isinstance(patch, list) or not patch:
        raise PatchError(["patch: must be a non-empty list of JSON Patch operations"])
    for i, op in enumerate(patch):
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise PatchError([f"patch[{i}]: each operation needs 'op' and 'path'"])
    try:
        new_spec = jsonpatch.apply_patch(copy.deepcopy(spec), patch)
    except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException, TypeError, ValueError) as exc:
        raise PatchError([f"patch: cannot apply: {exc}"]) from None
    if not isinstance(new_spec, dict):
        raise PatchError(["patch: the result must be a JSON object (a view spec)"])
    _, errors = validate_spec(new_spec, bundle)
    if errors:
        raise PatchError(errors)
    return new_spec


class SessionStore:
    """Thread-safe in-memory map session_id → Session (sessions are lost on restart; fine for the demo)."""

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions

    def create(self, bundle_id: str, spec: dict, get_bundle: Callable[[str], Bundle]) -> Session:
        sid = uuid.uuid4().hex
        s = Session(session_id=sid, bundle_id=bundle_id, get_bundle=get_bundle, _stack=[copy.deepcopy(spec)])
        s._record("initial view", "init")
        with self._lock:
            self._sessions[sid] = s
            while len(self._sessions) > self.max_sessions:
                self._sessions.pop(next(iter(self._sessions)))
        return s

    def get(self, sid: str) -> Session:
        with self._lock:
            try:
                return self._sessions[sid]
            except KeyError:
                raise SessionNotFound(sid) from None

    def __len__(self) -> int:
        return len(self._sessions)
