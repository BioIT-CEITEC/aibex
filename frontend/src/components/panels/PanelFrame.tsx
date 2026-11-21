import { Button } from '@/components/ui/button';
import { usePanelData } from '@/lib/usePanelData';
import type { Filter, Panel } from '@/lib/types';
import { PlotPanel } from './PlotPanel';
import { TablePanel } from './TablePanel';

/** Panels whose data come from `panel-data` (text needs none; widgets get theirs in T40a/T41a). */
function needsData(panel: Panel): boolean {
  return panel.type === 'plot' || panel.type === 'table';
}

/**
 * Card around one panel (`panel-<id>`): title bar (also the drag handle once T17e enables dragging), loading /
 * error state with Retry, and the body for the panel type. Errors stay inside the panel – one broken panel never
 * takes the dashboard down.
 */
export function PanelFrame({
  panel,
  sessionId,
  filters,
}: {
  panel: Panel;
  sessionId: string | null;
  filters: Filter[] | undefined;
}) {
  const state = usePanelData(needsData(panel) ? sessionId : null, panel, filters);
  const kind = panel.type === 'plot' ? panel.kind : panel.type;

  return (
    <div
      data-testid={`panel-${panel.id}`}
      className="flex h-full flex-col overflow-hidden rounded-lg border bg-card text-card-foreground shadow-xs"
    >
      <div className="panel-drag-handle flex items-center gap-2 border-b px-3 py-1.5" title={panel.description}>
        <h2 className="truncate text-sm font-medium">{panel.title || panel.id}</h2>
        <span className="text-xs text-muted-foreground">{kind}</span>
        {state.loading && <span className="ml-auto text-xs text-muted-foreground">loading…</span>}
      </div>
      <div className="relative min-h-0 flex-1 p-2">
        {state.error ? (
          <div role="alert" className="flex flex-col items-start gap-2 text-xs text-destructive">
            <span className="break-words">Could not load this panel: {state.error}</span>
            <Button variant="outline" size="sm" onClick={state.reload}>
              Retry
            </Button>
          </div>
        ) : (
          <PanelBody panel={panel} state={state} />
        )}
      </div>
    </div>
  );
}

function PanelBody({ panel, state }: { panel: Panel; state: ReturnType<typeof usePanelData> }) {
  switch (panel.type) {
    case 'table':
      return <TablePanel panel={panel} state={state} />;
    case 'text':
      return <div className="h-full overflow-auto text-sm whitespace-pre-wrap">{panel.markdown}</div>;
    case 'plot':
      return <PlotPanel panel={panel} state={state} />;
    case 'widget':
      return <p className="text-xs text-muted-foreground">Custom widget – the sandboxed runtime is not built yet.</p>;
  }
}
