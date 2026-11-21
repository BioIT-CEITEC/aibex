from fastapi.testclient import TestClient

from aibex.main import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_bundles_empty_ok():
    r = TestClient(app).get("/api/bundles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
