import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import type { HistorySource } from '@/lib/types';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/store';

function isTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

/**
 * Undo/redo buttons for the header (T24b). Enabled from the backend's `can_undo`/`can_redo`; disabled while a change
 * or a chat turn is in flight. Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z or Ctrl+Y redoes (not inside text fields, so the
 * chat input keeps its own text undo).
 */
export function UndoRedoButtons() {
  const canUndo = useAppStore((s) => s.canUndo);
  const canRedo = useAppStore((s) => s.canRedo);
  const busy = useAppStore((s) => s.busy || s.chatBusy || !s.sessionId);
  const undo = useAppStore((s) => s.undo);
  const redo = useAppStore((s) => s.redo);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || isTextField(e.target)) return;
      const key = e.key.toLowerCase();
      const state = useAppStore.getState();
      if (state.chatBusy) return;
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault();
        void undo();
      } else if ((key === 'z' && e.shiftKey) || (key === 'y' && !e.shiftKey)) {
        e.preventDefault();
        void redo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undo, redo]);

  return (
    <div className="flex items-center gap-1">
      <Button
        data-testid="undo-button"
        variant="outline"
        size="sm"
        title="Undo the last change (Ctrl/Cmd+Z)"
        disabled={busy || canUndo < 1}
        onClick={() => void undo()}
      >
        ↶ Undo
      </Button>
      <Button
        data-testid="redo-button"
        variant="outline"
        size="sm"
        title="Redo (Ctrl/Cmd+Shift+Z)"
        disabled={busy || canRedo < 1}
        onClick={() => void redo()}
      >
        Redo ↷
      </Button>
    </div>
  );
}

const SOURCE_LABEL: Record<HistorySource, string> = { init: 'init', user: 'you', llm: 'AI' };
const SOURCE_STYLE: Record<HistorySource, string> = {
  init: 'bg-muted text-muted-foreground',
  user: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200',
  llm: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200',
};

/** Version history of the session (T24b), newest first; every entry is one applied version. */
export function HistoryList() {
  const history = useAppStore((s) => s.history);
  const version = useAppStore((s) => s.version);
  const items = [...history].reverse();

  return (
    <details open className="border-b text-sm">
      <summary className="cursor-pointer select-none px-3 py-2 font-medium">
        History <span className="font-normal text-muted-foreground">({history.length})</span>
      </summary>
      <ol className="max-h-44 overflow-y-auto px-3 pb-2">
        {items.map((h) => {
          const current = h.version === version;
          return (
            <li
              key={h.version}
              data-testid="history-item"
              data-version={h.version}
              data-current={current ? 'true' : undefined}
              className={cn(
                'flex items-baseline gap-2 rounded px-1.5 py-0.5 text-xs',
                current && 'bg-accent font-medium',
              )}
              title={`version ${h.version} (${h.source}): ${h.summary}`}
            >
              <span className="w-6 shrink-0 text-right tabular-nums text-muted-foreground">v{h.version}</span>
              <span className={cn('shrink-0 rounded px-1 text-[10px] uppercase', SOURCE_STYLE[h.source])}>
                {SOURCE_LABEL[h.source] ?? h.source}
              </span>
              <span className="truncate">{h.summary}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
