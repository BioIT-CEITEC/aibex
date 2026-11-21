import { useCallback, useMemo } from 'react';
import { buildFigure, highlightSelection, isSelectablePlot } from '@/lib/plotFigure';
import type { PlotPanel as PlotPanelSpec } from '@/lib/types';
import type { PanelDataState } from '@/lib/usePanelData';
import { useAppStore } from '@/store';
import { PlotlyChart, type PlotPoint, type PointsEvent } from './PlotlyChart';

/** Key of a clicked/selected point: heatmap rows are matrix keys (`y`), other plots carry the key in `customdata`. */
function pointKey(kind: PlotPanelSpec['kind'], p: PlotPoint): string | null {
  const v = kind === 'heatmap' ? p.y : p.customdata;
  return typeof v === 'string' || typeof v === 'number' ? String(v) : null;
}

/**
 * Plot panel (`plot-<id>`): scatter / line / bar / histogram / box / violin from panel-data, with categorical or
 * continuous colour, point size, and labels as annotations; PCA of samples and heatmaps (long format pivoted).
 * Linked selection (T17e): when the panel's rows carry `selectionKey`, clicks and box/lasso selections set the shared
 * selection, and selected keys are highlighted. Heatmap rows are assumed to be values of the selection key (the
 * matrix key, e.g. gene_id).
 */
export function PlotPanel({
  panel,
  state,
  selectionKey,
}: {
  panel: PlotPanelSpec;
  state: PanelDataState;
  selectionKey: string | null;
}) {
  const { data } = state;
  const selection = useAppStore((s) => s.selection);
  const select = useAppStore((s) => s.select);
  // zoom/pan survive redraws caused by selection or data changes, but reset when the panel spec changes
  const revision = useMemo(() => JSON.stringify(panel), [panel]);
  const figure = useMemo(() => {
    if (!data) return null;
    const fig = buildFigure(panel, data);
    return { data: fig.data, layout: { ...fig.layout, uirevision: revision } };
  }, [panel, data, revision]);

  const linked =
    !!selectionKey && !!data && isSelectablePlot(panel) && (panel.kind === 'heatmap' || data.columns.includes(selectionKey));
  const selected = useMemo(() => new Set(selection), [selection]);
  const shown = useMemo(() => (figure && linked ? highlightSelection(panel, figure, selected) : figure), [figure, linked, panel, selected]);

  const onPoints = useCallback(
    (points: PlotPoint[], how: PointsEvent) => {
      if (how === 'clear') return select([]);
      const keys = points.map((p) => pointKey(panel.kind, p)).filter((k): k is string => k !== null);
      if (how !== 'select' && !keys.length) return;
      select(keys, how === 'toggle' ? 'toggle' : 'replace');
    },
    [panel.kind, select],
  );

  if (!data || !shown) return null;
  if (!data.rows.length) return <p className="text-xs text-muted-foreground">No rows match the current filters.</p>;

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <PlotlyChart figure={shown} testId={`plot-${panel.id}`} onPoints={linked ? onPoints : undefined} />
      </div>
      {data.truncated && (
        <p className="text-right text-[10px] text-muted-foreground">{panel.kind === 'heatmap' ? 'not all rows fit – first ones shown' : `first ${data.rows.length} rows shown`}</p>
      )}
    </div>
  );
}
