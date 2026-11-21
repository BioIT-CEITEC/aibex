import { useEffect, useRef, useState } from 'react';
import type { Config, Data, Layout } from 'plotly.js-dist-min';
import type { Figure } from '@/lib/plotFigure';

type PlotlyModule = typeof import('plotly.js-dist-min');

// Plotly (~4.5 MB minified) is loaded once, on first use, so the app shell appears before it arrives.
let plotlyPromise: Promise<PlotlyModule> | null = null;
function loadPlotly(): Promise<PlotlyModule> {
  plotlyPromise ??= import('plotly.js-dist-min').then((m) => ((m as unknown as { default?: PlotlyModule }).default ?? m) as PlotlyModule);
  return plotlyPromise;
}

const CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['sendDataToCloud', 'select2d', 'lasso2d'] };
/** Plots that take part in linked selection keep the box/lasso select tools. */
const SELECT_CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['sendDataToCloud'] };

/** A clicked or box/lasso-selected point as Plotly reports it (only the fields we use). */
export interface PlotPoint {
  x?: unknown;
  y?: unknown;
  customdata?: unknown;
}

/** `click` = plain click, `toggle` = shift/ctrl/cmd-click, `select` = box/lasso, `clear` = deselect (double-click). */
export type PointsEvent = 'click' | 'toggle' | 'select' | 'clear';

interface PlotlyEventData {
  points?: PlotPoint[];
  event?: MouseEvent;
}
type Emitter = { on: (name: string, cb: (e?: PlotlyEventData) => void) => void };

/**
 * Thin React wrapper around `Plotly.react` (instead of react-plotly.js, whose peer dependency drags in the full
 * plotly.js source tree). Redraws when the figure changes, follows the container size, purges on unmount.
 * `onPoints` receives clicks and box/lasso selections (linked selection, T17e).
 */
export function PlotlyChart({
  figure,
  testId,
  onPoints,
}: {
  figure: Figure;
  testId?: string;
  onPoints?: (points: PlotPoint[], how: PointsEvent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const handler = useRef(onPoints);
  const bound = useRef(false);
  const selectable = !!onPoints;

  useEffect(() => {
    handler.current = onPoints;
  }, [onPoints]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    loadPlotly()
      .then((Plotly) => {
        if (cancelled) return;
        const config = selectable ? SELECT_CONFIG : CONFIG;
        return Plotly.react(el, figure.data as Data[], figure.layout as Partial<Layout>, config as Partial<Config>);
      })
      .then(
        () => {
          if (cancelled) return;
          setError(null);
          if (bound.current) return;
          // handlers survive Plotly.react (they live on the graph div) and are dropped by purge on unmount
          bound.current = true;
          const gd = el as unknown as Emitter;
          gd.on('plotly_click', (e) => {
            const toggle = !!(e?.event && (e.event.shiftKey || e.event.ctrlKey || e.event.metaKey));
            handler.current?.(e?.points ?? [], toggle ? 'toggle' : 'click');
          });
          gd.on('plotly_selected', (e) => {
            // undefined event data = the selection was cleared (click outside / double-click)
            if (e) handler.current?.(e.points ?? [], 'select');
          });
          gd.on('plotly_deselect', () => handler.current?.([], 'clear'));
        },
        (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      cancelled = true;
    };
  }, [figure, selectable]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      loadPlotly().then((Plotly) => {
        if (el.isConnected && (el as { _fullLayout?: unknown })._fullLayout) void Plotly.Plots.resize(el);
      });
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      bound.current = false;
      loadPlotly().then((Plotly) => Plotly.purge(el));
    };
  }, []);

  return (
    <div className="relative h-full w-full">
      <div ref={ref} data-testid={testId} className="h-full w-full" />
      {error && (
        <p role="alert" className="absolute inset-x-0 top-0 text-xs text-destructive">
          Could not draw this plot: {error}
        </p>
      )}
    </div>
  );
}
