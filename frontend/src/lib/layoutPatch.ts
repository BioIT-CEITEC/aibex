// Turns a layout produced by react-grid-layout (after a drag or resize) into a JSON Patch on `spec.layout`.
// Only changed coordinates are patched; a `test` on each item's id guards against a concurrent layout change
// (e.g. the LLM added a panel meanwhile) – the backend then answers 422 and the grid snaps back to the spec.
import type { LayoutItem, PatchOp } from './types';

const COORDS = ['x', 'y', 'w', 'h'] as const;

export interface GridItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LayoutChange {
  patch: PatchOp[];
  /** Ids of panels whose own position/size changed (others may have been pushed by compaction). */
  moved: string[];
}

export function layoutPatch(current: LayoutItem[], next: readonly GridItem[]): LayoutChange {
  const byId = new Map(next.map((it) => [it.i, it]));
  const patch: PatchOp[] = [];
  const moved: string[] = [];
  current.forEach((item, k) => {
    const n = byId.get(item.i);
    if (!n) return;
    const ops: PatchOp[] = COORDS.filter((c) => n[c] !== item[c]).map((c) => ({ op: 'replace', path: `/layout/${k}/${c}`, value: n[c] }));
    if (!ops.length) return;
    patch.push({ op: 'test', path: `/layout/${k}/i`, value: item.i }, ...ops);
    moved.push(item.i);
  });
  return { patch, moved };
}
