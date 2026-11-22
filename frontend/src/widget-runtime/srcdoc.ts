// The widget iframe document (docs/api.md → "Level 2 widget runtime"): a CSP that blocks all network access, the
// Plotly basic bundle and the React runtime inlined as scripts, and a #root element. Built once per page load and
// shared by all widget iframes. Loaded lazily (dynamic import) so the ~1.4 MB stays out of the main bundle until a
// spec actually contains a widget.
import plotly from 'plotly.js-basic-dist-min/plotly-basic.min.js?raw';
import runtime from 'virtual:aibex-widget-runtime';

export const WIDGET_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:";

const STYLE = `
html, body, #root { margin: 0; height: 100%; }
body { font: 12px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color: #18181b; background: transparent;
  overflow: auto; }
.aibex-error { margin: 0; padding: 8px; color: #b91c1c; white-space: pre-wrap; font: 12px/1.4 ui-monospace, monospace; }
`;

/** A script body must not contain `</script` (closes the element early) or `<!--` (HTML script-data escape state). */
function inlineScript(code: string): string {
  return `<script>${code.replace(/<\/(script)/gi, '<\\/$1').replace(/<!--/g, '<\\!--')}</script>`;
}

export const WIDGET_SRCDOC = [
  '<!doctype html><html><head><meta charset="utf-8">',
  `<meta http-equiv="Content-Security-Policy" content="${WIDGET_CSP}">`,
  `<style>${STYLE}</style>`,
  inlineScript(plotly),
  '</head><body><div id="root"></div>',
  inlineScript(runtime),
  '</body></html>',
].join('');
