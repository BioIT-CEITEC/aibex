"""Phase 3 – real ADAR2 bundle (RNA-seq DE + RNA editing). Criteria A3.* in docs/acceptance.md.

Runs only where the bundle exists: $AIBEX_DATA_DIR/adar2-editing/bundle.yaml (never in CI / GitHub).
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.phase3


def _real_data_dir() -> Path | None:
    from aibex.config import Settings

    d = Path(os.getenv("AIBEX_DATA_DIR") or Settings().data_dir)
    return d if (d / "adar2-editing" / "bundle.yaml").exists() else None


@pytest.fixture(scope="module")
def real_client():
    d = _real_data_dir()
    if d is None:
        pytest.skip("ADAR2 bundle not present")
    from fastapi.testclient import TestClient

    from aibex.config import Settings
    from aibex.main import create_app

    return TestClient(create_app(Settings(data_dir=d, llm_provider="fake")))


def test_bundle_manifest_complete():
    d = _real_data_dir()
    if d is None:
        pytest.skip("ADAR2 bundle not present")
    m = yaml.safe_load((d / "adar2-editing" / "bundle.yaml").read_text())
    assert m["id"] == "adar2-editing"
    assert {"rna-seq", "rna-editing"} <= set(m["modalities"])
    assert m.get("organism")
    assert m.get("links"), "editing sites must link to genes"
    for name, t in m["tables"].items():
        assert t.get("key"), f"table {name} needs a key"
        assert t.get("description"), f"table {name} needs a description"


def test_schema_and_link_join(real_client):
    s = real_client.get("/api/bundles/adar2-editing/schema").json()
    link = s["links"][0]
    lt, lc = link["from"].split(".")
    rt, rc = link["to"].split(".")
    sql = f"SELECT count(*) AS n FROM {lt} a JOIN {rt} b ON a.{lc} = b.{rc}"
    r = real_client.post("/api/bundles/adar2-editing/query", json={"sql": sql})
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] > 0, "the link must actually join rows"


def test_default_view_combines_modalities(real_client):
    spec = real_client.get("/api/bundles/adar2-editing/default-view").json()
    tables = {p.get("table") for p in spec["panels"]}
    assert len(tables - {None}) >= 2, "default view should show both expression and editing"
    assert real_client.post("/api/validate-spec", json=spec).json()["valid"] is True
    # T32: both modalities as panels (not just de + counts of the generic view), linked by the gene key, and every
    # editing plot carries that key so its points take part in the linked selection
    editing = {"editing"}
    assert {"de", *editing} <= tables, f"expected expression and editing panels, got {sorted(tables - {None})}"
    key = spec["selection"]["key"]
    assert spec["selection"]["linked"] is True
    sid = real_client.post("/api/sessions", json={"bundle": "adar2-editing"}).json()["session_id"]
    for p in spec["panels"]:
        r = real_client.post(f"/api/sessions/{sid}/panel-data", json={"panel_id": p["id"]})
        assert r.status_code == 200, (p["id"], r.text)
        d = r.json()
        assert d["rows"], f"panel {p['id']} has no data"
        if p.get("table") in editing and p["type"] == "plot":
            assert key in d["columns"] and not d["truncated"], (p["id"], d["columns"])


def test_raw_data_not_in_repo():
    # every file git could commit (tracked + untracked-but-not-ignored); gitignored data/ is allowed locally
    repo = Path(__file__).resolve().parents[3]
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=repo,
                           capture_output=True, text=True, check=True).stdout.splitlines()
    data_suffixes = {".parquet", ".tsv", ".csv", ".xlsx", ".txt", ".gz", ".bed", ".vcf"}
    offenders = [f for f in files if "adar2" in f.lower() and Path(f).suffix in data_suffixes]
    offenders += [f for f in files if f.startswith("data/") and f != "data/.gitkeep"]
    assert not offenders, f"ADAR2/real data files could be committed: {offenders}"
