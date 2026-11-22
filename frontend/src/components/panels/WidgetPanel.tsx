import { useEffect, useRef, useState } from 'react';
import type { usePanelData } from '@/lib/usePanelData';
import type { WidgetPanel as WidgetPanelSpec } from '@/lib/types';
import { isFrameMessage, type RenderMessage, type WidgetData } from '@/widget-runtime/protocol';
import { useAppStore } from '@/store';

/** The srcdoc is ~1.4 MB (Plotly basic + React), so it is loaded only when the first widget appears. */
let srcdocPromise: Promise<string> | null = null;
function loadSrcdoc(): Promise<string> {
  srcdocPromise ??= import('@/widget-runtime/srcdoc').then((m) => m.WIDGET_SRCDOC);
  return srcdocPromise;
}

/**
 * Code sent to the iframe. The runtime evaluates CommonJS-style JavaScript (`exports.default = Widget`); compiling the
 * LLM's TSX/JSX with sucrase happens here in T41b – until then the code is sent unchanged, so only plain-JS widgets
 * render and TSX shows a load error inside the panel.
 */
function widgetModuleCode(panel: WidgetPanelSpec): string {
  return panel.code;
}

/**
 * Level 2 widget (T41a): runs the generated code in `<iframe sandbox="allow-scripts">` (opaque origin, no parent DOM)
 * whose srcdoc carries a `default-src 'none'` CSP (no network). Data from `panel-data` and the linked selection are
 * sent by postMessage; the widget's `onSelect(keys)` comes back as a store selection. Errors stay inside the panel.
 */
export function WidgetPanel({ panel, state }: { panel: WidgetPanelSpec; state: ReturnType<typeof usePanelData> }) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [srcdoc, setSrcdoc] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // the iframe window that said `ready` (a remounted iframe gets a new window and must say ready again)
  const [readyWindow, setReadyWindow] = useState<Window | null>(null);
  const [widgetError, setWidgetError] = useState<string | null>(null);
  const selection = useAppStore((s) => s.selection);
  const select = useAppStore((s) => s.select);

  useEffect(() => {
    let cancelled = false;
    loadSrcdoc().then(
      (doc) => !cancelled && setSrcdoc(doc),
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
  const code = widgetModuleCode(panel);

  useEffect(() => {
    const win = frameRef.current?.contentWindow;
    if (!readyWindow || win !== readyWindow || !data) return;
    const message: RenderMessage = { aibex: 1, type: 'render', code, data, selection };
    // the sandboxed frame has an opaque origin, so '*' is the only target that works; the frame checks the source
    readyWindow.postMessage(message, '*');
  }, [readyWindow, data, code, selection]);

  if (loadError) return <p className="text-xs text-destructive">Could not load the widget runtime: {loadError}</p>;

  return (
    <div className="flex h-full flex-col gap-1">
      {srcdoc ? (
        <iframe
          ref={frameRef}
          data-testid={`widget-frame-${panel.id}`}
          title={panel.title || panel.id}
          sandbox="allow-scripts"
          srcDoc={srcdoc}
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
