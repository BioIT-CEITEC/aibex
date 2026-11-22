from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibex.config import Settings
from aibex.main import create_app


def test_create_app_uses_given_settings(tmp_path):
    s = Settings(data_dir=tmp_path, llm_provider="fake")
    app = create_app(s)
    assert app.state.settings is s
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_provider"] == "fake"
    assert body["data_dir_exists"] is True


def test_create_app_missing_data_dir(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "nope", llm_provider="fake"))
    c = TestClient(app)
    assert c.get("/api/health").json()["data_dir_exists"] is False
    assert c.get("/api/bundles").json() == []


def test_injected_provider_is_kept(tmp_path):
    sentinel = object()
    app = create_app(Settings(data_dir=tmp_path, llm_provider="openai"), llm_provider=sentinel)
    assert app.state.llm_provider is sentinel


def test_settings_reads_env_at_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "FAKE")
    monkeypatch.setenv("AIBEX_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.llm_provider == "fake"
    assert s.data_dir == tmp_path


def test_settings_default_provider_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert Settings().llm_provider == "openai"


def test_settings_rejects_unknown_provider():
    with pytest.raises(ValueError):
        Settings(llm_provider="claude")


def test_settings_coerces_str_paths(tmp_path):
    s = Settings(data_dir=str(tmp_path), llm_provider="fake")
    assert isinstance(s.data_dir, Path)


def test_placeholder_root_without_frontend(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, frontend_dist=tmp_path / "missing", llm_provider="fake"))
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "Aibex View" in r.text


@pytest.fixture()
def built_frontend(tmp_path):
    """A minimal stand-in for `frontend/dist` (index.html + one large hashed asset)."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><title>Aibex View</title><script type="module" src="/assets/index-abc.js"></script>'
    )
    (dist / "assets" / "index-abc.js").write_text("console.log('aibex');\n" * 2000)
    return dist


def test_serves_built_frontend_at_root(tmp_path, built_frontend):
    app = create_app(Settings(data_dir=tmp_path, frontend_dist=built_frontend, llm_provider="fake"))
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and '<script type="module" src="/assets/index-abc.js">' in r.text
    assert "has not been built" not in r.text
    assert c.get("/?bundle=toy").status_code == 200  # the app keeps the bundle in the query string
    assert c.get("/assets/index-abc.js").status_code == 200
    assert c.get("/api/health").json()["status"] == "ok"  # the static mount does not shadow /api
    assert c.get("/api/nope").status_code == 404


def test_large_responses_are_gzipped(tmp_path, built_frontend):
    c = TestClient(create_app(Settings(data_dir=tmp_path, frontend_dist=built_frontend, llm_provider="fake")))
    r = c.get("/assets/index-abc.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert r.text.startswith("console.log")  # httpx decodes transparently
    r = c.get("/assets/index-abc.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers
