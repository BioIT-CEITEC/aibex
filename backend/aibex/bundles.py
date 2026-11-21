"""Results bundles (docs/bundle-format.md): discovery, loading into DuckDB, schema.

Every bundle gets its own in-memory DuckDB database. Each table listed in bundle.yaml is materialised as a DuckDB
table of the same name (bundle tables are small result tables, see Q7), so bundle links can be joined directly in SQL.
After loading, external access is disabled and the configuration locked, so SQL run on the connection cannot read
files or the network (defence in depth for the query endpoint, docs/api.md).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import yaml

TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BundleError(Exception):
    """A bundle exists but cannot be loaded (broken manifest, missing file, ...)."""


class BundleNotFound(KeyError):
    pass


def _read_manifest(manifest: Path) -> dict:
    meta = yaml.safe_load(manifest.read_text()) or {}
    if not isinstance(meta, dict):
        raise BundleError("bundle.yaml must be a mapping")
    return meta


def list_bundles(data_dir: Path) -> list[dict]:
    """Return id/title/modalities/tables for every folder in data_dir that contains a bundle.yaml."""
    bundles: list[dict] = []
    if not data_dir.exists():
        return bundles
    for manifest in sorted(data_dir.glob("*/bundle.yaml")):
        try:
            meta = _read_manifest(manifest)
        except (yaml.YAMLError, BundleError) as exc:  # broken manifest should not take the app down
            bundles.append({"id": manifest.parent.name, "error": f"invalid bundle.yaml: {exc}"})
            continue
        bundles.append(
            {
                "id": meta.get("id", manifest.parent.name),
                "title": meta.get("title", manifest.parent.name),
                "modalities": meta.get("modalities", []),
                "tables": sorted((meta.get("tables") or {}).keys()),
            }
        )
    return bundles


def find_manifest(data_dir: Path, bundle_id: str) -> Path:
    """Locate the bundle.yaml whose id (or folder name, when no id is set) equals bundle_id."""
    if data_dir.exists():
        for manifest in sorted(data_dir.glob("*/bundle.yaml")):
            try:
                meta = _read_manifest(manifest)
            except (yaml.YAMLError, BundleError):
                meta = {}
            if meta.get("id", manifest.parent.name) == bundle_id:
                return manifest
    raise BundleNotFound(bundle_id)


def duckdb_type_to_vocab(duck_type: str) -> str:
    """Map a DuckDB column type to the bundle type vocabulary: string, int, float, bool, date."""
    t = duck_type.upper()
    if t == "BOOLEAN":
        return "bool"
    if t.removeprefix("U") in {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"}:
        return "int"
    if t in {"FLOAT", "REAL", "DOUBLE"} or t.startswith("DECIMAL"):
        return "float"
    if t.startswith(("DATE", "TIMESTAMP")):
        return "date"
    return "string"


@dataclass
class Bundle:
    id: str
    path: Path
    meta: dict
    con: duckdb.DuckDBPyConnection
    tables: dict[str, dict] = field(default_factory=dict)  # name -> schema entry (see schema())
    mtime: float = 0.0

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """A per-request cursor (DuckDB connections must not be shared across threads)."""
        return self.con.cursor()

    @property
    def links(self) -> list[dict]:
        return [{"from": str(lk["from"]), "to": str(lk["to"])} for lk in self.meta.get("links") or []]

    def schema(self) -> dict:
        out: dict[str, Any] = {"id": self.id, "title": self.meta.get("title", self.id)}
        if self.meta.get("organism"):
            out["organism"] = self.meta["organism"]
        out["tables"] = self.tables
        out["links"] = self.links
        return out


def _resolve_inside(base: Path, rel: str) -> Path:
    p = (base / rel).resolve()
    if not p.is_relative_to(base.resolve()):
        raise BundleError(f"table file {rel!r} points outside the bundle")
    if not p.is_file():
        raise BundleError(f"table file {rel!r} not found")
    return p


def _reader_sql(path: Path) -> str:
    lit = "'" + str(path).replace("'", "''") + "'"
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return f"read_parquet({lit})"
    if suffix in {".tsv", ".txt"}:
        return f"read_csv({lit}, delim='\t', header=true)"
    if suffix == ".csv":
        return f"read_csv({lit}, header=true)"
    raise BundleError(f"unsupported table format {path.suffix!r} (use parquet, tsv or csv)")


def load_bundle(manifest: Path) -> Bundle:
    """Load all tables of a bundle into a fresh in-memory DuckDB database and build its schema."""
    try:
        meta = _read_manifest(manifest)
    except yaml.YAMLError as exc:
        raise BundleError(f"invalid bundle.yaml: {exc}") from exc
    base = manifest.parent
    bundle_id = meta.get("id", base.name)
    con = duckdb.connect(":memory:")
    tables: dict[str, dict] = {}
    try:
        for name, tmeta in (meta.get("tables") or {}).items():
            tmeta = tmeta or {}
            if not TABLE_NAME_RE.match(str(name)):
                raise BundleError(f"invalid table name {name!r}")
            if not tmeta.get("file"):
                raise BundleError(f"table {name!r} has no file")
            path = _resolve_inside(base, str(tmeta["file"]))
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM {_reader_sql(path)}')
            declared = tmeta.get("columns") or {}
            columns: dict[str, dict] = {}
            for col, duck_type, *_ in con.execute(f'DESCRIBE "{name}"').fetchall():
                d = declared.get(col) or {}
                entry: dict[str, Any] = {"type": d.get("type") or duckdb_type_to_vocab(duck_type)}
                if d.get("description"):
                    entry["description"] = d["description"]
                columns[col] = entry
            missing = [c for c in declared if c not in columns]
            if missing:
                raise BundleError(f"table {name!r}: declared columns missing in {tmeta['file']}: {missing}")
            key = tmeta.get("key")
            if key is not None and key not in columns:
                raise BundleError(f"table {name!r}: key column {key!r} not found")
            (row_count,) = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()
            tables[str(name)] = {
                "description": tmeta.get("description", ""),
                "key": key,
                "row_count": int(row_count),
                "columns": columns,
            }
        for lk in meta.get("links") or []:
            for side in ("from", "to"):
                t, _, c = str(lk.get(side, "")).partition(".")
                if t not in tables or c not in tables[t]["columns"]:
                    raise BundleError(f"link {lk!r}: {side} column not found")
        # defence in depth: SQL on this connection must not touch files, network or settings
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
    except duckdb.Error as exc:
        con.close()
        raise BundleError(str(exc)) from exc
    except BundleError:
        con.close()
        raise
    return Bundle(id=bundle_id, path=base, meta=meta, con=con, tables=tables, mtime=manifest.stat().st_mtime)


class BundleRegistry:
    """Loads bundles lazily from data_dir and caches them; reloads when bundle.yaml changes."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._cache: dict[str, Bundle] = {}
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        return list_bundles(self.data_dir)

    def get(self, bundle_id: str) -> Bundle:
        """Return the loaded bundle; raises BundleNotFound or BundleError."""
        manifest = find_manifest(self.data_dir, bundle_id)
        with self._lock:
            cached = self._cache.get(bundle_id)
            if cached is not None and cached.mtime == manifest.stat().st_mtime:
                return cached
            bundle = load_bundle(manifest)
            if cached is not None:
                cached.con.close()
            self._cache[bundle_id] = bundle
            return bundle
