import { useEffect, useMemo, useRef, useState } from 'react';
import { modeOf, plotlyChrome } from '@/lib/palette';
import type { usePanelData } from '@/lib/usePanelData';
import type { WidgetPanel as WidgetPanelSpec } from '@/lib/types';
import type { compileWidget } from '@/widget-runtime/compile';
import { isFrameMessage, type RenderMessage, type WidgetData } from '@/widget-runtime/protocol';
import { useAppStore } from '@/store';

interface WidgetRuntime {
  srcdoc: string;
  compile: typeof compileWidget;
}

/**
 * The srcdoc (~1.4 MB, Plotly basic + React) and the TSX compiler (sucrase) are loaded only when the first widget
 * appears, so dashboards without widgets do not pay for them.
 */
let runtimePromise: Promise<WidgetRuntime> | null = null;
function loadRuntime(): Promise<WidgetRuntime> {
  runtimePromise ??= Promise.all([import('@/widget-runtime/srcdoc'), import('@/widget-runtime/compile')]).then(
    ([s, c]) => ({ srcdoc: s.WIDGET_SRCDOC, compile: c.compileWidget }),
  );
  return runtimePromise;
}

/**
 * Code sent to the iframe: the panel's TSX/JSX compiled by sucrase to CommonJS (`exports.default = Widget`). A compile
 * error becomes a module that throws it, so the frame shows it like any load error (and reports it back).
 */
function widgetModuleCode(panel: WidgetPanelSpec, compile: typeof compileWidget): string {
  const result = compile(panel.code, panel.language ?? 'tsx');
  return result.ok ? result.code : `throw new Error(${JSON.stringify(result.error)});`;
}

/**
 * Level 2 widget (T41a/b): runs the generated code in `<iframe sandbox="allow-scripts">` (opaque origin, no parent DOM)
 * whose srcdoc carries a `default-src 'none'` CSP (no network). Data from `panel-data` and the linked selection are
 * sent by postMessage; the widget's `onSelect(keys)` comes back as a store selection. Errors stay inside the panel.
 */
export function WidgetPanel({ panel, state }: { panel: WidgetPanelSpec; state: ReturnType<typeof usePanelData> }) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [runtime, setRuntime] = useState<WidgetRuntime | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // the iframe window that said `ready` (a remounted iframe gets a new window and must say ready again)
  const [readyWindow, setReadyWindow] = useState<Window | null>(null);
  const [widgetError, setWidgetError] = useState<string | null>(null);
  const selection = useAppStore((s) => s.selection);
  const select = useAppStore((s) => s.select);
  const mode = useAppStore((s) => modeOf(s.spec?.theme));
  const theme = useMemo(() => ({ mode, plotly: plotlyChrome(mode) }), [mode]);

  useEffect(() => {
    let cancelled = false;
    loadRuntime().then(
      (rt) => !cancelled && setRuntime(rt),
      (e: unknown) => !cancelled && setLoadError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const win = frameRef.current?.contentWindow;
      if (!win || event.source !== win || !isFrameMessage(event.data)) return;
      const m = event.data;
      if (m.type === 'ready') setReadyWindow(win);
      else if (m.type === 'rendered') setWidgetError(null);
      else if (m.type === 'error') setWidgetError(m.message);
      else if (m.type === 'select' && Array.isArray(m.keys)) select(m.keys.map(String));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [select]);

  const data = state.data as unknown as WidgetData | null;
  const code = useMemo(() => (runtime ? widgetModuleCode(panel, runtime.compile) : null), [runtime, panel]);

  useEffect(() => {
    const win = frameRef.current?.contentWindow;
    if (!readyWindow || win !== readyWindow || !data || code === null) return;
    const message: RenderMessage = { aibex: 1, type: 'render', code, data, selection, theme };
    // the sandboxed frame has an opaque origin, so '*' is the only target that works; the frame checks the source
    readyWindow.postMessage(message, '*');
  }, [readyWindow, data, code, selection, theme]);

  if (loadError) return <p className="text-xs text-destructive">Could not load the widget runtime: {loadError}</p>;

  return (
    <div className="flex h-full flex-col gap-1">
      {runtime ? (
        <iframe
          ref={frameRef}
          data-testid={`widget-frame-${panel.id}`}
          title={panel.title || panel.id}
          sandbox="allow-scripts"
          srcDoc={runtime.srcdoc}
          // backup for a missed `ready`: the runtime script ends the body, so its listener exists by `load`
          onLoad={() => setReadyWindow(frameRef.current?.contentWindow ?? null)}
          className="min-h-0 w-full flex-1 border-0"
        />
      ) : (
        <p className="text-xs text-muted-foreground">loading widget runtime…</p>
      )}
      {widgetError && (
        <p data-testid={`widget-error-${panel.id}`} role="alert" className="truncate text-xs text-destructive" title={widgetError}>
          Widget error: {widgetError}
        </p>
      )}
    </div>
  );
}
