// TypeScript mirror of the view spec (backend/aibex/spec.py, docs/spec-format.md) and the REST payloads
// (docs/api.md). The backend validates every spec; these types only help the UI read it.

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface Axis {
  field?: string;
  expr?: string;
  label?: string;
}

export interface Color extends Axis {
  palette?: Record<string, string>;
  colorscale?: string;
}

export type Size = Axis;

export interface Label {
  field: string;
  values?: string[];
  top_n?: number;
  by?: string;
}

export interface HeatmapRows {
  top_n?: number;
  by?: string;
  values?: string[];
}

export type PlotKind = 'scatter' | 'line' | 'bar' | 'histogram' | 'box' | 'violin' | 'pca' | 'heatmap';

interface PanelBase {
  id: string;
  title?: string;
  description?: string;
}

export interface PlotPanel extends PanelBase {
  type: 'plot';
  table: string;
  kind: PlotKind;
  x?: Axis;
  y?: Axis;
  color?: Color;
  size?: Size;
  label?: Label;
  facet?: string;
  plotly?: Record<string, JsonValue>;
  top_n?: number;
  scale?: 'none' | 'log1p' | 'row-z';
  rows?: HeatmapRows;
  group_by?: string;
}

export interface SortKey {
  field: string;
  dir?: 'asc' | 'desc';
}

export interface TablePanel extends PanelBase {
  type: 'table';
  table: string;
  columns?: string[] | null;
  sort?: SortKey[];
  page_size?: number;
}

export interface TextPanel extends PanelBase {
  type: 'text';
  markdown?: string;
}

export interface WidgetInput {
  name: string;
  sql: string;
}

export interface WidgetPanel extends PanelBase {
  type: 'widget';
  inputs?: WidgetInput[];
  code: string;
  language?: 'tsx' | 'jsx';
}

export type Panel = PlotPanel | TablePanel | TextPanel | WidgetPanel;

export interface Filter {
  id: string;
  table: string;
  field?: string;
  op?: string;
  value?: JsonValue;
  expr?: string;
  label?: string;
  enabled?: boolean;
}

export interface LayoutItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
  static?: boolean;
}

export interface Spec {
  version: 1;
  title?: string;
  bundle: string;
  theme?: { palette?: string; dark?: boolean };
  filters?: Filter[];
  panels: Panel[];
  layout: LayoutItem[];
  selection?: { key: string; linked?: boolean };
}

// ---- REST payloads (docs/api.md) ----

export interface Health {
  status: string;
  version?: string;
  llm_provider?: string;
  llm_configured?: boolean;
  data_dir_exists?: boolean;
}

/** `GET /bundles` entry; a broken bundle.yaml gives `{id, error}`. */
export interface BundleInfo {
  id: string;
  title?: string;
  modalities?: string[];
  tables?: string[];
  error?: string;
}

export type HistorySource = 'init' | 'user' | 'llm';

export interface HistoryEntry {
  version: number;
  summary: string;
  source: HistorySource;
}

export interface SessionCreated {
  session_id: string;
  spec: Spec;
  version: number;
}

export interface SessionState extends SessionCreated {
  history: HistoryEntry[];
  /** Steps that can be undone / redone from the current version. */
  can_undo: number;
  can_redo: number;
}

export interface SpecVersion {
  spec: Spec;
  version: number;
}

/** SSE events of `POST /sessions/{sid}/chat` (docs/api.md → "Chat events"). */
export type ChatEvent =
  | { type: 'token'; text: string }
  | { type: 'tool'; name: string; status: 'running' | 'ok' | 'error' | string }
  | { type: 'spec'; spec: Spec; version: number; summary?: string }
  | { type: 'error'; message: string }
  | { type: 'done' };

/** RFC 6902 JSON Patch operation. */
export type PatchOp =
  | { op: 'add' | 'replace' | 'test'; path: string; value: JsonValue }
  | { op: 'remove'; path: string }
  | { op: 'move' | 'copy'; from: string; path: string };

export interface PanelData {
  columns: string[];
  rows: JsonValue[][];
  truncated: boolean;
  x_label?: string;
  y_label?: string;
}
