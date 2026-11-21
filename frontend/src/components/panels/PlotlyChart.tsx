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

/**
 * Thin React wrapper around `Plotly.react` (instead of react-plotly.js, whose peer dependency drags in the full
 * plotly.js source tree). Redraws when the figure changes, follows the container size, purges on unmount.
 */
export function PlotlyChart({ figure, testId }: { figure: Figure; testId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    loadPlotly()
      .then((Plotly) => {
        if (cancelled) return;
        return Plotly.react(el, figure.data as Data[], figure.layout as Partial<Layout>, CONFIG as Partial<Config>);
      })
      .then(
        () => !cancelled && setError(null),
        (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      cancelled = true;
    };
  }, [figure]);

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
