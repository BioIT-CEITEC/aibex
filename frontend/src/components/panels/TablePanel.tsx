import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { compareCells, formatCell } from '@/lib/format';
import type { PanelDataState } from '@/lib/usePanelData';
import type { TablePanel as TablePanelSpec } from '@/lib/types';
import { cn } from '@/lib/utils';

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
export function TablePanel({ panel, state }: { panel: TablePanelSpec; state: PanelDataState }) {
  const { data } = state;
  const pageSize = Math.max(1, panel.page_size ?? 25);
  const [sort, setSort] = useState<SortState | null>(null);
  const [page, setPage] = useState(0);

  const visible = useMemo(() => {
    if (!data) return [];
    const listed = panel.columns?.length ? panel.columns : data.columns;
    return listed.map((c) => data.columns.indexOf(c)).filter((i) => i >= 0);
  }, [data, panel.columns]);

  const rows = useMemo(() => {
    if (!data) return [];
    const i = sort ? data.columns.indexOf(sort.col) : -1;
    if (!sort || i < 0) return data.rows;
    return [...data.rows].sort((a, b) => compareCells(a[i], b[i], sort.dir));
  }, [data, sort]);

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
            {shown.map((row, r) => (
              <tr key={current * pageSize + r} className="odd:bg-muted/40 hover:bg-accent">
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
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-2 text-xs text-muted-foreground">No rows match the current filters.</p>}
      </div>
      <div className="flex items-center gap-2 border-t px-2 pt-1 text-xs text-muted-foreground">
        <span>
          {rows.length} rows{data.truncated && ' (first 5000 loaded)'}
        </span>
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
