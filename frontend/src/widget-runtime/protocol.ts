// postMessage protocol between the dashboard (parent) and a Level 2 widget iframe (docs/api.md → "Level 2 widget
// runtime"). The iframe has an opaque origin (sandbox without allow-same-origin), so both sides check the message
// *source* window instead of the origin, and every message carries `aibex: 1` plus a `type`.

/** Widget data as returned by `panel-data` for a widget panel: one `{columns, rows, truncated}` per input. */
export interface WidgetData {
  inputs: Record<string, { columns: string[]; rows: unknown[][]; truncated?: boolean }>;
}

/** Parent → iframe: (re)render. `code` is plain JavaScript in CommonJS form (`exports.default = Widget`). */
export interface RenderMessage {
  aibex: 1;
  type: 'render';
  code: string;
  data: WidgetData;
  selection: string[];
  /**
   * Dashboard theme (T53). The frame sets `data-theme` on its <html> and fills in Plotly layout keys the widget leaves
   * unset (`plotly` = themed defaults: transparent background, ink, grid, colorway). Optional for older parents.
   */
  theme?: { mode: 'light' | 'dark'; plotly: Record<string, unknown> };
}

/** Iframe → parent. */
export type FrameMessage =
  | { aibex: 1; type: 'ready' }
  | { aibex: 1; type: 'rendered' }
  | { aibex: 1; type: 'select'; keys: string[] }
  | { aibex: 1; type: 'error'; phase: 'load' | 'render'; message: string };

export function isFrameMessage(value: unknown): value is FrameMessage {
  if (!value || typeof value !== 'object') return false;
  const m = value as { aibex?: unknown; type?: unknown };
  return m.aibex === 1 && typeof m.type === 'string';
}
