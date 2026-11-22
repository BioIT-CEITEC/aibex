"""Phase 4 – Level 2 widgets created by the LLM. Criteria A4.* in docs/acceptance.md."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.phase4

WIDGET_CODE = """
export default function Widget({ data }) {
  const rows = data?.inputs?.sites?.rows ?? [];
  return <div>Sites: {rows.length}</div>;
}
"""


def _create(client, session, provider, h, code=WIDGET_CODE, inputs=None):
    inputs = inputs or [{"name": "sites", "sql": "SELECT site_id, delta FROM editing ORDER BY delta LIMIT 50"}]
    provider.queue(
        h.tool_call("create_widget", {"id": "site-count", "title": "Site count", "inputs": inputs, "code": code}),
        h.text("Added a widget."),
    )
    r = client.post(f"/api/sessions/{session['session_id']}/chat?stream=false", json={"message": "add widget"})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_widget_adds_panel_and_layout(client, session, provider, h):
    out = _create(client, session, provider, h)
    spec = out["spec"]
    w = next(p for p in spec["panels"] if p["id"] == "site-count")
    assert w["type"] == "widget" and "export default" in w["code"]
    assert any(item["i"] == "site-count" for item in spec["layout"])
    assert out["version"] == 1


def test_widget_inputs_resolved_server_side(client, session, provider, h):
    _create(client, session, provider, h)
    r = client.post(f"/api/sessions/{session['session_id']}/panel-data", json={"panel_id": "site-count"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["inputs"]["sites"]["rows"]) == 50


def test_widget_selected_param(client, session, provider, h):
    inputs = [{"name": "sites", "sql": "SELECT site_id FROM editing WHERE gene_id = $selected"}]
    _create(client, session, provider, h, inputs=inputs)
    gene = client.post("/api/bundles/toy/query", json={"sql": "SELECT gene_id FROM editing LIMIT 1"}).json()["rows"][0][0]
    r = client.post(f"/api/sessions/{session['session_id']}/panel-data",
                    json={"panel_id": "site-count", "selection": [gene]})
    assert r.status_code == 200
    assert len(r.json()["inputs"]["sites"]["rows"]) >= 1


@pytest.mark.parametrize("bad", ["fetch('https://x')", "new XMLHttpRequest()", "new WebSocket('ws://x')",
                                 "localStorage.setItem('a','b')", "document.cookie",
                                 "importScripts('x.js')"])
def test_widget_code_blocklist(client, session, provider, h, bad):
    code = WIDGET_CODE.replace("return", f"{bad};\n  return")
    out = _create(client, session, provider, h, code=code)
    assert all(p["id"] != "site-count" for p in out["spec"]["panels"])


def test_widget_code_size_limit(client, session, provider, h):
    out = _create(client, session, provider, h, code=WIDGET_CODE + "//" + "x" * 60_000)
    assert all(p["id"] != "site-count" for p in out["spec"]["panels"])


def test_widget_input_sql_is_readonly(client, session, provider, h):
    out = _create(client, session, provider, h, inputs=[{"name": "sites", "sql": "DROP TABLE editing"}])
    assert all(p["id"] != "site-count" for p in out["spec"]["panels"])


def test_widget_undo(client, session, provider, h):
    _create(client, session, provider, h)
    r = client.post(f"/api/sessions/{session['session_id']}/undo", json={"steps": 1}).json()
    assert all(p["id"] != "site-count" for p in r["spec"]["panels"])


# M4 helper (T42, optional): demo prompt 5 on the real ADAR2 bundle with the real chat + code model.
# The visual check (does the widget render?) is manual / e2e; this test checks the backend part.
@pytest.mark.live
def test_live_widget_editing_sites_adar2():
    import os
    import time

    from fastapi.testclient import TestClient

    from aibex.config import Settings
    from aibex.main import create_app

    d = Path(os.getenv("AIBEX_DATA_DIR") or Settings().data_dir)
    if not (d / "adar2-editing" / "bundle.yaml").exists():
        pytest.skip("ADAR2 bundle not present")
    c = TestClient(create_app(Settings(data_dir=d, llm_provider="openai")))
    sess = c.post("/api/sessions", json={"bundle": "adar2-editing"}).json()
    sid = sess["session_id"]
    n_before = len(sess["spec"]["panels"])
    t0 = time.monotonic()
    r = c.post(f"/api/sessions/{sid}/chat?stream=false",
               json={"message": "For the selected gene, show its editing sites along the transcript."})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    steps = [(e.get("type"), e.get("name") or e.get("summary") or e.get("message") or "", e.get("status", ""))
             for e in body.get("events", []) if e.get("type") != "token"]
    widgets = [p for p in body["spec"]["panels"] if p.get("type") == "widget"]
    print(f"\n[live] models fast={os.getenv('LLM_MODEL_FAST')} code={os.getenv('LLM_MODEL_CODE')} "
          f"latency={elapsed:.1f}s version={body.get('version')}\n[live] events={steps}"
          f"\n[live] reply={(body.get('reply') or '')[:300]!r}")
    for w in widgets:
        print(f"[live] widget {w['id']} inputs={w.get('inputs')}\n{w.get('code')}")
    assert len(body["spec"]["panels"]) == n_before + 1 and len(widgets) == 1, f"events={steps}"
    w = widgets[0]
    assert "export default" in w["code"]
    assert any("$selected" in i["sql"] for i in w["inputs"]), w["inputs"]
    gene = c.post("/api/bundles/adar2-editing/query",
                  json={"sql": "SELECT gene_id FROM editing GROUP BY gene_id ORDER BY count(*) DESC LIMIT 1"}
                  ).json()["rows"][0][0]
    r = c.post(f"/api/sessions/{sid}/panel-data", json={"panel_id": w["id"], "selection": [gene]})
    assert r.status_code == 200, r.text
    assert any(len(v["rows"]) > 1 for v in r.json()["inputs"].values()), f"no sites for {gene}"
