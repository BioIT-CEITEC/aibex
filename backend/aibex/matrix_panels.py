"""Panel data for `pca` and `heatmap` plots, computed server-side from a matrix table (docs/api.md → "Panel data
shape", docs/spec-format.md → `pca`, `heatmap`).

A matrix table is the key column plus one numeric column per sample (`Bundle.matrix_columns`). Filters apply to the
matrix rows like to any other panel (own table and one hop through bundle links).

- `pca`: rows with a missing value are dropped, values scaled (`log1p` default, or `none`), the `top_n` (default 500)
  most variable rows kept, each row centred, then the samples are projected on the first two principal components.
  Returns `x`, `y`, `sample` plus the samples.tsv annotation columns, and `x_label`/`y_label` with the explained
  variance. The eigendecomposition runs on the small samples × samples Gram matrix in pure Python (Jacobi), so no
  numpy dependency is needed; sample counts in a results bundle are small.
- `heatmap`: rows = explicit key `values` (case-insensitive, in the given order) or the `top_n` rows ascending by
  `rows.by` (`<table>.<column>`, the matrix table or a linked one); columns = samples ordered by `group_by` then
  samples.tsv order; `scale` `row-z` (default), `log1p` or `none`. Long format `row`, `column`, `value`, `group`;
  only whole rows are returned under the 5000-row cap.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb

from aibex.bundles import Bundle
from aibex.query import jsonable
from aibex.spec import PlotPanel

MAX_ROWS = 5000
PCA_TOP_N = 500


class MatrixPanelError(ValueError):
    """Panel data cannot be computed (message is safe to show)."""


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _scale_value(v: Any, scale: str) -> float | None:
    if v is None:
        return None
    x = float(v)
    if math.isnan(x) or math.isinf(x):
        return None
    if scale == "log1p":
        return math.log1p(x) if x > -1 else None
    return x


def _samples(bundle: Bundle, table: str) -> list[str]:
    """Sample columns in samples.tsv order (matrix order when there is no samples.tsv)."""
    cols = bundle.matrix_columns(table)
    if len(cols) < 2:
        raise MatrixPanelError(f"{table!r} is not a matrix table (fewer than 2 numeric sample columns)")
    if bundle.samples:
        order = [str(s.get(bundle.samples_columns[0])) for s in bundle.samples]
        cols = sorted(cols, key=lambda c: order.index(c) if c in order else len(order))
    return cols


def _annotations(bundle: Bundle) -> dict[str, dict]:
    if not bundle.samples:
        return {}
    first = bundle.samples_columns[0]
    return {str(s.get(first)): s for s in bundle.samples}


def _fetch(bundle: Bundle, sql: str, params: list) -> list[tuple]:
    try:
        return bundle.cursor().execute(sql, params).fetchall()
    except duckdb.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise MatrixPanelError(f"query failed: {first}") from None


def _filtered_source(table: str, conds: list[str]) -> str:
    if conds:
        return f"(SELECT * FROM {_q(table)} WHERE {' AND '.join(conds)})"
    return _q(table)


# --- PCA ---------------------------------------------------------------------------------------------------------
def jacobi_eigen(a: list[list[float]], max_sweeps: int = 100) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues (descending) and eigenvectors (as columns: vecs[i][k] = component i of vector k) of a symmetric
    matrix, by cyclic Jacobi rotations."""
    n = len(a)
    m = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_sweeps):
        off = sum(m[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        scale = sum(m[i][i] ** 2 for i in range(n)) or 1.0
        if off <= 1e-22 * scale:
            break
        for p in range(n - 1):
            for r in range(p + 1, n):
                if abs(m[p][r]) < 1e-300:
                    continue
                theta = (m[r][r] - m[p][p]) / (2 * m[p][r])
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    mkp, mkr = m[k][p], m[k][r]
                    m[k][p] = c * mkp - s * mkr
                    m[k][r] = s * mkp + c * mkr
                for k in range(n):
                    mpk, mrk = m[p][k], m[r][k]
                    m[p][k] = c * mpk - s * mrk
                    m[r][k] = s * mpk + c * mrk
                for k in range(n):
                    vkp, vkr = v[k][p], v[k][r]
                    v[k][p] = c * vkp - s * vkr
                    v[k][r] = s * vkp + c * vkr
    order = sorted(range(n), key=lambda k: -m[k][k])
    vals = [m[k][k] for k in order]
    vecs = [[v[i][k] for k in order] for i in range(n)]
    return vals, vecs


def pca_data(bundle: Bundle, p: PlotPanel, conds: list[str], params: list) -> dict:
    samples = _samples(bundle, p.table)
    scale = p.scale or "log1p"
    top_n = p.top_n or PCA_TOP_N
    sql = f"SELECT {', '.join(_q(s) for s in samples)} FROM {_filtered_source(p.table, conds)} AS t"
    rows: list[list[float]] = []
    for r in _fetch(bundle, sql, params):
        vals = [_scale_value(v, scale) for v in r]
        if all(v is not None for v in vals):
            rows.append(vals)  # type: ignore[arg-type]
    n = len(samples)
    # top_n most variable rows, each centred across samples
    scored = []
    for vals in rows:
        mean = sum(vals) / n
        centred = [v - mean for v in vals]
        var = sum(c * c for c in centred)
        if var > 0:
            scored.append((var, centred))
    scored.sort(key=lambda t: -t[0])
    x = [c for _, c in scored[:top_n]]
    if len(x) < 2:
        raise MatrixPanelError(f"PCA needs at least 2 varying rows; {len(x)} left after filters")
    gram = [[sum(row[i] * row[j] for row in x) for j in range(n)] for i in range(n)]
    vals, vecs = jacobi_eigen(gram)
    total = sum(max(v, 0.0) for v in vals) or 1.0
    pcs = []
    for k in (0, 1):
        lam = max(vals[k], 0.0) if k < len(vals) else 0.0
        vec = [vecs[i][k] for i in range(n)]
        big = max(range(n), key=lambda i: abs(vec[i]))
        sign = 1.0 if vec[big] >= 0 else -1.0  # deterministic orientation
        pcs.append(([sign * c * math.sqrt(lam) for c in vec], 100 * lam / total))

    ann = _annotations(bundle)
    extra = list(bundle.samples_columns[1:])
    columns = ["x", "y", "sample", *extra]
    out_rows = []
    for i, s in enumerate(samples):
        a = ann.get(s, {})
        out_rows.append([pcs[0][0][i], pcs[1][0][i], s, *[jsonable(a.get(c)) for c in extra]])
    return {
        "columns": columns,
        "rows": [[jsonable(v) for v in r] for r in out_rows],
        "truncated": False,
        "x_label": f"PC1 ({pcs[0][1]:.0f} %)",
        "y_label": f"PC2 ({pcs[1][1]:.0f} %)",
    }


# --- heatmap -----------------------------------------------------------------------------------------------------
def _heatmap_rows(bundle: Bundle, p: PlotPanel, conds: list[str], params: list, samples: list[str],
                  link_columns) -> list[tuple]:
    """(key, *sample values) of the selected matrix rows in display order."""
    key = bundle.tables[p.table].get("key")
    if key is None:
        raise MatrixPanelError(f"heatmap needs a key column in matrix table {p.table!r}")
    rows = p.rows
    assert rows is not None  # structural validation requires `rows`
    cols = ", ".join(f"m.{_q(s)}" for s in samples)
    src = _filtered_source(p.table, conds)
    if rows.values:
        wanted = [str(v).lower() for v in rows.values]
        sql = (f"SELECT m.{_q(key)}, {cols} FROM {src} AS m "
               f"WHERE lower(CAST(m.{_q(key)} AS VARCHAR)) IN ({', '.join('?' for _ in wanted)})")
        found = _fetch(bundle, sql, params + wanted)
        pos = {w: i for i, w in reversed(list(enumerate(wanted)))}
        return sorted(found, key=lambda r: pos.get(str(r[0]).lower(), len(wanted)))
    by_table, _, by_col = (rows.by or "").partition(".")
    limit = int(rows.top_n or 0)
    if by_table == p.table:
        sql = (f"SELECT m.{_q(key)}, {cols} FROM {src} AS m "
               f"ORDER BY m.{_q(by_col)} ASC NULLS LAST, m.{_q(key)} LIMIT {limit}")
        return _fetch(bundle, sql, params)
    link = link_columns(bundle, p.table, by_table)
    if link is None:
        raise MatrixPanelError(f"rows.by: table {by_table!r} is not linked to {p.table!r}")
    own, other = link
    sql = (f"SELECT m.{_q(key)}, {cols} FROM {src} AS m "
           f"JOIN (SELECT {_q(other)} AS _k, min({_q(by_col)}) AS _by FROM {_q(by_table)} GROUP BY 1) AS o "
           f"ON m.{_q(own)} = o._k ORDER BY o._by ASC NULLS LAST, m.{_q(key)} LIMIT {limit}")
    return _fetch(bundle, sql, params)


def heatmap_data(bundle: Bundle, p: PlotPanel, conds: list[str], params: list, link_columns) -> dict:
    samples = _samples(bundle, p.table)
    scale = p.scale or "row-z"
    ann = _annotations(bundle)
    groups = {s: (ann.get(s, {}).get(p.group_by) if p.group_by else None) for s in samples}
    if p.group_by:
        first_seen: dict[Any, int] = {}
        for s in samples:
            first_seen.setdefault(groups[s], len(first_seen))
        samples = sorted(samples, key=lambda s: first_seen[groups[s]])  # stable: keeps samples.tsv order in a group

    found = _heatmap_rows(bundle, p, conds, params, samples, link_columns)
    max_rows = max(1, MAX_ROWS // len(samples))
    truncated = len(found) > max_rows
    out = []
    for r in found[:max_rows]:
        vals = [_scale_value(v, "log1p" if scale == "log1p" else "none") for v in r[1:]]
        if scale == "row-z":
            present = [v for v in vals if v is not None]
            if present:
                mean = sum(present) / len(present)
                sd = math.sqrt(sum((v - mean) ** 2 for v in present) / (len(present) - 1)) if len(present) > 1 else 0
                vals = [None if v is None else ((v - mean) / sd if sd > 0 else 0.0) for v in vals]
        for s, v in zip(samples, vals, strict=True):
            out.append([jsonable(r[0]), s, jsonable(v), jsonable(groups[s])])
    return {"columns": ["row", "column", "value", "group"], "rows": out, "truncated": truncated}
