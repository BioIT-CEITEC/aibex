import { useMemo } from 'react';
import { buildFigure } from '@/lib/plotFigure';
import type { PlotPanel as PlotPanelSpec } from '@/lib/types';
import type { PanelDataState } from '@/lib/usePanelData';
import { PlotlyChart } from './PlotlyChart';

/**
 * Plot panel (`plot-<id>`): scatter / line / bar / histogram / box / violin from panel-data, with categorical or
 * continuous colour, point size, and labels as annotations; PCA of samples and heatmaps (long format pivoted).
 */
export function PlotPanel({ panel, state }: { panel: PlotPanelSpec; state: PanelDataState }) {
  const { data } = state;
  const figure = useMemo(() => (data ? buildFigure(panel, data) : null), [panel, data]);

  if (!data || !figure) return null;
  if (!data.rows.length) return <p className="text-xs text-muted-foreground">No rows match the current filters.</p>;

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <PlotlyChart figure={figure} testId={`plot-${panel.id}`} />
      </div>
      {data.truncated && (
        <p className="text-right text-[10px] text-muted-foreground">{panel.kind === 'heatmap' ? 'not all rows fit – first ones shown' : `first ${data.rows.length} rows shown`}</p>
      )}
    </div>
  );
}
