"""Phase 4 – Level 2 widgets created by the LLM. Criteria A4.* in docs/acceptance.md."""

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
