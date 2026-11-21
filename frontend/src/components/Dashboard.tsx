import { useMemo } from 'react';
import ReactGridLayout, { useContainerWidth, type Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { PanelFrame } from '@/components/panels/PanelFrame';
import type { Spec } from '@/lib/types';
import { useAppStore } from '@/store';

/** Height of one grid row in px; the default view uses h=9 → ~400 px panels. */
const ROW_HEIGHT = 40;

/**
 * Panel grid (react-grid-layout, 12 columns) rendered from `spec.layout`. Positions come only from the spec;
 * dragging/resizing (written back as a patch) is enabled in T17e, until then the grid is fixed.
 */
export function Dashboard({ spec }: { spec: Spec }) {
  const sessionId = useAppStore((s) => s.sessionId);
  const { width, containerRef, mounted } = useContainerWidth();

  const layout: Layout = useMemo(
    () => spec.layout.map(({ i, x, y, w, h, minW, minH }) => ({ i, x, y, w, h, minW, minH })),
    [spec.layout],
  );

  return (
    <div ref={containerRef} data-testid="dashboard-grid">
      {mounted && (
        <ReactGridLayout
          layout={layout}
          width={width}
          gridConfig={{ cols: 12, rowHeight: ROW_HEIGHT, margin: [12, 12], containerPadding: [0, 0] }}
          dragConfig={{ enabled: false, handle: '.panel-drag-handle' }}
          resizeConfig={{ enabled: false }}
        >
          {spec.panels.map((panel) => (
            <div key={panel.id}>
              <PanelFrame panel={panel} sessionId={sessionId} filters={spec.filters} />
            </div>
          ))}
        </ReactGridLayout>
      )}
    </div>
  );
}
