"""Unit tests for sessions + spec store (T15): patch validation, undo/redo stack, history, REST endpoints."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.default_view import default_view
from aibex.main import create_app
from aibex.sessions import NothingToUndo, PatchError, SessionNotFound, SessionStore, check_patch

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(d, "toy")
    return d


@pytest.fixture(scope="module")
def bundle(data_dir):
    return load_bundle(data_dir / "toy" / "bundle.yaml")


@pytest.fixture()
def store():
    return SessionStore()


@pytest.fixture()
def sess(store, bundle):
    return store.create("toy", default_view(bundle), lambda _id: bundle)


def _title(i: int, value: str) -> list[dict]:
    return [{"op": "replace", "path": f"/panels/{i}/title", "value": value}]


# --- store / Session -------------------------------------------------------------------------------------------
def test_create_starts_at_version_0_with_init_history(sess):
    assert sess.version == 0
    assert sess.history == [{"version": 0, "summary": "initial view", "source": "init"}]
    assert sess.can_undo == 0 and sess.can_redo == 0


def test_spec_is_a_copy(sess):
    s = sess.spec
    s["panels"][0]["title"] = "mutated"
    assert sess.spec["panels"][0]["title"] != "mutated"


def test_apply_patch_increments_version_and_records_source(sess):
    spec = sess.apply_patch(_title(0, "T"), "rename", source="llm")
    assert spec["panels"][0]["title"] == "T"
    assert sess.version == 1
    assert sess.history[-1] == {"version": 1, "summary": "rename", "source": "llm"}


def test_default_summary_describes_patch(sess):
    sess.apply_patch(_title(0, "T"))
    assert sess.history[-1]["summary"] == "replace /panels/0/title"
    assert sess.history[-1]["source"] == "user"


@pytest.mark.parametrize("patch", [
    [],
    "not a list",
    [{"path": "/title"}],
    [{"op": "replace", "path": "/panels/99/title", "value": "x"}],
    [{"op": "test", "path": "/bundle", "value": "other"}],
    [{"op": "replace", "path": "/panels/0/table", "value": "nope"}],
    [{"op": "replace", "path": "", "value": []}],
    [{"op": "remove", "path": "/panels/0"}],  # layout item left without a panel
])
def test_invalid_patch_raises_and_changes_nothing(sess, patch):
    before = sess.spec
    with pytest.raises(PatchError) as exc:
        sess.apply_patch(patch)
    assert exc.value.errors
    assert sess.version == 0 and sess.spec == before and len(sess.history) == 1


def test_semantic_errors_are_returned_for_repair(sess):
    with pytest.raises(PatchError) as exc:
        sess.apply_patch([{"op": "replace", "path": "/panels/0/x/field", "value": "nope"}])
    assert any("nope" in e for e in exc.value.errors)


def test_check_patch_does_not_mutate_input(sess, bundle):
    spec = sess.spec
    out = check_patch(spec, _title(0, "Z"), bundle)
    assert out["panels"][0]["title"] == "Z" and spec["panels"][0]["title"] != "Z"


def test_undo_redo_move_pointer_and_add_versions(sess):
    orig = sess.spec["panels"][0]["title"]
    sess.apply_patch(_title(0, "A"))
    sess.apply_patch(_title(0, "B"))
    assert sess.undo(2)["panels"][0]["title"] == orig
    assert sess.version == 3
    assert sess.redo(1)["panels"][0]["title"] == "A"
    assert sess.version == 4
    assert [h["summary"] for h in sess.history[-2:]] == ["undo 2", "redo"]
    assert sess.can_undo == 1 and sess.can_redo == 1


def test_undo_steps_are_clamped(sess):
    sess.apply_patch(_title(0, "A"))
    sess.undo(5)
    assert sess.can_undo == 0 and sess.version == 2
    assert sess.history[-1]["summary"] == "undo"


def test_nothing_to_undo_or_redo(sess):
    with pytest.raises(NothingToUndo):
        sess.undo()
    with pytest.raises(NothingToUndo):
        sess.redo()
    assert sess.version == 0 and len(sess.history) == 1


def test_new_change_after_undo_drops_redo(sess):
    sess.apply_patch(_title(0, "A"))
    sess.apply_patch(_title(0, "B"))
    sess.undo(1)
    sess.apply_patch(_title(0, "C"))
    assert sess.can_redo == 0
    with pytest.raises(NothingToUndo):
        sess.redo()
    assert sess.undo(1)["panels"][0]["title"] == "A"


def test_replace_spec_is_undoable(sess):
    orig = sess.spec
    new = sess.spec
    new["title"] = "Loaded view"
    sess.replace_spec(new, "load view x")
    assert sess.spec["title"] == "Loaded view"
    assert sess.undo() == orig


def test_store_get_unknown(store):
    with pytest.raises(SessionNotFound):
        store.get("nope")


def test_store_drops_oldest_beyond_limit(bundle):
    store = SessionStore(max_sessions=2)
    spec = default_view(bundle)
    a = store.create("toy", spec, lambda _id: bundle)
    store.create("toy", spec, lambda _id: bundle)
    store.create("toy", spec, lambda _id: bundle)
    assert len(store) == 2
    with pytest.raises(SessionNotFound):
        store.get(a.session_id)


# --- REST ------------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


@pytest.fixture()
def sid(client):
    r = client.post("/api/sessions", json={"bundle": "toy"})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 0 and body["spec"]["bundle"] == "toy"
    return body["session_id"]


def test_create_session_unknown_bundle_404(client):
    assert client.post("/api/sessions", json={"bundle": "nope"}).status_code == 404


@pytest.mark.parametrize("method,path", [
    ("get", ""), ("post", "/patch"), ("post", "/undo"), ("post", "/redo"),
])
def test_unknown_session_404(client, method, path):
    kwargs = {"json": {"patch": _title(0, "x")}} if path == "/patch" else ({"json": {}} if method == "post" else {})
    assert getattr(client, method)(f"/api/sessions/nope{path}", **kwargs).status_code == 404


def test_get_session_state(client, sid):
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["session_id"] == sid and s["version"] == 0
    assert s["history"] == [{"version": 0, "summary": "initial view", "source": "init"}]


def test_patch_endpoint_and_history(client, sid):
    r = client.post(f"/api/sessions/{sid}/patch", json={"patch": _title(0, "N"), "summary": "rename"})
    assert r.status_code == 200 and r.json()["version"] == 1
    hist = client.get(f"/api/sessions/{sid}").json()["history"]
    assert hist[-1] == {"version": 1, "summary": "rename", "source": "user"}


def test_patch_endpoint_422_shape(client, sid):
    r = client.post(f"/api/sessions/{sid}/patch",
                    json={"patch": [{"op": "replace", "path": "/panels/0/table", "value": "nope"}]})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"]
    assert client.get(f"/api/sessions/{sid}").json()["version"] == 0


def test_undo_redo_endpoints(client, sid):
    assert client.post(f"/api/sessions/{sid}/undo").status_code == 409  # no body → steps 1
    client.post(f"/api/sessions/{sid}/patch", json={"patch": _title(0, "N")})
    r = client.post(f"/api/sessions/{sid}/undo", json={})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = client.post(f"/api/sessions/{sid}/redo")
    assert r.status_code == 200 and r.json()["spec"]["panels"][0]["title"] == "N"
    assert client.post(f"/api/sessions/{sid}/redo", json={"steps": 1}).status_code == 409


def test_session_state_undo_redo_counts(client, sid):
    s = client.get(f"/api/sessions/{sid}").json()
    assert (s["can_undo"], s["can_redo"]) == (0, 0)
    client.post(f"/api/sessions/{sid}/patch", json={"patch": _title(0, "A")})
    client.post(f"/api/sessions/{sid}/patch", json={"patch": _title(0, "B")})
    client.post(f"/api/sessions/{sid}/undo")
    s = client.get(f"/api/sessions/{sid}").json()
    assert (s["can_undo"], s["can_redo"]) == (1, 1)
    client.post(f"/api/sessions/{sid}/patch", json={"patch": _title(0, "C")})  # drops the redo part
    s = client.get(f"/api/sessions/{sid}").json()
    assert (s["can_undo"], s["can_redo"]) == (2, 0)


def test_steps_must_be_positive(client, sid):
    assert client.post(f"/api/sessions/{sid}/undo", json={"steps": 0}).status_code == 422
