// Builds a Plotly figure (traces + layout) from a plot panel spec and its panel-data (docs/api.md → "Panel data
// shape"). Pure function, no Plotly import, so it stays cheap and testable. Column names of the dataset are never
// hard-coded: panel-data returns the generic columns x / y / color / size / label / facet plus the table key.
import type { JsonValue, PanelData, PlotPanel } from './types';

export type Trace = Record<string, unknown>;
export interface Figure {
  data: Trace[];
  layout: Record<string, unknown>;
}

/** Above this many points scatter/line use WebGL (`scattergl`) so big DE tables stay responsive. */
const WEBGL_THRESHOLD = 1500;
/** Upper bound for text annotations (labels); more would be unreadable anyway. */
export const MAX_ANNOTATIONS = 60;
/** Fallback categorical colours (Plotly/D3 category10) when the spec has no palette entry. */
const COLORWAY = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
/** Generic panel-data columns; anything else (except `facet`/`sample`) is the table key used for selection. */
const GENERIC = new Set(['x', 'y', 'color', 'size', 'label', 'facet']);

type Row = JsonValue[];

function axisTitle(axis: PlotPanel['x'], fallback?: string): string | undefined {
  return axis?.label || axis?.field || axis?.expr || fallback;
}

function isNumericColumn(rows: Row[], i: number): boolean {
  let seen = 0;
  for (const r of rows) {
    const v = r[i];
    if (v === null || v === undefined) continue;
    if (typeof v !== 'number') return false;
    if (++seen > 50) break;
  }
  return seen > 0;
}

function plain(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Deep merge of plain objects (arrays and scalars of `over` replace). Returns a new object. */
export function deepMerge(base: Record<string, unknown>, over: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(over)) {
    out[k] = plain(v) && plain(out[k]) ? deepMerge(out[k] as Record<string, unknown>, v) : v;
  }
  return out;
}

/**
 * Applies the spec's `plotly` escape hatch: `plotly.layout` and every other top-level key merge into the layout,
 * `plotly.trace` merges into every trace (documented in docs/spec-format.md).
 */
export function applyOverrides(fig: Figure, overrides: PlotPanel['plotly']): Figure {
  if (!overrides || !plain(overrides)) return fig;
  const { layout, trace, ...rest } = overrides as Record<string, unknown>;
  let lay = fig.layout;
  if (plain(layout)) lay = deepMerge(lay, layout);
  if (Object.keys(rest).length) lay = deepMerge(lay, rest);
  const data = plain(trace) ? fig.data.map((t) => deepMerge(t, trace)) : fig.data;
  return { data, layout: lay };
}

/** Splits rows by a category value, keeping first-appearance order (null → "n/a"). */
function groupBy(rows: Row[], i: number): Map<string, Row[]> {
  const groups = new Map<string, Row[]>();
  for (const r of rows) {
    const v = r[i];
    const k = v === null || v === undefined ? 'n/a' : String(v);
    const g = groups.get(k);
    if (g) g.push(r);
    else groups.set(k, [r]);
  }
  return groups;
}

function scaleSizes(values: JsonValue[]): number[] {
  const nums = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!nums.length) return values.map(() => 6);
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  return values.map((v) => (typeof v === 'number' && Number.isFinite(v) ? (hi > lo ? 4 + (12 * (v - lo)) / (hi - lo) : 8) : 4));
}

/** Diverging scale for centred values (row z-scores): blue – neutral grey – red, never a hue at the midpoint. */
const DIVERGING: [number, string][] = [
  [0, '#2b59c3'],
  [0.25, '#8da4dc'],
  [0.5, '#e6e6e6'],
  [0.75, '#e39a8a'],
  [1, '#c0392b'],
];
/** Sequential single-hue scale (light → dark) for unscaled / log values. */
const SEQUENTIAL: [number, string][] = [
  [0, '#f2f5fb'],
  [0.5, '#7f9fd6'],
  [1, '#1d3f8f'],
];

function baseLayout(xTitle?: string, yTitle?: string): Record<string, unknown> {
  return {
    autosize: true,
    margin: { l: 56, r: 16, t: 12, b: 48 },
    font: { size: 11 },
    xaxis: { title: { text: xTitle }, automargin: true, zeroline: false },
    yaxis: { title: { text: yTitle }, automargin: true, zeroline: false },
    hovermode: 'closest',
    showlegend: false,
    colorway: COLORWAY,
  };
}

/**
 * PCA of samples: panel-data has `x` (PC1), `y` (PC2), `sample` and the samples.tsv annotation columns; the spec's
 * `color.field` names one of those annotation columns. Points carry the sample name as text and in the hover.
 */
export function buildPcaFigure(panel: PlotPanel, data: PanelData): Figure {
  const cols = data.columns;
  const xi = cols.indexOf('x');
  const yi = cols.indexOf('y');
  const sampleIdx = cols.indexOf('sample');
  const colourField = panel.color?.field;
  const ci = colourField ? cols.indexOf(colourField) : -1;
  const annot = cols.map((c, i) => [c, i] as const).filter(([c]) => !['x', 'y', 'sample'].includes(c));
  const rows = data.rows;
  const layout = baseLayout(data.x_label ?? 'PC1', data.y_label ?? 'PC2');
  layout.legend = {
    orientation: 'h',
    x: 1,
    xanchor: 'right',
    y: 1.01,
    yanchor: 'bottom',
    title: { text: panel.color?.label || colourField || '' },
  };
  const hover =
    '<b>%{customdata[0]}</b>' +
    annot.map(([c], k) => `<br>${c}: %{customdata[${k + 1}]}`).join('') +
    '<br>PC1: %{x:.2f}<br>PC2: %{y:.2f}<extra></extra>';
  const trace = (rs: Row[]): Trace => ({
    type: 'scatter',
    mode: rs.length <= 40 ? 'markers+text' : 'markers',
    x: rs.map((r) => r[xi]),
    y: rs.map((r) => r[yi]),
    text: rs.map((r) => (sampleIdx >= 0 ? r[sampleIdx] : '')),
    textposition: 'top center',
    textfont: { size: 10, color: '#444' },
    customdata: rs.map((r) => [sampleIdx >= 0 ? r[sampleIdx] : '', ...annot.map(([, i]) => r[i])]),
    hovertemplate: hover,
    marker: { size: 10, opacity: 0.9, line: { width: 1, color: '#fff' } },
    cliponaxis: false,
  });

  const traces: Trace[] = [];
  if (ci >= 0 && isNumericColumn(rows, ci)) {
    const t = trace(rows);
    t.name = '';
    t.marker = {
      ...(t.marker as object),
      color: rows.map((r) => r[ci]),
      colorscale: panel.color?.colorscale ?? 'Viridis',
      showscale: true,
      colorbar: { title: { text: panel.color?.label || colourField }, thickness: 12 },
    };
    traces.push(t);
  } else if (ci >= 0) {
    const palette = panel.color?.palette ?? {};
    let n = 0;
    for (const [name, rs] of groupBy(rows, ci)) {
      const t = trace(rs);
      t.name = name;
      t.marker = { ...(t.marker as object), color: palette[name] ?? COLORWAY[n++ % COLORWAY.length] };
      traces.push(t);
    }
    layout.showlegend = true;
    layout.margin = { l: 56, r: 16, t: 28, b: 48 };
  } else {
    const t = trace(rows);
    t.name = '';
    traces.push(t);
  }
  return applyOverrides({ data: traces, layout }, panel.plotly);
}

/**
 * Heatmap: panel-data is long format `row, column, value, group` (rows in display order, columns grouped by
 * `group_by`). Pivoted to a matrix; first row on top. Row z-scores get a diverging scale centred at 0, other scales
 * a sequential one. Sample groups are drawn as a coloured band above the columns with the group name.
 */
export function buildHeatmapFigure(panel: PlotPanel, data: PanelData): Figure {
  const cols = data.columns;
  const ri = cols.indexOf('row');
  const coli = cols.indexOf('column');
  const vi = cols.indexOf('value');
  const gi = cols.indexOf('group');
  const rowNames: string[] = [];
  const colNames: string[] = [];
  const rowIx = new Map<string, number>();
  const colIx = new Map<string, number>();
  const colGroup = new Map<string, string | null>();
  for (const r of data.rows) {
    const rn = String(r[ri]);
    const cn = String(r[coli]);
    if (!rowIx.has(rn)) rowIx.set(rn, rowNames.push(rn) - 1);
    if (!colIx.has(cn)) {
      colIx.set(cn, colNames.push(cn) - 1);
      const g = gi >= 0 ? r[gi] : null;
      colGroup.set(cn, g === null || g === undefined ? null : String(g));
    }
  }
  const z: (number | null)[][] = rowNames.map(() => colNames.map(() => null));
  for (const r of data.rows) {
    const v = r[vi];
    z[rowIx.get(String(r[ri]))!][colIx.get(String(r[coli]))!] = typeof v === 'number' && Number.isFinite(v) ? v : null;
  }

  const centred = panel.scale === 'row-z';
  const valueName = centred ? 'row z-score' : panel.scale === 'log1p' ? 'log1p(value)' : 'value';
  const trace: Trace = {
    type: 'heatmap',
    x: colNames,
    y: rowNames,
    z,
    colorscale: panel.color?.colorscale ?? (centred ? DIVERGING : SEQUENTIAL),
    ...(centred ? { zmid: 0 } : {}),
    xgap: 1,
    ygap: 1,
    hoverongaps: false,
    colorbar: { title: { text: valueName, side: 'right' }, thickness: 12, len: 0.9 },
    hovertemplate: `%{y}<br>%{x}<br>${valueName}: %{z:.2f}<extra></extra>`,
  };
  const layout = baseLayout();
  layout.xaxis = { type: 'category', tickangle: -45, automargin: true, showgrid: false, ticks: '' };
  layout.yaxis = {
    type: 'category',
    autorange: 'reversed',
    automargin: true,
    showgrid: false,
    ticks: '',
    tickfont: { size: rowNames.length > 40 ? 8 : 10 },
  };

  // group band: one coloured strip + name per contiguous run of columns with the same group
  const runs: { name: string; start: number; end: number }[] = [];
  colNames.forEach((c, k) => {
    const g = colGroup.get(c);
    if (g === null || g === undefined) return;
    const last = runs[runs.length - 1];
    if (last && last.name === g && last.end === k - 1) last.end = k;
    else runs.push({ name: g, start: k, end: k });
  });
  if (runs.length) {
    const palette = panel.color?.palette ?? {};
    const colourOf = new Map<string, string>();
    for (const run of runs) {
      if (!colourOf.has(run.name)) colourOf.set(run.name, palette[run.name] ?? COLORWAY[colourOf.size % COLORWAY.length]);
    }
    layout.margin = { l: 56, r: 16, t: 30, b: 48 };
    layout.shapes = runs.map((run) => ({
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: run.start - 0.5,
      x1: run.end + 0.5,
      y0: 1.01,
      y1: 1.05,
      fillcolor: colourOf.get(run.name),
      line: { width: 1, color: '#fff' },
    }));
    layout.annotations = runs.map((run) => ({
      xref: 'x',
      yref: 'paper',
      x: (run.start + run.end) / 2,
      y: 1.05,
      yanchor: 'bottom',
      text: run.name,
      showarrow: false,
      font: { size: 10, color: '#333' },
    }));
  }
  return applyOverrides({ data: [trace], layout }, panel.plotly);
}

export function buildFigure(panel: PlotPanel, data: PanelData): Figure {
  if (panel.kind === 'pca') return buildPcaFigure(panel, data);
  if (panel.kind === 'heatmap') return buildHeatmapFigure(panel, data);
  const cols = data.columns;
  const ix = (name: string) => cols.indexOf(name);
  const xi = ix('x');
  const yi = ix('y');
  const ci = ix('color');
  const si = ix('size');
  const li = ix('label');
  const keyIdx = cols.findIndex((c) => !GENERIC.has(c));
  const rows = data.rows;
  const kind = panel.kind;
  const col = (rs: Row[], i: number) => (i < 0 ? undefined : rs.map((r) => r[i]));

  const xTitle = data.x_label ?? axisTitle(panel.x);
  const yTitle = data.y_label ?? axisTitle(panel.y, kind === 'histogram' ? 'count' : undefined);
  const layout: Record<string, unknown> = {
    autosize: true,
    margin: { l: 56, r: 16, t: 12, b: 48 },
    font: { size: 11 },
    xaxis: { title: { text: xTitle }, automargin: true, zeroline: false },
    yaxis: { title: { text: yTitle }, automargin: true, zeroline: false },
    // horizontal legend above the plot; titled only by a readable name (a raw `expr` would be noise)
    legend: {
      orientation: 'h',
      x: 1,
      xanchor: 'right',
      y: 1.01,
      yanchor: 'bottom',
      title: { text: panel.color?.label || panel.color?.field || '' },
    },
    hovermode: 'closest',
    showlegend: false,
    colorway: COLORWAY,
  };

  // --- base trace per kind (one trace; colour may split it into groups below)
  const big = rows.length > WEBGL_THRESHOLD;
  const base = (rs: Row[]): Trace => {
    const keys = col(rs, keyIdx);
    const common: Trace = keys ? { customdata: keys } : {};
    switch (kind) {
      case 'scatter':
        return { ...common, type: big ? 'scattergl' : 'scatter', mode: 'markers', x: col(rs, xi), y: col(rs, yi), marker: { size: 6, opacity: 0.8 } };
      case 'line': {
        const sorted = xi >= 0 ? [...rs].sort((a, b) => cmp(a[xi], b[xi])) : rs;
        const k = col(sorted, keyIdx);
        return { ...(k ? { customdata: k } : {}), type: big ? 'scattergl' : 'scatter', mode: 'lines+markers', x: col(sorted, xi), y: col(sorted, yi), marker: { size: 4 } };
      }
      case 'bar':
        return { ...common, type: 'bar', x: col(rs, xi), y: col(rs, yi) };
      case 'histogram':
        return xi >= 0 ? { type: 'histogram', x: col(rs, xi), opacity: 0.75 } : { type: 'histogram', y: col(rs, yi), opacity: 0.75 };
      case 'box':
        return { type: 'box', x: col(rs, xi), y: col(rs, yi), boxpoints: rs.length <= 200 ? 'all' : 'outliers', jitter: 0.3 };
      case 'violin':
        return { type: 'violin', x: col(rs, xi), y: col(rs, yi), box: { visible: true }, meanline: { visible: true }, points: false };
      default:
        return { type: 'scatter', mode: 'markers', x: col(rs, xi), y: col(rs, yi) };
    }
  };

  const traces: Trace[] = [];
  const hoverKey = keyIdx >= 0 ? `<br>${cols[keyIdx]}: %{customdata}` : '';
  const pointKinds = kind === 'scatter' || kind === 'line' || kind === 'bar';
  const hovertemplate = pointKinds ? `x: %{x}<br>y: %{y}${hoverKey}<extra>%{fullData.name}</extra>` : undefined;

  if (ci >= 0 && isNumericColumn(rows, ci) && (kind === 'scatter' || kind === 'line')) {
    // continuous colour → one trace with a colour scale and colour bar
    const t = base(rows);
    const marker = (t.marker as Record<string, unknown>) ?? {};
    t.marker = {
      ...marker,
      color: col(rows, ci),
      colorscale: panel.color?.colorscale ?? 'Viridis',
      showscale: true,
      colorbar: { title: { text: axisTitle(panel.color) }, thickness: 12 },
    };
    t.name = '';
    if (hovertemplate) t.hovertemplate = hovertemplate;
    traces.push(t);
  } else if (ci >= 0) {
    // categorical colour → one trace per value, colours from the spec palette (case-sensitive), else the colorway
    const palette = panel.color?.palette ?? {};
    let n = 0;
    for (const [name, rs] of groupBy(rows, ci)) {
      const colour = palette[name] ?? COLORWAY[n++ % COLORWAY.length];
      const t = base(rs);
      t.name = name;
      if (hovertemplate) t.hovertemplate = hovertemplate;
      t.marker = { ...((t.marker as object) ?? {}), color: colour };
      if (kind === 'line' || kind === 'violin') t.line = { color: colour };
      traces.push(t);
    }
    layout.showlegend = true;
    layout.margin = { l: 56, r: 16, t: 28, b: 48 };
    if (kind === 'histogram') layout.barmode = 'overlay';
    if (kind === 'box' || kind === 'violin') layout[kind === 'box' ? 'boxmode' : 'violinmode'] = 'group';
  } else {
    const t = base(rows);
    t.name = '';
    if (hovertemplate) t.hovertemplate = hovertemplate;
    traces.push(t);
  }

  // size → marker size per point (scatter only; applies to whichever traces carry the points)
  if (si >= 0 && kind === 'scatter') {
    const sizeOf = new Map<Row, number>();
    const scaled = scaleSizes(rows.map((r) => r[si]));
    rows.forEach((r, k) => sizeOf.set(r, scaled[k]));
    if (traces.length === 1 && (ci < 0 || isNumericColumn(rows, ci))) {
      (traces[0].marker as Record<string, unknown>).size = scaled;
    } else {
      const groups = [...groupBy(rows, ci).values()];
      traces.forEach((t, k) => {
        (t.marker as Record<string, unknown>).size = (groups[k] ?? []).map((r) => sizeOf.get(r) ?? 6);
      });
    }
  }

  // labels → annotations with arrows at the labelled points (rows with a non-null label come first)
  if (li >= 0 && xi >= 0 && yi >= 0 && pointKinds) {
    const annotations: Record<string, unknown>[] = [];
    for (const r of rows) {
      if (annotations.length >= MAX_ANNOTATIONS) break;
      const text = r[li];
      if (text === null || text === undefined || text === '') continue;
      if (r[xi] === null || r[yi] === null) continue;
      annotations.push({
        x: r[xi],
        y: r[yi],
        text: String(text),
        showarrow: true,
        arrowhead: 0,
        arrowwidth: 1,
        arrowcolor: '#555',
        // staggered offsets so labels of nearby points overlap less
        ax: annotations.length % 2 ? -20 : 20,
        ay: -18 - (annotations.length % 3) * 12,
        font: { size: 11, color: '#111' },
        bgcolor: 'rgba(255,255,255,0.75)',
        borderpad: 1,
      });
    }
    if (annotations.length) layout.annotations = annotations;
  }

  return applyOverrides({ data: traces, layout }, panel.plotly);
}

function cmp(a: JsonValue, b: JsonValue): number {
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}
