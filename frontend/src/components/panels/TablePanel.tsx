import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { compareCells, formatCell } from '@/lib/format';
import type { PanelDataState } from '@/lib/usePanelData';
import type { JsonValue, TablePanel as TablePanelSpec } from '@/lib/types';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/store';

interface SortState {
  col: string;
  dir: 'asc' | 'desc';
}

/**
 * Table panel (`table-<id>`). Rows come from panel-data, already filtered and sorted as in the spec. Clicking a
 * header sorts the loaded rows locally (asc → desc → spec order); this is view state, not a spec change.
 * Columns: the spec's `columns` when listed (the backend appends the key column for linked selection – hidden
 * here), else every returned column.
 */
export function TablePanel({
  panel,
  state,
  selectionKey,
}: {
  panel: TablePanelSpec;
  state: PanelDataState;
  selectionKey: string | null;
}) {
  const { data } = state;
  const pageSize = Math.max(1, panel.page_size ?? 25);
  const [sort, setSort] = useState<SortState | null>(null);
  const selection = useAppStore((s) => s.selection);
  // the page belongs to the selection it was chosen under; a new selection jumps back to the first page
  // (selected rows are listed first)
  const [paging, setPaging] = useState({ page: 0, selection });
  const page = paging.selection === selection ? paging.page : 0;
  const setPage = (p: number) => setPaging({ page: p, selection });
  const select = useAppStore((s) => s.select);
  const selected = useMemo(() => new Set(selection), [selection]);
  // linked selection (T17e): only when this table's rows carry the spec's selection key
  const keyIdx = data && selectionKey ? data.columns.indexOf(selectionKey) : -1;
  const keyOf = (row: JsonValue[]) => (keyIdx >= 0 && row[keyIdx] !== null ? String(row[keyIdx]) : null);

  const visible = useMemo(() => {
    if (!data) return [];
    const listed = panel.columns?.length ? panel.columns : data.columns;
    return listed.map((c) => data.columns.indexOf(c)).filter((i) => i >= 0);
  }, [data, panel.columns]);

  const rows = useMemo(() => {
    if (!data) return [];
    const i = sort ? data.columns.indexOf(sort.col) : -1;
    const sorted = !sort || i < 0 ? data.rows : [...data.rows].sort((a, b) => compareCells(a[i], b[i], sort.dir));
    if (keyIdx < 0 || !selected.size) return sorted;
    // selected rows first (a selection made in a plot may sit on any page), otherwise the order is kept
    const hit = (r: JsonValue[]) => r[keyIdx] !== null && selected.has(String(r[keyIdx]));
    return [...sorted.filter(hit), ...sorted.filter((r) => !hit(r))];
  }, [data, sort, keyIdx, selected]);
  const nSelected = useMemo(
    () => (keyIdx < 0 ? 0 : rows.filter((r) => r[keyIdx] !== null && selected.has(String(r[keyIdx]))).length),
    [rows, keyIdx, selected],
  );

  if (!data) return null;
  const numeric = (i: number) => typeof data.rows.find((r) => r[i] !== null)?.[i] === 'number';
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(page, pages - 1); // data may shrink after a filter change
  const shown = rows.slice(current * pageSize, (current + 1) * pageSize);

  const toggleSort = (col: string) => {
    setPage(0);
    setSort((s) => (s?.col !== col ? { col, dir: 'asc' } : s.dir === 'asc' ? { col, dir: 'desc' } : null));
  };

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <table data-testid={`table-${panel.id}`} className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-card">
            <tr>
              {visible.map((i) => {
                const name = data.columns[i];
                const dir = sort?.col === name ? sort.dir : null;
                return (
                  <th
                    key={name}
                    scope="col"
                    aria-sort={dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'}
                    className={cn(
                      'border-b px-2 py-1 font-medium whitespace-nowrap',
                      numeric(i) ? 'text-right' : 'text-left',
                    )}
                  >
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:underline"
                      title="Sort the loaded rows"
                      onClick={() => toggleSort(name)}
                    >
                      {name}
                      <span className="w-2 text-muted-foreground">{dir === 'asc' ? '▲' : dir === 'desc' ? '▼' : ''}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, r) => {
              const key = keyOf(row);
              const isSel = key !== null && selected.has(key);
              return (
              <tr
                key={current * pageSize + r}
                data-selected={isSel || undefined}
                className={cn(
                  'odd:bg-muted/40 hover:bg-accent',
                  key !== null && 'cursor-pointer',
                  isSel && 'bg-highlight font-medium odd:bg-highlight hover:bg-highlight-strong',
                )}
                title={key !== null ? 'Click to select (shift/ctrl-click: add or remove)' : undefined}
                onClick={
                  key === null
                    ? undefined
                    : (e) => {
                        if (e.shiftKey || e.ctrlKey || e.metaKey) select([key], 'toggle');
                        // plain click on the only selected row clears the selection
                        else select(isSel && selected.size === 1 ? [] : [key]);
                      }
                }
              >
                {visible.map((i) => (
                  <td
                    key={data.columns[i]}
                    className={cn(
                      'px-2 py-0.5 whitespace-nowrap',
                      numeric(i) && 'text-right tabular-nums',
                    )}
                  >
                    {formatCell(row[i])}
                  </td>
                ))}
              </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-2 text-xs text-muted-foreground">No rows match the current filters.</p>}
      </div>
      <div className="flex items-center gap-2 border-t px-2 pt-1 text-xs text-muted-foreground">
        <span>
          {rows.length} rows{data.truncated && ' (first 5000 loaded)'}
        </span>
        {nSelected > 0 && <span className="font-medium text-foreground">{nSelected} selected (shown first)</span>}
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            aria-label="Previous page"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            ‹
          </Button>
          <span>
            {current + 1} / {pages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            aria-label="Next page"
            disabled={current >= pages - 1}
            onClick={() => setPage(current + 1)}
          >
            ›
          </Button>
        </div>
      </div>
    </div>
  );
}
