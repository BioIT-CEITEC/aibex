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
  "color": {"field": "significant", "palette": {"true": "#d62728", "false": "#bbbbbb"}},
  "size": null,
  "label": {"field": "gene_name", "values": ["Gria2", "Cyfip2"], "top_n": 10, "by": "padj"},
  "facet": null,
  "plotly": {}
}
```
- `kind`: `scatter`, `bar`, `box`, `violin`, `histogram`, `heatmap`, `line`, `pca` (computed server-side from a count/matrix table).
- An axis is either `{"field": ...}` or `{"expr": ...}`. `expr` is a restricted DuckDB SQL expression over the table's columns (validated server-side; no subqueries, no functions outside an allow-list: log, log2, log10, abs, ln, sqrt, round, least, greatest, coalesce, case).
- `plotly` holds optional raw Plotly layout/trace overrides (escape hatch; validated to be plain JSON).

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
`inputs` are resolved by the backend through the same read-only query path the LLM uses.

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
