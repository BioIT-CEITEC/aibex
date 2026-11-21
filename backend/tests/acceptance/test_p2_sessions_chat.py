"""Phase 2 – sessions, patches, undo/redo, chat loop with tools, privacy. Criteria A2.* in docs/acceptance.md."""

import json
import os

import pytest

pytestmark = pytest.mark.phase2


def _chat(client, sid, message):
    r = client.post(f"/api/sessions/{sid}/chat?stream=false", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


# A2.1 sessions + patch + history
def test_session_starts_at_version_0(client, session):
    assert session["version"] == 0
    s = client.get(f"/api/sessions/{session['session_id']}").json()
    assert s["history"][0]["source"] == "init"


def test_valid_patch_increments_version(client, session, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    r = client.post(f"/api/sessions/{sid}/patch", json={
        "patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "New title"}], "summary": "rename"})
    assert r.status_code == 200
    assert r.json()["version"] == 1
    assert r.json()["spec"]["panels"][i]["title"] == "New title"


def test_invalid_patch_422_and_unchanged(client, session, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    r = client.post(f"/api/sessions/{sid}/patch", json={
        "patch": [{"op": "replace", "path": f"/panels/{i}/table", "value": "nope"}]})
    assert r.status_code == 422
    assert client.get(f"/api/sessions/{sid}").json()["version"] == 0


def test_undo_redo(client, session, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    client.post(f"/api/sessions/{sid}/patch", json={"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "A"}]})
    client.post(f"/api/sessions/{sid}/patch", json={"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "B"}]})
    r = client.post(f"/api/sessions/{sid}/undo", json={"steps": 2}).json()
    assert r["spec"]["panels"][i]["title"] == spec["panels"][i]["title"]
    r = client.post(f"/api/sessions/{sid}/redo", json={"steps": 1}).json()
    assert r["spec"]["panels"][i]["title"] == "A"
    assert r["version"] == 4  # every applied change, including undo/redo, increments


# A2.2 chat applies tool calls
def test_chat_update_view_applies(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    provider.queue(
        h.tool_call("update_view", {"patch": [{"op": "replace", "path": f"/panels/{i}/label/values",
                                               "value": ["Gene_001", "Gene_002"]}], "summary": "label two genes"}),
        h.text("Done – labelled Gene_001 and Gene_002."),
    )
    out = _chat(client, sid, "Label Gene_001 and Gene_002")
    assert out["spec"]["panels"][i]["label"]["values"] == ["Gene_001", "Gene_002"]
    assert out["version"] == 1
    assert "Gene_001" in out["reply"]
    hist = client.get(f"/api/sessions/{sid}").json()["history"]
    assert hist[-1]["source"] == "llm" and hist[-1]["summary"]
    assert any(e["type"] == "spec" for e in out["events"])


def test_chat_repairs_after_invalid_patch(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    provider.queue(
        h.tool_call("update_view", {"patch": [{"op": "replace", "path": f"/panels/{i}/x/field", "value": "nope"}],
                                    "summary": "bad"}, "c1"),
        h.tool_call("update_view", {"patch": [{"op": "replace", "path": f"/panels/{i}/x/field", "value": "baseMean"}],
                                    "summary": "x = baseMean"}, "c2"),
        h.text("Changed the x axis to baseMean."),
    )
    out = _chat(client, sid, "use baseMean on x")
    assert out["spec"]["panels"][i]["x"]["field"] == "baseMean"
    # the validation error was sent back to the model as a tool result
    second_call_msgs = provider.calls[1]["messages"]
    assert any(m.get("role") == "tool" and "nope" in str(m.get("content")) for m in second_call_msgs)


def test_chat_gives_up_after_two_failures(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    bad = {"patch": [{"op": "replace", "path": f"/panels/{i}/table", "value": "nope"}], "summary": "bad"}
    provider.queue(h.tool_call("update_view", bad, "c1"), h.tool_call("update_view", bad, "c2"),
                   h.tool_call("update_view", bad, "c3"))
    out = _chat(client, sid, "break it")
    assert out["version"] == 0
    assert any(e["type"] == "error" for e in out["events"])


def test_chat_text_json_fallback(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    payload = {"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "From text"}], "summary": "t"}
    provider.queue(h.text("Here is the change:\n```json\n" + json.dumps(payload) + "\n```"), h.text("ok"))
    out = _chat(client, sid, "rename the volcano")
    assert out["spec"]["panels"][i]["title"] == "From text"


def test_chat_undo_tool(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    client.post(f"/api/sessions/{sid}/patch", json={"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "X"}]})
    provider.queue(h.tool_call("undo_view", {"steps": 1}), h.text("Undone."))
    out = _chat(client, sid, "undo")
    assert out["spec"]["panels"][i]["title"] == spec["panels"][i]["title"]


def test_chat_no_tool_call_changes_nothing(client, session, provider, h):
    provider.queue(h.text("I am not sure what you mean."))
    out = _chat(client, session["session_id"], "hmm")
    assert out["version"] == 0
    assert out["reply"]


# A2.3 privacy: the model never gets whole tables
def test_query_tool_results_capped_at_200_rows(client, session, provider, h):
    provider.queue(h.tool_call("query_data", {"sql": "SELECT * FROM editing"}), h.text("Looked at the sites."))
    _chat(client, session["session_id"], "look at all editing sites")
    tool_msgs = [m for m in provider.calls[-1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs
    content = json.loads(tool_msgs[-1]["content"])
    rows = content.get("rows", [])
    assert len(rows) <= 200


def test_context_does_not_contain_whole_tables(client, session, provider, h):
    provider.queue(h.tool_call("describe_bundle", {}), h.text("ok"))
    _chat(client, session["session_id"], "what data do we have?")
    sent = json.dumps(provider.calls[-1]["messages"])
    # site ids are unique per row; with 300 sites, a full dump would contain all of them
    n_sites = sum(1 for k in range(1, 301) if f"site_{k:04d}" in sent)
    assert n_sites <= 200
    assert "row_count" in sent or "rows" in sent


# A2.4 SSE stream
def test_chat_stream_emits_events(client, session, provider, h):
    sid, spec = session["session_id"], session["spec"]
    i = h.first_scatter(spec)
    provider.queue(h.tool_call("update_view", {"patch": [{"op": "replace", "path": f"/panels/{i}/title", "value": "S"}],
                                               "summary": "s"}), h.text("done"))
    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"message": "rename"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: spec" in body and "event: done" in body


# A2.5 live LLM (optional, real e-INFRA model)
@pytest.mark.live
def test_live_label_genes(data_dir):
    from fastapi.testclient import TestClient

    from aibex.config import Settings
    from aibex.main import create_app

    s = Settings(data_dir=data_dir, llm_provider="openai")
    c = TestClient(create_app(s))
    sess = c.post("/api/sessions", json={"bundle": "toy"}).json()
    r = c.post(f"/api/sessions/{sess['session_id']}/chat?stream=false",
               json={"message": "Label the genes Gene_001 and Gene_002 in the volcano plot."})
    assert r.status_code == 200, r.text
    spec = r.json()["spec"]
    labels = [v for p in spec["panels"] if p.get("label") for v in p["label"].get("values", [])]
    assert {"Gene_001", "Gene_002"} <= set(labels), f"model={os.getenv('LLM_MODEL_FAST')}"
