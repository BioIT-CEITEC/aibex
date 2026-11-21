import { useMemo, useState } from 'react';
import ReactGridLayout, { useContainerWidth, type Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { PanelFrame } from '@/components/panels/PanelFrame';
import { layoutPatch } from '@/lib/layoutPatch';
import type { Spec } from '@/lib/types';
import { useAppStore } from '@/store';

/** Height of one grid row in px; the default view uses h=9 → ~400 px panels. */
const ROW_HEIGHT = 40;

/**
 * Panel grid (react-grid-layout, 12 columns) rendered from `spec.layout`. Dragging a panel by its title bar or
 * resizing it (bottom-right corner) sends one JSON Patch with source `user` – a new, undoable version (T17e).
 * Until the backend answers, the dropped layout is kept (no snap-back flicker); on rejection the grid returns to
 * the spec and the error banner explains why.
 */
export function Dashboard({ spec }: { spec: Spec }) {
  const sessionId = useAppStore((s) => s.sessionId);
  const applyPatch = useAppStore((s) => s.applyPatch);
  const { width, containerRef, mounted } = useContainerWidth();
  // layout dropped by the user, shown while its patch is in flight; tied to the spec layout it was made from
  const [pending, setPending] = useState<{ base: Spec['layout']; layout: Layout } | null>(null);

  const specLayout: Layout = useMemo(
    () => spec.layout.map(({ i, x, y, w, h, minW, minH }) => ({ i, x, y, w, h, minW, minH })),
    [spec.layout],
  );
  const layout = pending && pending.base === spec.layout ? pending.layout : specLayout;

  const selectionKey = spec.selection && spec.selection.linked !== false ? spec.selection.key : null;

  const commit = (verb: 'move' | 'resize') => async (next: Layout) => {
    const { patch, moved } = layoutPatch(spec.layout, next);
    if (!patch.length) return;
    const base = spec.layout;
    setPending({ base, layout: next.map((it) => ({ ...it })) });
    await applyPatch(patch, `${verb} panel ${moved[0]}${moved.length > 1 ? ` (+${moved.length - 1} shifted)` : ''}`);
    setPending((p) => (p?.base === base ? null : p));
  };
  const onMove = commit('move');
  const onResize = commit('resize');

  return (
    <div ref={containerRef} data-testid="dashboard-grid">
      {mounted && (
        <ReactGridLayout
          layout={layout}
          width={width}
          gridConfig={{ cols: 12, rowHeight: ROW_HEIGHT, margin: [12, 12], containerPadding: [0, 0] }}
          dragConfig={{ enabled: true, handle: '.panel-drag-handle' }}
          resizeConfig={{ enabled: true }}
          onDragStop={(next) => void onMove(next)}
          onResizeStop={(next) => void onResize(next)}
        >
          {spec.panels.map((panel) => (
            <div key={panel.id}>
              <PanelFrame panel={panel} sessionId={sessionId} filters={spec.filters} selectionKey={selectionKey} />
            </div>
          ))}
        </ReactGridLayout>
      )}
    </div>
  );
}
