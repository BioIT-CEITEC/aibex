"""Read-only SQL on a bundle (docs/api.md, "Query details").

Guard, in this order:
1. DuckDB's own parser (`duckdb.extract_statements`) must find exactly one statement of type SELECT (incl. WITH,
   VALUES, FROM-first, DESCRIBE/SUMMARIZE, which DuckDB reports as SELECT).
2. DuckDB's tokenizer: no call to a file/network/meta table function (`read_csv`, `glob`, `query`, ...). Names inside
   string literals and comments are ignored because they are separate token types.
3. Defence in depth (bundles.py): the connection has external access disabled and its configuration locked.

The same guard is used by the `query_data` LLM tool and widget input SQL.
"""

from __future__ import annotations

import datetime as dt
import decimal
import math
import uuid
from typing import Any

import duckdb

DEFAULT_LIMIT = 200
MAX_LIMIT = 5000

# function names that read files / the network / other databases, or run SQL given as a string
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "glob",
        "query",
        "query_table",
        "sniff_csv",
        "parquet_scan",
        "parquet_metadata",
        "parquet_schema",
        "parquet_file_metadata",
        "parquet_kv_metadata",
        "csv_scan",
        "json_scan",
        "iceberg_scan",
        "iceberg_metadata",
        "iceberg_snapshots",
        "delta_scan",
        "sqlite_scan",
        "sqlite_attach",
        "postgres_scan",
        "postgres_attach",
        "postgres_query",
        "mysql_scan",
        "mysql_query",
        "st_read",
        "getenv",
        "load_aws_credentials",
        "duckdb_secrets",
        "duckdb_settings",
        "duckdb_extensions",
        "which_secret",
    }
)
FORBIDDEN_PREFIXES = ("read_", "pragma_", "scan_", "httpfs_")


class QueryError(ValueError):
    """The SQL is not allowed or failed; the message is safe to show (HTTP 400)."""


def _tokens(sql: str) -> list[tuple[str, str]]:
    """(text, type-name) for every token of sql, comments dropped."""
    raw = duckdb.tokenize(sql)
    out: list[tuple[str, str]] = []
    for i, (start, ttype) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else len(sql)
        name = getattr(ttype, "name", str(ttype)).split(".")[-1]
        if name == "comment":
            continue
        out.append((sql[start:end].strip(), name))
    return out


def _forbidden_function(sql: str) -> str | None:
    toks = _tokens(sql)
    for i, (text, ttype) in enumerate(toks):
        if ttype not in {"identifier", "keyword"}:
            continue
        if i + 1 >= len(toks) or not toks[i + 1][0].startswith("("):
            continue
        name = text.strip('"').lower().rsplit(".", 1)[-1]
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_PREFIXES):
            return name
    return None


def check_readonly(sql: str) -> str:
    """Validate sql and return the single statement's text (without trailing `;`); raises QueryError."""
    if not isinstance(sql, str) or not sql.strip():
        raise QueryError("empty SQL")
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        raise QueryError(f"SQL parse error: {exc}") from None
    if len(statements) != 1:
        raise QueryError(f"exactly one statement allowed, got {len(statements)}")
    st = statements[0]
    if st.type != duckdb.StatementType.SELECT:
        raise QueryError(f"only SELECT/WITH queries are allowed, got {st.type.name}")
    bad = _forbidden_function(sql)
    if bad:
        raise QueryError(f"function {bad!r} is not allowed (no file, network or meta access)")
    return st.query.strip().rstrip(";").strip()


def sql_parameters(sql: str) -> list[str]:
    """Prepared-statement parameters used in sql, in order of first use: `$name` → "name", `$1` → "1", `?` → "?".
    Inside string literals and comments they are separate tokens and do not count."""
    toks = _tokens(sql)
    found: list[str] = []
    for i, (text, ttype) in enumerate(toks):
        name = None
        if ttype == "operator" and text == "$" and i + 1 < len(toks):
            nxt, ntype = toks[i + 1]
            if ntype in {"identifier", "keyword", "numeric_const"}:
                name = nxt.strip('"')
        elif ttype == "operator" and text == "?":
            name = "?"
        elif ttype == "operator" and text.startswith("$") and len(text) > 1:  # tokenizer variants: "$selected"
            name = text[1:]
        if name is not None and name not in found:
            found.append(name)
    return found


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(0, min(int(limit), MAX_LIMIT))


def jsonable(v: Any) -> Any:
    """Make a DuckDB value JSON-safe: NaN/inf → None, dates → ISO strings, Decimal → float."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, decimal.Decimal):
        return jsonable(float(v))
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return v


def run_query(
    cur: duckdb.DuckDBPyConnection, sql: str, limit: int | None = None, params: list | dict | None = None
) -> dict:
    """Run a guarded read-only query: `{columns, rows, row_count, truncated}` (rows as arrays, ≤ limit).
    `params` are bound by DuckDB (positional list, or a dict for `$name` parameters) – never string-formatted."""
    stmt = check_readonly(sql)
    n = clamp_limit(limit)
    try:
        rel = cur.execute(stmt, params or [])
        columns = [d[0] for d in rel.description or []]
        fetched = rel.fetchmany(n + 1)
        truncated = len(fetched) > n
        rows = fetched[:n]
        if truncated:
            (row_count,) = cur.execute(f"SELECT count(*) FROM (\n{stmt}\n)", params or []).fetchone()
        else:
            row_count = len(rows)
    except duckdb.Error as exc:
        raise QueryError(f"query failed: {exc}") from None
    return {
        "columns": columns,
        "rows": [[jsonable(v) for v in r] for r in rows],
        "row_count": int(row_count),
        "truncated": truncated,
    }
