# View spec format (v1)

The view spec is a JSON document that fully describes what Aibex View shows.
The frontend is a pure renderer of the spec. The LLM changes the UI only by sending
an RFC 6902 JSON Patch against the spec (tool `update_view`). The backend validates the
patched spec with Pydantic (`backend/aibex/spec.py`) and rejects anything invalid.

## Top level

```json
{
  "version": 1,
  "title": "ADAR2-KO: expression and RNA editing",
  "bundle": "adar2-editing",
  "theme": {"palette": "default", "dark": false},
  "filters": [ ... ],
  "panels": [ ... ],
  "layout": [ ... ],
  "selection": {"key": "gene_id", "linked": true}
}
```

| field | meaning |
|---|---|
| `version` | always `1` for now |
| `bundle` | id of the results bundle (see bundle-format.md) |
| `filters` | global filters, applied to every panel that uses the filtered table |
| `panels` | list of panels (plots, tables, text, widgets) |
| `layout` | grid positions, react-grid-layout format, 12 columns |
| `selection` | linked selection across panels by a shared key column |

## Filters

```json
{"id": "sig", "table": "de", "field": "padj", "op": "<=", "value": 0.05, "label": "padj ≤ 0.05", "enabled": true}
```
`op`: `<=`, `>=`, `<`, `>`, `==`, `!=`, `in`, `between` (value = [min, max]), `contains`.
Instead of `field`/`op`/`value` a filter may give a boolean `expr`, e.g.
`{"id": "lfc", "table": "de", "expr": "abs(log2FoldChange) > 1", "label": "|log2FC| > 1", "enabled": true}`.
`label` is optional. A filter also reaches panels on tables linked to its table (`docs/api.md` → "Filters").

## Panels

Common fields: `id` (unique, kebab-case), `type`, `title`, optional `description`.

### `plot`
```json
{
  "id": "volcano",
  "type": "plot",
  "title": "Volcano: KO vs WT",
  "table": "de",
  "kind": "scatter",
  "x": {"field": "log2FoldChange", "label": "log2 FC"},
  "y": {"expr": "-log10(padj)", "label": "-log10 padj"},
  "color": {"expr": "CASE WHEN padj < 0.05 THEN 'significant' ELSE 'n.s.' END", "palette": {"significant": "#d62728", "n.s.": "#bbbbbb"}},
  "size": null,
  "label": {"field": "gene_name", "values": ["Gria2", "Cyfip2"], "top_n": 10, "by": "padj"},
  "facet": null,
  "plotly": {}
}
```
- `kind`: `scatter`, `bar`, `box`, `violin`, `histogram`, `heatmap`, `line`, `pca` (`pca` and `heatmap` are computed server-side from a matrix table, see below).
- An axis (and `color`, `size`) is either `{"field": ...}` or `{"expr": ...}`. `expr` is a restricted DuckDB SQL expression over the table's columns, validated server-side. The grammar (allowed operators and functions) is defined once in `docs/api.md` → "Spec validation rules".
- `color` may carry a `palette` (`{value: colour}`, categorical) or a `colorscale` (Plotly name, continuous).
- `label`: `values` are labelled explicitly; `top_n` + `by` label the top rows by a column (ascending). The first scatter of a generated default view always has a `label` object (possibly with empty `values`).
- `plotly` holds optional raw Plotly layout/trace overrides (escape hatch; validated to be plain JSON). The frontend
  deep-merges `plotly.layout` and every other top-level key into the Plotly layout, and `plotly.trace` into every trace,
  e.g. `{"layout": {"yaxis": {"type": "log"}}, "trace": {"marker": {"opacity": 0.5}}}`.
- Rendering (frontend, `src/lib/plotFigure.ts`): a numeric `color` on scatter/line → continuous colour scale with a
  colour bar (`colorscale`, default Viridis); otherwise one trace per colour value (legend; `palette` keys match the
  value exactly, unknown values get the default colourway). The legend title is `color.label` or `color.field`, never
  an `expr`. `size` scales markers to 4–16 px (scatter). Rows with a `label` text are annotated (max 60).
  Above 1500 points scatter/line use WebGL. `facet` is not drawn yet.

### `pca`
```json
{"id": "pca", "type": "plot", "kind": "pca", "title": "PCA", "table": "counts",
 "top_n": 500, "scale": "log1p", "color": {"field": "genotype"}}
```
`table` is a matrix table (see bundle-format.md); PCA uses the `top_n` most variable rows (default 500) after `scale`
(`none` | `log1p`, default `log1p`). `color.field` is a column of `samples.tsv`. Each point is a sample.
Optional `symbol: {"field": <samples.tsv column>, "label"?}` (pca only) sets the marker shape per value of a second
categorical annotation, e.g. `"color": {"field": "genotype"}, "symbol": {"field": "treatment"}`; the legend then has one
entry per colour × shape combination.

### `heatmap`
```json
{"id": "top-genes", "type": "plot", "kind": "heatmap", "title": "Top 30 genes", "table": "counts",
 "rows": {"top_n": 30, "by": "de.padj", "values": []}, "group_by": "genotype", "scale": "row-z"}
```
`rows` picks matrix rows: explicit key `values`, or the `top_n` rows ordered ascending by a column of a linked table
(`<table>.<column>`). Columns are the samples, ordered and annotated by the `samples.tsv` column `group_by`.
`scale`: `none` | `log1p` | `row-z` (default `row-z`).

### `table`
```json
{"id": "genes", "type": "table", "title": "Genes", "table": "de",
 "columns": ["gene_name", "log2FoldChange", "padj"], "sort": [{"field": "padj", "dir": "asc"}], "page_size": 25}
```

### `text`
```json
{"id": "notes", "type": "text", "title": "Notes", "markdown": "Editing sites with Δ > 0.2 ..."}
```

### `widget` (Level 2)
```json
{"id": "editing-lollipop", "type": "widget", "title": "Editing sites per gene",
 "inputs": [{"name": "sites", "sql": "SELECT gene_name, position, delta FROM editing WHERE gene_name = $selected"}],
 "code": "export default function Widget({data, selection, onSelect}) { ... }",
 "language": "tsx"}
```
The code is compiled in the browser and runs in a sandboxed iframe (no network, no parent DOM).
`inputs` are resolved by the backend through the same read-only query path the LLM uses. Runtime details (CSP, postMessage,
layout placement) are in `docs/api.md` → "Level 2 widget runtime".

## Layout

```json
[{"i": "volcano", "x": 0, "y": 0, "w": 6, "h": 9}, {"i": "genes", "x": 6, "y": 0, "w": 6, "h": 9}]
```
Every panel must have exactly one layout item. Users may drag/resize; the result is written back into the spec (and is undoable).

## Patch examples

"Label Gria2 and Cyfip2 in the volcano plot":
```json
[{"op": "replace", "path": "/panels/0/label/values", "value": ["Gria2", "Cyfip2"]}]
```

"Only show significant genes everywhere":
```json
[{"op": "add", "path": "/filters/-", "value": {"id": "sig", "table": "de", "field": "padj", "op": "<=", "value": 0.05, "label": "padj ≤ 0.05", "enabled": true}}]
```

Patches should address panels by index; the backend gives the LLM a compact index (`id → index`) together with the current spec.
