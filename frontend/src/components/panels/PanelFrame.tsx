import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { usePanelData } from '@/lib/usePanelData';
import { cn } from '@/lib/utils';
import type { Filter, Panel } from '@/lib/types';
import { PlotPanel } from './PlotPanel';
import { TablePanel } from './TablePanel';
import { WidgetPanel } from './WidgetPanel';
import { useAppStore } from '@/store';

/** Panels whose data come from `panel-data` (text needs none). */
function needsData(panel: Panel): boolean {
  return panel.type === 'plot' || panel.type === 'table' || panel.type === 'widget';
}

/** Widgets whose input SQL uses `$selected` refetch when the selection changes; nothing else sends the selection. */
function usesSelected(panel: Panel): boolean {
  return panel.type === 'widget' && (panel.inputs ?? []).some((i) => /\$selected\b/.test(i.sql));
}

/**
 * Card around one panel (`panel-<id>`): title bar (also the drag handle), loading /
 * error state with Retry, and the body for the panel type. Errors stay inside the panel – one broken panel never
 * takes the dashboard down.
 */
export function PanelFrame({
  panel,
  sessionId,
  filters,
  selectionKey,
}: {
  panel: Panel;
  sessionId: string | null;
  filters: Filter[] | undefined;
  /** `spec.selection.key` when linked selection is on, else null. */
  selectionKey: string | null;
}) {
  const selection = useAppStore((s) => s.selection);
  const state = usePanelData(
    needsData(panel) ? sessionId : null,
    panel,
    filters,
    usesSelected(panel) ? selection : null,
  );
  const kind = panel.type === 'plot' ? panel.kind : panel.type;
  // first load: nothing to show yet → placeholder; refetch: keep the old data, dimmed, with a spinner in the title bar
  const firstLoad = state.loading && !state.data;

  return (
    <div
      data-testid={`panel-${panel.id}`}
      data-loading={state.loading ? 'true' : undefined}
      aria-busy={state.loading || undefined}
      className="flex h-full flex-col overflow-hidden rounded-lg border bg-card text-card-foreground shadow-xs"
    >
      <div
        className="panel-drag-handle flex cursor-move items-center gap-2 border-b px-3 py-1.5"
        title={panel.description ? `${panel.description} – drag to move` : 'Drag to move; resize at the bottom-right corner'}
      >
        <h2 className="truncate text-sm font-medium">{panel.title || panel.id}</h2>
        <span className="text-xs text-muted-foreground">{kind}</span>
        {state.loading && !firstLoad && (
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <Spinner className="size-3" /> updating…
          </span>
        )}
      </div>
      <div className="relative min-h-0 flex-1 p-2">
        {state.error ? (
          <div
            role="alert"
            data-testid={`error-panel-${panel.id}`}
            className="flex flex-col items-start gap-2 text-xs text-destructive"
          >
            <span className="break-words">Could not load this panel: {state.error}</span>
            <Button variant="outline" size="sm" data-testid={`retry-panel-${panel.id}`} onClick={state.reload}>
              Retry
            </Button>
          </div>
        ) : firstLoad ? (
          <div
            data-testid={`loading-panel-${panel.id}`}
            className="flex h-full animate-pulse flex-col items-center justify-center gap-2 rounded-md bg-muted/40 text-xs text-muted-foreground"
          >
            <Spinner />
            Loading data…
          </div>
        ) : (
          <div className={cn('h-full transition-opacity', state.loading && 'opacity-60')}>
            <PanelBody panel={panel} state={state} selectionKey={selectionKey} />
          </div>
        )}
      </div>
    </div>
  );
}

function PanelBody({
  panel,
  state,
  selectionKey,
}: {
  panel: Panel;
  state: ReturnType<typeof usePanelData>;
  selectionKey: string | null;
}) {
  switch (panel.type) {
    case 'table':
      return <TablePanel panel={panel} state={state} selectionKey={selectionKey} />;
    case 'text':
      return <div className="h-full overflow-auto text-sm whitespace-pre-wrap">{panel.markdown}</div>;
    case 'plot':
      return <PlotPanel panel={panel} state={state} selectionKey={selectionKey} />;
    case 'widget':
      return <WidgetPanel panel={panel} state={state} />;
  }
}
