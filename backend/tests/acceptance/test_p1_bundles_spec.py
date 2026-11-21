"""Phase 1 – bundles, read-only queries, spec validation, panel data. Criteria A1.* in docs/acceptance.md."""

import pytest

pytestmark = pytest.mark.phase1


# A1.1 bundle discovery
def test_bundles_list_contains_toy(client):
    r = client.get("/api/bundles")
    assert r.status_code == 200
    toy = next(b for b in r.json() if b["id"] == "toy")
    assert set(toy["tables"]) == {"de", "counts", "editing"}
    assert "rna-editing" in toy["modalities"]


# A1.2 schema
def test_schema_tables_columns_rowcounts_links(client):
    r = client.get("/api/bundles/toy/schema")
    assert r.status_code == 200
    s = r.json()
    assert s["tables"]["de"]["row_count"] == 200
    assert s["tables"]["editing"]["row_count"] == 300
    assert s["tables"]["de"]["key"] == "gene_id"
    assert {"gene_name", "log2FoldChange", "padj"} <= set(s["tables"]["de"]["columns"])
    # columns not declared in bundle.yaml (sample columns of counts) are exposed with inferred types
    assert "KO_1" in s["tables"]["counts"]["columns"]
    assert {"from": "editing.gene_id", "to": "de.gene_id"} in s["links"]


def test_schema_unknown_bundle_404(client):
    assert client.get("/api/bundles/nope/schema").status_code == 404


# A1.3 read-only query
def test_query_select_and_join(client):
    sql = (
        "SELECT d.gene_name, count(*) AS n_sites FROM editing e JOIN de d ON e.gene_id = d.gene_id "
        "GROUP BY d.gene_name ORDER BY n_sites DESC"
    )
    r = client.post("/api/bundles/toy/query", json={"sql": sql})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["gene_name", "n_sites"]
    assert 0 < len(body["rows"]) <= 200


def test_query_default_cap_200_and_truncated(client):
    r = client.post("/api/bundles/toy/query", json={"sql": "SELECT * FROM editing"})
    body = r.json()
    assert len(body["rows"]) == 200
    assert body["truncated"] is True
    assert body["row_count"] >= 200


def test_query_limit_max_5000(client):
    r = client.post("/api/bundles/toy/query", json={"sql": "SELECT * FROM editing", "limit": 100000})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert len(r.json()["rows"]) <= 5000


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE de",
        "DELETE FROM de",
        "INSERT INTO de VALUES (1)",
        "CREATE TABLE x AS SELECT 1",
        "ATTACH 'x.db' AS x",
        "COPY de TO '/tmp/x.csv'",
        "PRAGMA database_list",
        "SELECT 1; DROP TABLE de",
        "SELECT * FROM read_csv('/etc/passwd')",
        "INSTALL httpfs",
    ],
)
def test_query_rejects_non_readonly(client, sql):
    r = client.post("/api/bundles/toy/query", json={"sql": sql})
    assert r.status_code == 400, f"should reject: {sql}"


# A1.4 default view
def test_default_view_is_valid_and_useful(client):
    r = client.get("/api/bundles/toy/default-view")
    assert r.status_code == 200
    spec = r.json()
    assert spec["bundle"] == "toy"
    types = [p["type"] for p in spec["panels"]]
    assert "table" in types
    assert any(p["type"] == "plot" and p.get("kind") == "scatter" for p in spec["panels"])
    assert len(spec["panels"]) >= 4
    v = client.post("/api/validate-spec", json=spec).json()
    assert v["valid"] is True, v


# A1.5 spec validation
def _valid_spec():
    return {
        "version": 1,
        "title": "t",
        "bundle": "toy",
        "filters": [],
        "panels": [
            {
                "id": "volcano",
                "type": "plot",
                "title": "Volcano",
                "table": "de",
                "kind": "scatter",
                "x": {"field": "log2FoldChange"},
                "y": {"expr": "-log10(padj)"},
                "label": {"field": "gene_name", "values": []},
            },
            {"id": "genes", "type": "table", "title": "Genes", "table": "de", "columns": ["gene_name", "padj"]},
        ],
        "layout": [{"i": "volcano", "x": 0, "y": 0, "w": 6, "h": 8}, {"i": "genes", "x": 6, "y": 0, "w": 6, "h": 8}],
    }


def test_validate_good_spec(client):
    assert client.post("/api/validate-spec", json=_valid_spec()).json()["valid"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["panels"][0].update(table="nope"),
        lambda s: s["panels"][0]["x"].update(field="not_a_column"),
        lambda s: s["panels"][1].update(id="volcano"),  # duplicate id
        lambda s: s["layout"].pop(),  # panel without layout
        lambda s: s["panels"][0]["y"].update(expr="(SELECT 1)"),
        lambda s: s["panels"][0]["y"].update(expr="read_csv('x')"),
        lambda s: s["panels"][0]["y"].update(expr="-log10(secret_col)"),
        lambda s: s["filters"].append({"id": "f", "table": "de", "field": "nope", "op": "<", "value": 1, "enabled": True}),
    ],
)
def test_validate_rejects_bad_spec(client, mutate):
    s = _valid_spec()
    mutate(s)
    v = client.post("/api/validate-spec", json=s).json()
    assert v["valid"] is False
    assert v["errors"]


# A1.6 panel data
def test_panel_data_scatter_expr_and_filter(client, session, h):
    sid = session["session_id"]
    spec = session["spec"]
    idx = h.first_scatter(spec)
    pid = spec["panels"][idx]["id"]
    r = client.post(f"/api/sessions/{sid}/panel-data", json={"panel_id": pid})
    assert r.status_code == 200, r.text
    d = r.json()
    assert {"x", "y"} <= set(d["columns"])
    n_all = len(d["rows"])
    assert n_all > 0
    # add a padj filter via patch → fewer rows
    patch = [{"op": "add", "path": "/filters/-", "value": {"id": "sig", "table": spec["panels"][idx]["table"],
              "field": "padj", "op": "<", "value": 0.001, "enabled": True}}]
    assert client.post(f"/api/sessions/{sid}/patch", json={"patch": patch}).status_code == 200
    d2 = client.post(f"/api/sessions/{sid}/panel-data", json={"panel_id": pid}).json()
    assert 0 < len(d2["rows"]) < n_all


def test_panel_data_unknown_panel_404(client, session):
    r = client.post(f"/api/sessions/{session['session_id']}/panel-data", json={"panel_id": "nope"})
    assert r.status_code == 404
