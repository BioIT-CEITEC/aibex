"""Unit tests for the read-only query guard and runner (T12, docs/api.md "Query details")."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from aibex.bundles import load_bundle
from aibex.config import Settings
from aibex.main import create_app
from aibex.query import QueryError, check_readonly, clamp_limit, jsonable, run_query, sql_parameters

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _make_toy(d: Path) -> Path:
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make_toy_bundle(d, "toy")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    _make_toy(d)
    return load_bundle(d / "toy" / "bundle.yaml")


@pytest.fixture()
def client(tmp_path):
    _make_toy(tmp_path)
    return TestClient(create_app(Settings(data_dir=tmp_path, llm_provider="fake")))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from de;",
        "WITH t AS (SELECT gene_id FROM de) SELECT count(*) FROM t",
        "FROM de LIMIT 3",
        "SELECT 'read_csv(x)' AS s",  # names inside string literals are fine
        "SELECT 1 -- glob('x')",  # and inside comments
        "SELECT gene_id AS read_parquet FROM de",  # identifier not followed by ( is fine
    ],
)
def test_guard_accepts_readonly(sql):
    check_readonly(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "SELECT 1; SELECT 2",
        "DROP TABLE de",
        "UPDATE de SET padj = 0",
        "SET threads = 1",
        "LOAD httpfs",
        "INSTALL httpfs",
        "CALL pragma_version()",
        "EXPLAIN SELECT 1",
        "DETACH memory",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM READ_PARQUET ('x.parquet')",
        'SELECT * FROM "read_text"(\'/etc/passwd\')',
        "SELECT * FROM glob('*')",
        "SELECT * FROM query('SELECT 1')",
        "SELECT * FROM pragma_database_list()",
        "SELECT * FROM duckdb_secrets()",
        "SELECT * FROM sqlite_scan('x.db', 't')",
        "SELECT getenv('HOME')",
        "SELEC 1",
    ],
)
def test_guard_rejects(sql):
    with pytest.raises(QueryError):
        check_readonly(sql)


def test_guard_strips_trailing_semicolon():
    assert check_readonly("SELECT 1 ;") == "SELECT 1"


@pytest.mark.parametrize(("given", "expected"), [(None, 200), (10, 10), (5000, 5000), (100000, 5000), (-5, 0)])
def test_clamp_limit(given, expected):
    assert clamp_limit(given) == expected


def test_run_query_truncation_and_row_count(bundle):
    out = run_query(bundle.cursor(), "SELECT site_id FROM editing ORDER BY site_id", limit=10)
    assert out["columns"] == ["site_id"]
    assert len(out["rows"]) == 10 and out["truncated"] is True and out["row_count"] == 300
    ordered = run_query(bundle.cursor(), "SELECT site_id FROM editing ORDER BY site_id", limit=300)["rows"]
    assert out["rows"] == ordered[:10]  # order of the original query is kept


def test_run_query_not_truncated_when_exact(bundle):
    out = run_query(bundle.cursor(), "SELECT * FROM editing", limit=300)
    assert out["truncated"] is False and out["row_count"] == 300


def test_run_query_with_params(bundle):
    gene = run_query(bundle.cursor(), "SELECT gene_id FROM de LIMIT 1")["rows"][0][0]
    out = run_query(bundle.cursor(), "SELECT gene_id FROM de WHERE gene_id = ?", params=[gene])
    assert out["rows"] == [[gene]]


def test_run_query_with_named_params(bundle):
    gene = run_query(bundle.cursor(), "SELECT gene_id FROM de LIMIT 1")["rows"][0][0]
    out = run_query(bundle.cursor(), "SELECT gene_id FROM de WHERE gene_id = $selected", params={"selected": gene})
    assert out["rows"] == [[gene]]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", []),
        ("SELECT * FROM de WHERE gene_id = $selected OR $selected IS NULL", ["selected"]),
        ("SELECT * FROM de WHERE gene_id = ? AND x = $1 AND y = $other", ["?", "1", "other"]),
        ("SELECT '$selected', '?' -- $hidden ?", []),  # inside literals / comments
    ],
)
def test_sql_parameters(sql, expected):
    assert sql_parameters(sql) == expected


def test_run_query_sql_error_is_query_error(bundle):
    with pytest.raises(QueryError):
        run_query(bundle.cursor(), "SELECT no_such_column FROM de")


def test_external_access_blocked_even_past_the_guard(bundle):
    # defence in depth: a replacement scan on a file path is not a function call, the connection must refuse it
    with pytest.raises(QueryError):
        run_query(bundle.cursor(), "SELECT * FROM '/etc/passwd'")
    with pytest.raises(duckdb.Error):
        bundle.cursor().execute("SET enable_external_access = true")


def test_tables_unchanged_after_rejected_writes(client):
    for sql in ["DROP TABLE de", "DELETE FROM de", "SELECT 1; DROP TABLE de"]:
        assert client.post("/api/bundles/toy/query", json={"sql": sql}).status_code == 400
    r = client.post("/api/bundles/toy/query", json={"sql": "SELECT count(*) AS n FROM de"})
    assert r.json()["rows"] == [[200]]


def test_jsonable_values():
    import datetime as dt
    import decimal

    assert jsonable(math.nan) is None
    assert jsonable(math.inf) is None
    assert jsonable(dt.date(2026, 11, 21)) == "2026-11-21"
    assert jsonable(decimal.Decimal("1.5")) == 1.5
    assert jsonable([1.0, math.nan]) == [1.0, None]


def test_endpoint_nan_is_null_and_400_detail(client):
    r = client.post("/api/bundles/toy/query", json={"sql": "SELECT 'nan'::DOUBLE AS x"})
    assert r.status_code == 200 and r.json()["rows"] == [[None]]
    r = client.post("/api/bundles/toy/query", json={"sql": "DROP TABLE de"})
    assert r.status_code == 400 and "SELECT" in r.json()["detail"]


def test_endpoint_unknown_bundle_404(client):
    assert client.post("/api/bundles/nope/query", json={"sql": "SELECT 1"}).status_code == 404
