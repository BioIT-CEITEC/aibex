// T41a/T41b – Level 2 widget iframe runtime: sandbox + CSP, data and selection via postMessage, onSelect back to the
// page, errors kept inside the panel, TSX/JSX compiled in the parent (sucrase). Widgets are added to the fresh backend
// session through the patch endpoint.
import { test, expect, type Page } from '@playwright/test';

// what an LLM typically writes: ES module, `import React`, TS types and generics, JSX, Plotly global
const TSX_WIDGET = `import React, { useEffect, useRef } from 'react';

type Input = { columns: string[]; rows: unknown[][] };
interface Props { data: { inputs: Record<string, Input> }; selection: string[]; onSelect: (keys: unknown[]) => void }

export default function Widget({ data, selection }: Props) {
  const genes = data.inputs.genes as Input;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) Plotly.newPlot(ref.current, [{ type: 'bar', x: genes.rows.map((r) => String(r[0])), y: genes.rows.map((r) => Number(r[1])) }], { margin: { t: 10 } }, { staticPlot: true });
  }, [genes]);
  return (
    <div>
      <p data-kind="tsx">tsx genes: {genes.rows.length} (selected {selection.length})</p>
      <div ref={ref} className="plot" style={{ height: 150 }} />
    </div>
  );
}
`;

const PROBE = `
exports.default = function Widget(props) {
  var h = React.createElement;
  var genes = props.data.inputs.genes;
  var sites = props.data.inputs.sites;
  var net = React.useState('no violation');
  React.useEffect(function () {
    document.addEventListener('securitypolicyviolation', function (e) { net[1]('blocked ' + e.effectiveDirective); });
    var img = new Image();
    img.src = 'https://example.org/pixel.png';
  }, []);
  return h('div', null,
    h('p', null, 'genes: ' + genes.rows.length),
    h('p', null, 'sites of selected: ' + sites.rows.length),
    h('p', null, 'selection: [' + props.selection.join(',') + ']'),
    h('p', null, 'plotly: ' + typeof Plotly.newPlot),
    h('p', null, 'network: ' + net[0]),
    h('button', { onClick: function () { props.onSelect([genes.rows[0][0]]); } }, 'select first gene'));
};
`;

async function withWidget(page: Page, panel: Record<string, unknown>) {
  await page.route('**/api/sessions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    const created = (await response.json()) as { session_id: string };
    const patched = await page.request.post(`/api/sessions/${created.session_id}/patch`, {
      data: {
        patch: [
          { op: 'add', path: '/selection', value: { key: 'gene_id', linked: true } },
          { op: 'add', path: '/panels/-', value: panel },
          { op: 'add', path: '/layout/-', value: { i: panel.id, x: 0, y: 100, w: 6, h: 8 } },
        ],
        summary: 'e2e: add widget',
      },
    });
    expect(patched.ok(), await patched.text()).toBeTruthy();
    const body = (await patched.json()) as { spec: unknown; version: number };
    await route.fulfill({ json: { ...created, spec: body.spec, version: body.version } });
  });
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('1');
}

test('widget runs sandboxed with a no-network CSP, gets data + selection, and selects back', async ({ page }) => {
  await withWidget(page, {
    id: 'probe',
    type: 'widget',
    title: 'Runtime probe',
    language: 'jsx',
    inputs: [
      { name: 'genes', sql: 'SELECT gene_id FROM de ORDER BY gene_id LIMIT 20' },
      { name: 'sites', sql: 'SELECT site_id FROM editing WHERE gene_id = $selected' },
    ],
    code: PROBE,
  });

  const frame = page.getByTestId('widget-frame-probe');
  await expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  await expect(frame).toHaveAttribute('srcdoc', /http-equiv="Content-Security-Policy" content="default-src 'none'/);
  const body = frame.contentFrame().locator('body');
  await expect(body).toContainText('genes: 20', { timeout: 20_000 });
  await expect(body).toContainText('sites of selected: 0'); // $selected is NULL without a selection
  await expect(body).toContainText('selection: []');
  await expect(body).toContainText('plotly: function');
  await expect(body).toContainText('network: blocked img-src');
  await frame.scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../logs/screens/T41a-widget-runtime.png', fullPage: true });

  // onSelect → linked selection in the page → panel-data refetch with $selected → new data in the widget
  const refetch = page.waitForRequest(
    (r) => r.url().includes('/panel-data') && (r.postData() ?? '').includes('"selection"'),
  );
  await frame.contentFrame().getByRole('button', { name: 'select first gene' }).click();
  await refetch;
  await expect(page.getByTestId('selection-bar')).toContainText('1 selected');
  await expect(body).toContainText(/selection: \[[^\]]+\]/);
  await expect(body).toContainText(/sites of selected: \d+/);
  // selection is view state: no new version
  await expect(page.getByTestId('spec-version')).toHaveText('1');
});

test('broken widget code shows an error inside its panel and the dashboard keeps working', async ({ page }) => {
  await withWidget(page, {
    id: 'broken',
    type: 'widget',
    title: 'Broken widget',
    language: 'jsx',
    inputs: [],
    code: 'exports.default = function Widget( { return 1 }',
  });
  await expect(page.getByTestId('widget-error-broken')).toContainText('Widget error', { timeout: 20_000 });
  await expect(page.getByTestId('widget-frame-broken').contentFrame().locator('body')).toContainText('Widget error');
  // other panels still render
  await expect(page.locator('[data-testid^="table-"] tbody tr').first()).toBeVisible();
});

test('TSX widget (imports, types, JSX, Plotly) is compiled in the browser and renders', async ({ page }) => {
  await withWidget(page, {
    id: 'tsx-probe',
    type: 'widget',
    title: 'TSX probe',
    language: 'tsx',
    inputs: [{ name: 'genes', sql: 'SELECT gene_id, baseMean FROM de ORDER BY gene_id LIMIT 12' }],
    code: TSX_WIDGET,
  });
  const frame = page.getByTestId('widget-frame-tsx-probe');
  const body = frame.contentFrame().locator('body');
  await expect(body).toContainText('tsx genes: 12 (selected 0)', { timeout: 20_000 });
  await expect(frame.contentFrame().locator('.plot .main-svg').first()).toBeVisible();
  await expect(page.getByTestId('widget-error-tsx-probe')).toHaveCount(0);
  await frame.scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../logs/screens/T41b-widget-tsx.png', fullPage: true });
});

test('chat "add widget" (FakeProvider TSX) shows the row count of its input', async ({ page }) => {
  // stricter than E4.1's /\d+/ (the srcdoc's inline scripts contain digits too): the visible count must be 50
  await page.goto('/?bundle=toy');
  await page.getByTestId('chat-input').fill('add widget');
  await page.getByTestId('chat-send').click();
  const frame = page.getByTestId('widget-frame-row-count').contentFrame();
  await expect(frame.getByText('50', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(frame.getByText('rows in the input (max 50)')).toBeVisible();
  await expect(page.getByTestId('widget-error-row-count')).toHaveCount(0);
  // Chromium does not paint off-viewport iframes into a fullPage screenshot
  await page.getByTestId('widget-frame-row-count').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../logs/screens/T41b-add-widget.png', fullPage: true });
});

test('TSX compile error is shown in the panel with its position', async ({ page }) => {
  await withWidget(page, {
    id: 'tsx-broken',
    type: 'widget',
    title: 'TSX broken',
    language: 'tsx',
    inputs: [],
    code: 'export default function Widget() {\n  return <div>unclosed;\n}\n',
  });
  const error = page.getByTestId('widget-error-tsx-broken');
  await expect(error).toContainText('Compile error (tsx)', { timeout: 20_000 });
  await expect(error).toContainText(/\(\d+:\d+\)/);
  await expect(page.getByTestId('widget-frame-tsx-broken').contentFrame().locator('body')).toContainText('Compile error');
});
