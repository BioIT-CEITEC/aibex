import { useState } from 'react';
import type { Filter, JsonValue } from '@/lib/types';
import { useAppStore } from '@/store';

function formatValue(v: JsonValue | undefined): string {
  if (Array.isArray(v)) return v.map((x) => formatValue(x)).join(', ');
  if (typeof v === 'string') return `"${v}"`;
  return v === undefined ? '' : String(v);
}

/** Readable text for a filter: its `label`, else `field op value` / the `expr`. */
function filterText(f: Filter): string {
  if (f.label) return f.label;
  if (f.expr) return f.expr;
  if (f.op === 'between' && Array.isArray(f.value)) return `${f.field} between ${formatValue(f.value)}`;
  if (f.op === 'in') return `${f.field} in [${formatValue(f.value)}]`;
  return `${f.field} ${f.op} ${formatValue(f.value)}`;
}

/**
 * Filters bar (T17d): one checkbox per spec filter (`filter-<id>`). Toggling sends a JSON Patch with source `user`,
 * i.e. a new, undoable version. The checkbox flips at once (optimistic) and falls back to the spec value when the
 * request finishes – on failure the error banner explains why.
 */
export function FiltersBar({ filters }: { filters: Filter[] }) {
  const applyPatch = useAppStore((s) => s.applyPatch);
  const [pending, setPending] = useState<Record<string, boolean>>({});

  if (filters.length === 0) return null;

  const toggle = async (index: number, f: Filter, enabled: boolean) => {
    setPending((p) => ({ ...p, [f.id]: enabled }));
    // `test` guards against the filter list having changed underneath (e.g. a chat edit in flight);
    // `add` also works when `enabled` was omitted in the spec (default true).
    await applyPatch(
      [
        { op: 'test', path: `/filters/${index}/id`, value: f.id },
        { op: 'add', path: `/filters/${index}/enabled`, value: enabled },
      ],
      `${enabled ? 'enable' : 'disable'} filter ${f.id}`,
    );
    setPending((p) => {
      const next = { ...p };
      delete next[f.id];
      return next;
    });
  };

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/30 px-3 py-2 text-sm">
      <span className="font-medium text-muted-foreground">Filters</span>
      {filters.map((f, i) => {
        const checked = pending[f.id] ?? f.enabled !== false;
        return (
          <label
            key={f.id}
            className="flex cursor-pointer items-center gap-1.5"
            title={`table ${f.table}${f.label ? ` · ${filterText({ ...f, label: undefined })}` : ''}`}
          >
            <input
              type="checkbox"
              data-testid={`filter-${f.id}`}
              className="size-4 accent-primary"
              checked={checked}
              disabled={f.id in pending}
              onChange={(e) => void toggle(i, f, e.target.checked)}
            />
            <span className={checked ? '' : 'text-muted-foreground line-through'}>{filterText(f)}</span>
          </label>
        );
      })}
    </div>
  );
}
