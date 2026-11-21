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

export function buildFigure(panel: PlotPanel, data: PanelData): Figure {
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
