"""Unit tests for bundle loading (T11): DuckDB tables, inferred types, links, errors, registry caching."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import duckdb
import pytest
import yaml
from fastapi.testclient import TestClient

from aibex.bundles import BundleError, BundleNotFound, BundleRegistry, duckdb_type_to_vocab, load_bundle
from aibex.config import Settings
from aibex.main import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _make_toy(d: Path, bundle_id: str = "toy") -> Path:
    spec = importlib.util.spec_from_file_location("make_toy_bundle", FIXTURES / "make_toy_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make_toy_bundle(d, bundle_id)


@pytest.fixture()
def data_dir(tmp_path) -> Path:
    _make_toy(tmp_path)
    return tmp_path


def _edit_manifest(bundle_dir: Path, fn) -> None:
    p = bundle_dir / "bundle.yaml"
    meta = yaml.safe_load(p.read_text())
    fn(meta)
    p.write_text(yaml.safe_dump(meta, sort_keys=False))


@pytest.mark.parametrize(
    ("duck", "vocab"),
    [
        ("VARCHAR", "string"),
        ("BIGINT", "int"),
        ("UINTEGER", "int"),
        ("DOUBLE", "float"),
        ("DECIMAL(10,2)", "float"),
        ("BOOLEAN", "bool"),
        ("DATE", "date"),
        ("TIMESTAMP WITH TIME ZONE", "date"),
        ("LIST", "string"),
    ],
)
def test_type_vocabulary(duck, vocab):
    assert duckdb_type_to_vocab(duck) == vocab


def test_load_toy_tables_types_rowcounts(data_dir):
    b = load_bundle(data_dir / "toy" / "bundle.yaml")
    assert set(b.tables) == {"de", "counts", "editing"}
    assert b.tables["de"]["row_count"] == 200
    assert b.tables["editing"]["key"] == "site_id"
    # declared types win, undeclared columns are inferred
    assert b.tables["editing"]["columns"]["position"]["type"] == "int"
    assert b.tables["counts"]["columns"]["KO_1"]["type"] == "int"
    assert b.tables["de"]["columns"]["padj"]["type"] == "float"
    assert {"from": "editing.gene_id", "to": "de.gene_id"} in b.links


def test_tables_joinable_in_sql(data_dir):
    b = load_bundle(data_dir / "toy" / "bundle.yaml")
    (n,) = b.cursor().execute("SELECT count(*) FROM editing e JOIN de d USING (gene_id)").fetchone()
    assert n == 300


def test_connection_has_no_external_access(data_dir):
    b = load_bundle(data_dir / "toy" / "bundle.yaml")
    parquet = data_dir / "toy" / "tables" / "de.parquet"
    with pytest.raises(duckdb.Error):
        b.cursor().execute(f"SELECT * FROM read_parquet('{parquet}')").fetchall()
    with pytest.raises(duckdb.Error):
        b.cursor().execute("SET enable_external_access = true")


def test_tsv_tables_are_supported(data_dir):
    bdir = data_dir / "toy"
    (bdir / "tables" / "extra.tsv").write_text("id\tscore\tflag\na\t1.5\ttrue\nb\t2.0\tfalse\n")

    def add(meta):
        meta["tables"]["extra"] = {"file": "tables/extra.tsv", "key": "id"}

    _edit_manifest(bdir, add)
    b = load_bundle(bdir / "bundle.yaml")
    cols = b.tables["extra"]["columns"]
    assert cols == {"id": {"type": "string"}, "score": {"type": "float"}, "flag": {"type": "bool"}}
    assert b.tables["extra"]["row_count"] == 2


@pytest.mark.parametrize(
    "breakage",
    [
        lambda m: m["tables"]["de"].update(file="tables/missing.parquet"),
        lambda m: m["tables"]["de"].update(file="../../outside.parquet"),
        lambda m: m["tables"]["de"]["columns"].update(nope={"type": "float"}),
        lambda m: m["tables"]["de"].update(key="nope"),
        lambda m: m["links"].append({"from": "editing.nope", "to": "de.gene_id"}),
        lambda m: m["tables"].update({"bad name": {"file": "tables/de.parquet"}}),
    ],
)
def test_broken_bundles_raise_bundle_error(data_dir, breakage):
    _edit_manifest(data_dir / "toy", breakage)
    with pytest.raises(BundleError):
        load_bundle(data_dir / "toy" / "bundle.yaml")


def test_registry_unknown_and_cache_reload(data_dir):
    reg = BundleRegistry(data_dir)
    with pytest.raises(BundleNotFound):
        reg.get("nope")
    b1 = reg.get("toy")
    assert reg.get("toy") is b1
    manifest = data_dir / "toy" / "bundle.yaml"
    _edit_manifest(data_dir / "toy", lambda m: m.update(title="Renamed"))
    st = manifest.stat()
    os.utime(manifest, (st.st_atime, st.st_mtime + 10))
    b2 = reg.get("toy")
    assert b2 is not b1
    assert b2.schema()["title"] == "Renamed"


def test_schema_endpoint_and_errors(data_dir):
    _make_toy(data_dir, "broken")
    _edit_manifest(data_dir / "broken", lambda m: m["tables"]["de"].update(file="tables/missing.parquet"))
    client = TestClient(create_app(Settings(data_dir=data_dir, llm_provider="fake")))
    s = client.get("/api/bundles/toy/schema").json()
    assert s["id"] == "toy"
    assert s["organism"] == "Mus musculus"
    assert s["tables"]["counts"]["row_count"] == 200
    assert client.get("/api/bundles/nope/schema").status_code == 404
    r = client.get("/api/bundles/broken/schema")
    assert r.status_code == 500
    assert "missing.parquet" in r.json()["detail"]
