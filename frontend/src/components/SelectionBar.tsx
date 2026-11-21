import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store';

const SHOWN = 5;

/**
 * Linked selection summary in the header (T17e): which keys are selected across panels, and a Clear button.
 * Selection is view state, not a spec change, so it creates no version. Hidden when nothing is selected.
 */
export function SelectionBar({ selectionKey }: { selectionKey: string | null }) {
  const selection = useAppStore((s) => s.selection);
  const select = useAppStore((s) => s.select);
  if (!selectionKey || selection.length === 0) return null;
  const head = selection.slice(0, SHOWN).join(', ');
  const more = selection.length > SHOWN ? ` +${selection.length - SHOWN} more` : '';
  return (
    <div
      data-testid="selection-bar"
      className="flex min-w-0 items-center gap-2 rounded-md bg-amber-100 px-2 py-0.5 text-sm"
      title={selection.join(', ')}
    >
      <span className="shrink-0 font-medium">
        {selection.length} selected
      </span>
      <span className="truncate text-muted-foreground">
        {selectionKey}: {head}
        {more}
      </span>
      <Button data-testid="selection-clear" variant="ghost" size="sm" className="h-6 px-2" onClick={() => select([])}>
        Clear
      </Button>
    </div>
  );
}
