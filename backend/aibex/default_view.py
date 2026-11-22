"""Default view for a bundle (docs/api.md → "Default view").

`default_view(bundle)` returns a valid spec: the bundle's own `default_view` file when bundle.yaml names one and it
validates, else a generated one. Generation finds column roles (fold change, adjusted p-value, mean expression, gene
name) by common DESeq2 / edgeR / limma names – the only place where such names appear; the frontend never knows them.

Generated panels (in order): volcano scatter of the DE table (first plot, always with `label`), MA plot, PCA and a
top-genes heatmap of a matrix table, then the DE table. Bundles without a DE-like table get a generic scatter /
histogram / table view instead.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from aibex.bundles import Bundle
from aibex.validate import validate_spec

log = logging.getLogger(__name__)

# common column names per role, in order of preference (matched case-insensitively)
ROLE_NAMES: dict[str, list[str]] = {
    "fc": ["log2FoldChange", "log2FC", "logFC", "log2_fold_change", "log2fc_ko_vs_wt", "lfc", "log2_fc"],
    "padj": ["padj", "FDR", "adj.P.Val", "p_adj", "padj_bh", "qvalue", "q_value", "qval", "fdr_bh"],
    "pvalue": ["pvalue", "PValue", "P.Value", "p_value", "pval"],
    "mean": ["baseMean", "AveExpr", "logCPM", "mean_expr", "base_mean", "meanExpr"],
    "name": ["gene_name", "symbol", "gene_symbol", "SYMBOL", "external_gene_name", "Name", "gene"],
}
_LOG_SCALE_MEANS = {"basemean", "base_mean", "mean_expr", "meanexpr"}  # raw means → log10 on the MA x axis
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PADJ_CUTOFF = 0.05
LFC_CUTOFF = 1
# Volcano/MA colours (T53): the app palette's red (readable on the light and the dark surface) and a mid grey that
# recedes in both themes. See frontend/src/lib/palette.ts.
SIG_PALETTE = {"significant": "#e34948", "n.s.": "#a8a7a0"}


def find_role(columns: list[str], role: str) -> str | None:
    lower = {c.lower(): c for c in columns}
    for name in ROLE_NAMES[role]:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _q(col: str) -> str:
    """Column reference for an `expr` (double-quoted unless a plain identifier)."""
    return col if _IDENT.match(col) else '"' + col.replace('"', '""') + '"'


def _numeric(bundle: Bundle, table: str) -> list[str]:
    t = bundle.tables[table]
    return [c for c, m in t["columns"].items() if m["type"] in ("int", "float") and c != t.get("key")]


def _strings(bundle: Bundle, table: str) -> list[str]:
    return [c for c, m in bundle.tables[table]["columns"].items() if m["type"] == "string"]


def _linked(bundle: Bundle, a: str, b: str) -> bool:
    for lk in bundle.links:
        ta, tb = lk["from"].split(".", 1)[0], lk["to"].split(".", 1)[0]
        if {ta, tb} == {a, b}:
            return True
    return False


def _find_de_table(bundle: Bundle) -> tuple[str, dict[str, str]] | None:
    """The first table with a fold-change and a p-value column; prefers a table named `de`."""
    names = sorted(bundle.tables, key=lambda n: (n != "de", list(bundle.tables).index(n)))
    for name in names:
        cols = list(bundle.tables[name]["columns"])
        roles = {r: c for r in ROLE_NAMES if (c := find_role(cols, r))}
        if "fc" in roles and ("padj" in roles or "pvalue" in roles):
            return name, roles
    return None


def _matrix_tables(bundle: Bundle) -> list[str]:
    return [t for t in bundle.tables if len(bundle.matrix_columns(t)) >= 2]


def _group_column(bundle: Bundle) -> str | None:
    """First samples.tsv annotation column (not `sample`) – used for PCA colour and heatmap grouping."""
    return bundle.samples_columns[1] if len(bundle.samples_columns) > 1 else None


def _layout(panels: list[dict], wide: set[str]) -> list[dict]:
    """Two panels per row (w=6, h=9); ids in `wide` take a full row."""
    out, x, y = [], 0, 0
    for p in panels:
        w = 12 if p["id"] in wide else 6
        if x + w > 12:
            x, y = 0, y + 9
        out.append({"i": p["id"], "x": x, "y": y, "w": w, "h": 9})
        x += w
        if x >= 12:
            x, y = 0, y + 9
    return out


def _de_panels(bundle: Bundle, de: str, roles: dict[str, str]) -> list[dict]:
    key = bundle.tables[de].get("key")
    fc = roles["fc"]
    p = roles.get("padj") or roles["pvalue"]
    p_label = "padj" if "padj" in roles else "p-value"
    name = roles.get("name") or key or (_strings(bundle, de) or [None])[0]
    contrast = (bundle.meta.get("contrast") or {}).get("name")
    vs = f": {contrast.replace('_', ' ')}" if isinstance(contrast, str) else ""

    sig = f"CASE WHEN {_q(p)} < {PADJ_CUTOFF} AND abs({_q(fc)}) > {LFC_CUTOFF} THEN 'significant' ELSE 'n.s.' END"
    volcano: dict[str, Any] = {
        "id": "volcano",
        "type": "plot",
        "title": f"Volcano{vs}",
        "table": de,
        "kind": "scatter",
        "x": {"field": fc, "label": "log2 fold change"},
        "y": {"expr": f"-log10({_q(p)})", "label": f"-log10 {p_label}"},
        "color": {"expr": sig, "palette": dict(SIG_PALETTE)},
    }
    if name:
        volcano["label"] = {"field": name, "values": []}
    panels = [volcano]

    mean = roles.get("mean")
    if mean:
        if mean.lower() in _LOG_SCALE_MEANS:
            x = {"expr": f"log10({_q(mean)} + 1)", "label": f"log10 {mean}"}
        else:
            x = {"field": mean, "label": mean}
        panels.append({
            "id": "ma-plot",
            "type": "plot",
            "title": "MA plot",
            "table": de,
            "kind": "scatter",
            "x": x,
            "y": {"field": fc, "label": "log2 fold change"},
            "color": {"expr": sig, "palette": dict(SIG_PALETTE)},
        })

    group = _group_column(bundle)
    matrices = _matrix_tables(bundle)
    matrix = next((m for m in matrices if m != de and _linked(bundle, m, de)), None) or next(
        (m for m in matrices if m != de), None
    )
    if matrix:
        pca: dict[str, Any] = {"id": "pca", "type": "plot", "kind": "pca", "title": "PCA of samples",
                               "table": matrix, "top_n": 500, "scale": "log1p"}
        if group:
            pca["color"] = {"field": group}
        panels.append(pca)
        if _linked(bundle, matrix, de):
            heatmap: dict[str, Any] = {"id": "top-genes", "type": "plot", "kind": "heatmap",
                                       "title": f"Top 30 genes by {p_label}", "table": matrix,
                                       "rows": {"top_n": 30, "by": f"{de}.{p}", "values": []}, "scale": "row-z"}
            if group:
                heatmap["group_by"] = group
            panels.append(heatmap)

    cols = [c for c in dict.fromkeys([name, key, mean, fc, p]) if c]
    panels.append({"id": "genes", "type": "table", "title": "Genes", "table": de, "columns": cols,
                   "sort": [{"field": p, "dir": "asc"}], "page_size": 25})
    # no mean column and/or no matrix table: fill up to 4 panels with distributions
    fillers = [
        {"id": "fc-histogram", "type": "plot", "title": "Fold change distribution", "table": de,
         "kind": "histogram", "x": {"field": fc, "label": "log2 fold change"}},
        {"id": "p-histogram", "type": "plot", "title": f"{p_label} distribution", "table": de,
         "kind": "histogram", "x": {"field": p, "label": p_label}},
    ]
    while len(panels) < 4 and fillers:
        panels.insert(-1, fillers.pop(0))
    return panels


def _generic_panels(bundle: Bundle) -> list[dict]:
    """No DE-like table: scatter/histogram of the first table with two numeric columns, plus a table per table."""
    panels: list[dict] = []
    plain = [t for t in bundle.tables if t not in _matrix_tables(bundle)] or list(bundle.tables)
    first = next((t for t in plain if len(_numeric(bundle, t)) >= 2), None)
    if first:
        a, b = _numeric(bundle, first)[:2]
        key = bundle.tables[first].get("key") or (_strings(bundle, first) or [None])[0]
        scatter: dict[str, Any] = {"id": "overview", "type": "plot", "title": f"{first}: {b} vs {a}",
                                   "table": first, "kind": "scatter", "x": {"field": a}, "y": {"field": b}}
        if key:
            scatter["label"] = {"field": key, "values": []}
        panels.append(scatter)
        panels.append({"id": "distribution", "type": "plot", "title": f"{first}: {a}", "table": first,
                       "kind": "histogram", "x": {"field": a}})
    for t in plain:
        panels.append({"id": _kebab(f"{t}-table"), "type": "table", "title": t, "table": t, "page_size": 25})
    return panels


def _kebab(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s if s and s[0].isalpha() else f"t-{s}"


def generate_default_view(bundle: Bundle) -> dict:
    found = _find_de_table(bundle)
    if found:
        de, roles = found
        panels = _de_panels(bundle, de, roles)
        wide = {"genes"}
        key = bundle.tables[de].get("key")
    else:
        panels = _generic_panels(bundle)
        wide = {p["id"] for p in panels if p["type"] == "table"}
        first_table = next((p["table"] for p in panels if "table" in p), None)
        key = bundle.tables[first_table].get("key") if first_table else None
    spec: dict[str, Any] = {
        "version": 1,
        "title": bundle.meta.get("title") or bundle.id,
        "bundle": bundle.id,
        "theme": {"palette": "default", "dark": False},
        "filters": [],
        "panels": panels,
        "layout": _layout(panels, wide),
    }
    if key:
        spec["selection"] = {"key": key, "linked": True}
    return spec


def _bundle_default_file(bundle: Bundle) -> dict | None:
    rel = bundle.meta.get("default_view")
    if not rel:
        return None
    path = (bundle.path / str(rel)).resolve()
    if not path.is_relative_to(bundle.path.resolve()) or not path.is_file():
        log.warning("bundle %s: default_view %r not found inside the bundle; generating one", bundle.id, rel)
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("bundle %s: default_view %r unreadable (%s); generating one", bundle.id, rel, exc)
        return None
    if isinstance(data, dict):
        data.setdefault("bundle", bundle.id)
    return data


def default_view(bundle: Bundle) -> dict:
    """The bundle's own default view if present and valid, else a generated one (which is validated too)."""
    own = _bundle_default_file(bundle)
    if own is not None:
        _, errors = validate_spec(own, bundle)
        if not errors:
            return own
        log.warning("bundle %s: default_view is invalid (%s); generating one", bundle.id, "; ".join(errors[:3]))
    spec = generate_default_view(bundle)
    _, errors = validate_spec(spec, bundle)
    if errors:  # should not happen; keep the demo alive with tables only
        log.error("bundle %s: generated default view invalid: %s", bundle.id, errors)
        panels = [{"id": _kebab(f"{t}-table"), "type": "table", "title": t, "table": t} for t in bundle.tables]
        spec = {"version": 1, "title": spec["title"], "bundle": bundle.id, "filters": [], "panels": panels,
                "layout": _layout(panels, {p["id"] for p in panels})}
    return spec
