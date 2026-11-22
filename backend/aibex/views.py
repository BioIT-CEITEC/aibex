"""Saved views per bundle (T51, P5.2; docs/api.md → "Saved views").

A saved view is a plain view spec stored as `<bundle>/views/<name>.json` (docs/bundle-format.md), the same format as
the bundle's optional `default.json`. Names are kebab-case. Specs are validated against the bundle before they are
written, and again when a session loads them (the bundle may have changed since). Files are written atomically
(temp file + rename) so a crash never leaves half a view behind. The file the bundle uses as `default_view` cannot be
overwritten from the app (that would change what every new session shows).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from aibex.bundles import Bundle
from aibex.validate import validate_spec

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_TITLE = 200
MAX_VIEW_BYTES = 2_000_000  # a spec with a few widgets is ~50 kB; refuse anything absurd
VIEWS_DIR = "views"


class ViewError(ValueError):
    """Invalid name or spec (→ 422); `errors` are readable messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ViewNotFound(KeyError):
    pass


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > MAX_NAME:
        rule = f"kebab-case: lowercase letters, digits and single dashes, starting with a letter, max {MAX_NAME} chars"
        raise ViewError([f"name: {name!r} is not a valid view name ({rule})"])
    return name


def _views_dir(bundle: Bundle) -> Path:
    return bundle.path / VIEWS_DIR


def _default_file(bundle: Bundle) -> Path | None:
    rel = bundle.meta.get("default_view")
    return (bundle.path / str(rel)).resolve() if rel else None


def _path(bundle: Bundle, name: str) -> Path:
    return _views_dir(bundle) / f"{check_name(name)}.json"


def _read(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_VIEW_BYTES:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_views(bundle: Bundle) -> list[dict]:
    """`[{name, title}]` sorted by name; files with a non-kebab name or unreadable JSON are skipped."""
    d = _views_dir(bundle)
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.json")):
        name = path.stem
        if not NAME_RE.match(name) or len(name) > MAX_NAME:
            continue
        data = _read(path)
        if data is None:
            continue
        title = data.get("title")
        out.append({"name": name, "title": title if isinstance(title, str) and title else name})
    return out


def load_view(bundle: Bundle, name: str) -> dict:
    """The stored spec (not yet validated – the session validates it when it applies it). ViewNotFound if missing."""
    path = _path(bundle, name)
    if not path.is_file():
        raise ViewNotFound(name)
    data = _read(path)
    if data is None:
        raise ViewError([f"view {name!r}: the stored file is not a readable JSON object"])
    data["bundle"] = bundle.id  # a copied bundle keeps working
    return data


def save_view(bundle: Bundle, name: str, spec: Any, title: str | None = None) -> str:
    """Validate and store `spec` as view `name` (overwrites a view of that name). Raises ViewError."""
    path = _path(bundle, name)
    if not isinstance(spec, dict):
        raise ViewError(["spec: must be a JSON object (a view spec)"])
    spec = dict(spec)
    if spec.get("bundle", bundle.id) != bundle.id:
        raise ViewError([f"spec.bundle: {spec.get('bundle')!r} does not match bundle {bundle.id!r}"])
    spec["bundle"] = bundle.id
    if title is not None:
        title = title.strip()
        if not title or len(title) > MAX_TITLE:
            raise ViewError([f"title: must be 1–{MAX_TITLE} characters"])
        spec["title"] = title
    if path.resolve() == _default_file(bundle):
        raise ViewError([f"name: {name!r} is the bundle's default view and cannot be overwritten from the app"])
    _, errors = validate_spec(spec, bundle)
    if errors:
        raise ViewError(errors)
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if len(text.encode()) > MAX_VIEW_BYTES:
        raise ViewError([f"spec: too large to save (over {MAX_VIEW_BYTES // 1_000_000} MB)"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return name
