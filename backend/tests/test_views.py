"""Unit tests for saved views per bundle (T51, P5.2): save/list/load endpoints and the views module."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.main import create_app
from aibex.views import ViewError, ViewNotFound, list_views, load_view, save_view

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def data_dir(tmp_path) -> Path:
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_toy_bundle(tmp_path, "toy")
    return tmp_path


@pytest.fixture()
def client(data_dir):
    return TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))


@pytest.fixture()
def session(client) -> dict:
    return client.post("/api/sessions", json={"bundle": "toy"}).json()


def _retitled(spec: dict, title: str) -> dict:
    return {**spec, "panels": [{**spec["panels"][0], "title": title}, *spec["panels"][1:]]}


# --- endpoints ------------------------------------------------------------------------------------------------
def test_views_empty_list_for_a_new_bundle(client):
    r = client.get("/api/bundles/toy/views")
    assert r.status_code == 200 and r.json() == []


def test_save_then_list_then_load_as_new_undoable_version(client, session, data_dir):
    spec = _retitled(session["spec"], "Saved volcano")
    r = client.post("/api/bundles/toy/views", json={"name": "my-view", "spec": spec, "title": "My view"})
    assert r.status_code == 200 and r.json() == {"name": "my-view"}
    assert (data_dir / "toy" / "views" / "my-view.json").is_file()
    assert client.get("/api/bundles/toy/views").json() == [{"name": "my-view", "title": "My view"}]

    sid = session["session_id"]
    r = client.post(f"/api/sessions/{sid}/load-view", json={"name": "my-view"})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["spec"]["panels"][0]["title"] == "Saved volcano"
    assert body["spec"]["title"] == "My view"

    state = client.get(f"/api/sessions/{sid}").json()
    assert state["history"][-1] == {"version": 1, "summary": "load view my-view", "source": "user"}
    assert state["can_undo"] == 1
    undone = client.post(f"/api/sessions/{sid}/undo").json()
    assert undone["spec"] == session["spec"]


def test_save_overwrites_a_view_of_the_same_name(client, session):
    spec = session["spec"]
    client.post("/api/bundles/toy/views", json={"name": "v", "spec": _retitled(spec, "one")})
    client.post("/api/bundles/toy/views", json={"name": "v", "spec": _retitled(spec, "two")})
    sid = session["session_id"]
    loaded = client.post(f"/api/sessions/{sid}/load-view", json={"name": "v"}).json()
    assert loaded["spec"]["panels"][0]["title"] == "two"
    assert len(client.get("/api/bundles/toy/views").json()) == 1


def test_list_title_defaults_to_the_spec_title(client, session):
    client.post("/api/bundles/toy/views", json={"name": "plain", "spec": session["spec"]})
    [entry] = client.get("/api/bundles/toy/views").json()
    assert entry == {"name": "plain", "title": session["spec"]["title"]}


@pytest.mark.parametrize("name", ["My View", "my_view", "-x", "x-", "a--b", "1abc", "", "../evil", "a" * 65, 5])
def test_save_rejects_non_kebab_names(client, session, data_dir, name):
    r = client.post("/api/bundles/toy/views", json={"name": name, "spec": session["spec"]})
    assert r.status_code == 422
    assert "kebab-case" in r.json()["detail"]["errors"][0]
    assert not (data_dir / "toy" / "views").exists()


def test_save_rejects_an_invalid_spec_with_readable_errors(client, session, data_dir):
    bad = {**session["spec"], "panels": [{**session["spec"]["panels"][0], "table": "nope"}, *session["spec"]["panels"][1:]]}
    r = client.post("/api/bundles/toy/views", json={"name": "bad", "spec": bad})
    assert r.status_code == 422
    assert any("nope" in e for e in r.json()["detail"]["errors"])
    assert client.get("/api/bundles/toy/views").json() == []


def test_save_rejects_a_spec_of_another_bundle(client, session):
    r = client.post("/api/bundles/toy/views", json={"name": "other", "spec": {**session["spec"], "bundle": "other"}})
    assert r.status_code == 422
    assert "does not match" in r.json()["detail"]["errors"][0]


def test_save_and_list_unknown_bundle_404(client, session):
    assert client.get("/api/bundles/nope/views").status_code == 404
    assert client.post("/api/bundles/nope/views", json={"name": "x", "spec": session["spec"]}).status_code == 404


def test_load_view_unknown_view_404_and_unknown_session_404(client, session):
    sid = session["session_id"]
    r = client.post(f"/api/sessions/{sid}/load-view", json={"name": "missing"})
    assert r.status_code == 404
    assert client.get(f"/api/sessions/{sid}").json()["version"] == 0
    assert client.post("/api/sessions/nope/load-view", json={"name": "x"}).status_code == 404


def test_load_view_with_an_invalid_name_is_422(client, session):
    r = client.post(f"/api/sessions/{session['session_id']}/load-view", json={"name": "../bundle"})
    assert r.status_code == 422


def test_load_view_whose_spec_no_longer_validates_is_422_and_changes_nothing(client, session, data_dir):
    views = data_dir / "toy" / "views"
    views.mkdir()
    stale = {**session["spec"], "panels": [{**session["spec"]["panels"][0], "table": "gone"}, *session["spec"]["panels"][1:]]}
    (views / "stale.json").write_text(json.dumps(stale))
    sid = session["session_id"]
    r = client.post(f"/api/sessions/{sid}/load-view", json={"name": "stale"})
    assert r.status_code == 422
    assert any("gone" in e for e in r.json()["detail"]["errors"])
    assert client.get(f"/api/sessions/{sid}").json()["version"] == 0


# --- module -----------------------------------------------------------------------------------------------------
def test_list_skips_unreadable_and_badly_named_files(data_dir, session):
    bundle = load_bundle(data_dir / "toy" / "bundle.yaml")
    save_view(bundle, "good", session["spec"])
    views = data_dir / "toy" / "views"
    (views / "broken.json").write_text("{not json")
    (views / "Bad_Name.json").write_text(json.dumps(session["spec"]))
    (views / "list.json").write_text("[1, 2]")
    assert [v["name"] for v in list_views(bundle)] == ["good"]
    with pytest.raises(ViewError):
        load_view(bundle, "broken")
    with pytest.raises(ViewNotFound):
        load_view(bundle, "missing")


def test_save_leaves_no_temp_files(data_dir, session):
    bundle = load_bundle(data_dir / "toy" / "bundle.yaml")
    save_view(bundle, "a", session["spec"])
    save_view(bundle, "a", session["spec"])
    assert sorted(p.name for p in (data_dir / "toy" / "views").iterdir()) == ["a.json"]


def test_the_bundles_default_view_file_cannot_be_overwritten(data_dir, session):
    manifest = data_dir / "toy" / "bundle.yaml"
    manifest.write_text(manifest.read_text() + "\ndefault_view: views/default.json\n")
    bundle = load_bundle(manifest)
    with pytest.raises(ViewError, match="default view"):
        save_view(bundle, "default", session["spec"])


def test_save_rejects_an_empty_title(data_dir, session):
    bundle = load_bundle(data_dir / "toy" / "bundle.yaml")
    with pytest.raises(ViewError, match="title"):
        save_view(bundle, "t", session["spec"], title="   ")
