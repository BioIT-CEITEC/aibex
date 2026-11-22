// Runtime inside the sandboxed widget iframe. Bundled on its own (IIFE, see widget-runtime-plugin.ts) and inlined into
// the iframe's srcdoc next to the Plotly basic bundle – the iframe's CSP (`default-src 'none'`) forbids loading
// anything, so nothing here may fetch. Exposes `React` / `ReactDOM` globals for widget code, waits for a `render`
// message from the parent, evaluates the widget module and renders `Widget({data, selection, onSelect})`.
//
// Evaluation uses an inline <script> element (allowed by `script-src 'unsafe-inline'`); `eval`/`new Function` stay
// blocked because the CSP has no 'unsafe-eval'.
import React, { Component, type ComponentType, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import * as ReactDOM from 'react-dom';
import type { FrameMessage, RenderMessage, WidgetData } from './protocol';

interface WidgetProps {
  data: WidgetData;
  selection: string[];
  onSelect: (keys: unknown[]) => void;
}

type Define = (factory: (exports: Record<string, unknown>, module: { exports: Record<string, unknown> }, require: (name: string) => unknown) => void) => void;

const w = window as unknown as Record<string, unknown> & { __aibexDefine?: Define };
w.React = React;
w.ReactDOM = ReactDOM;

type Outgoing = FrameMessage extends infer M ? (M extends FrameMessage ? Omit<M, 'aibex'> : never) : never;

function post(message: Outgoing) {
  window.parent.postMessage({ aibex: 1, ...message }, '*');
}

function errorText(e: unknown): string {
  if (e instanceof Error) return `${e.name}: ${e.message}`;
  return String(e);
}

const MODULES: Record<string, () => unknown> = {
  react: () => React,
  'react-dom': () => ReactDOM,
  'react-dom/client': () => ({ createRoot }),
  'plotly.js': () => w.Plotly,
  'plotly.js-dist-min': () => w.Plotly,
  'plotly.js-basic-dist-min': () => w.Plotly,
};

function requireModule(name: string): unknown {
  const get = MODULES[name];
  if (!get) throw new Error(`Widgets cannot import "${name}" – use the React and Plotly globals`);
  return get();
}

/** Evaluate CommonJS-style widget code; returns the default export or throws the load error. */
function loadWidget(code: string): ComponentType<WidgetProps> {
  let defined: Record<string, unknown> | null = null;
  let loadError: unknown = null;
  const onError = (event: ErrorEvent) => {
    loadError = event.error ?? event.message;
    event.preventDefault();
  };
  w.__aibexDefine = (factory) => {
    const module = { exports: {} as Record<string, unknown> };
    try {
      factory(module.exports, module, requireModule);
      defined = module.exports;
    } catch (e) {
      loadError = e;
    }
  };
  window.addEventListener('error', onError);
  const script = document.createElement('script');
  // a newline before the closing brace so a trailing `// comment` in the code cannot swallow it
  script.textContent = `window.__aibexDefine(function (exports, module, require) {\n${code}\n});`;
  document.head.appendChild(script);
  script.remove();
  window.removeEventListener('error', onError);
  delete w.__aibexDefine;

  if (loadError) throw loadError instanceof Error ? loadError : new Error(String(loadError));
  if (!defined) throw new Error('The widget code could not be evaluated (syntax error?)');
  const exports = defined as Record<string, unknown>;
  const widget = exports.default ?? exports.Widget ?? (typeof exports === 'function' ? exports : undefined);
  if (typeof widget !== 'function') throw new Error('The widget code must export a default function component');
  return widget as ComponentType<WidgetProps>;
}

// No JSX in this file: the nested runtime build (widget-runtime-plugin.ts) has no React plugin, and the dev server's
// environment would otherwise make it emit the development JSX runtime.
const h = React.createElement;

function errorBox(message: string) {
  return h('pre', { className: 'aibex-error' }, `Widget error: ${message}`);
}

class Boundary extends Component<{ children?: ReactNode; resetKey: unknown }, { error: string | null }> {
  state: { error: string | null } = { error: null };

  static getDerivedStateFromError(e: unknown) {
    return { error: errorText(e) };
  }

  componentDidCatch(e: unknown) {
    post({ type: 'error', phase: 'render', message: errorText(e) });
  }

  componentDidUpdate(prev: { resetKey: unknown }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) return errorBox(this.state.error);
    return this.props.children;
  }
}

// Theme (T53): the parent sends themed Plotly defaults; every Plotly.newPlot/react/plot call from widget code gets them
// underneath its own layout, so a widget that sets its own colours keeps them and one that does not matches the theme.
let plotlyDefaults: Record<string, unknown> = {};

function isPlain(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function underlay(base: Record<string, unknown>, over: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(over)) out[k] = isPlain(v) && isPlain(out[k]) ? underlay(out[k] as Record<string, unknown>, v) : v;
  return out;
}

function themePlotly() {
  const plotly = w.Plotly as Record<string, unknown> | undefined;
  if (!plotly || plotly.__aibexThemed) return;
  for (const name of ['newPlot', 'react', 'plot']) {
    const original = plotly[name];
    if (typeof original !== 'function') continue;
    plotly[name] = function (this: unknown, gd: unknown, data: unknown, layout: unknown, ...rest: unknown[]) {
      // the figure form `Plotly.newPlot(gd, {data, layout, config})` is left alone apart from its layout
      if (isPlain(data) && !Array.isArray(data)) {
        const fig = data as Record<string, unknown>;
        const lay = isPlain(fig.layout) ? fig.layout : {};
        return original.call(this, gd, { ...fig, layout: underlay(plotlyDefaults, lay) }, layout, ...rest);
      }
      return original.call(this, gd, data, underlay(plotlyDefaults, isPlain(layout) ? layout : {}), ...rest);
    };
  }
  plotly.__aibexThemed = true;
}

function applyTheme(theme: RenderMessage['theme']) {
  const mode = theme?.mode === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = mode;
  plotlyDefaults = theme && isPlain(theme.plotly) ? theme.plotly : {};
  themePlotly();
}

let root: Root | null = null;
let cached: { code: string; widget: ComponentType<WidgetProps> | null; error: string | null } | null = null;

const onSelect = (keys: unknown[]) => {
  const list = Array.isArray(keys) ? keys : [keys];
  post({ type: 'select', keys: list.filter((k) => k !== null && k !== undefined).map(String) });
};

function render(message: RenderMessage) {
  applyTheme(message.theme);
  if (!cached || cached.code !== message.code) {
    try {
      cached = { code: message.code, widget: loadWidget(message.code), error: null };
    } catch (e) {
      cached = { code: message.code, widget: null, error: errorText(e) };
    }
  }
  root ??= createRoot(document.getElementById('root')!);
  if (!cached.widget) {
    post({ type: 'error', phase: 'load', message: cached.error ?? 'unknown error' });
    root.render(errorBox(cached.error ?? 'unknown error'));
    return;
  }
  const widget = h(cached.widget, { data: message.data, selection: message.selection, onSelect });
  root.render(h(Boundary, { resetKey: message }, widget));
  post({ type: 'rendered' });
}

window.addEventListener('message', (event: MessageEvent) => {
  if (event.source !== window.parent) return;
  const m = event.data as Partial<RenderMessage> | null;
  if (!m || m.aibex !== 1 || m.type !== 'render' || typeof m.code !== 'string') return;
  render({
    aibex: 1,
    type: 'render',
    code: m.code,
    data: m.data ?? { inputs: {} },
    selection: Array.isArray(m.selection) ? m.selection : [],
    theme: m.theme,
  });
});

post({ type: 'ready' });
