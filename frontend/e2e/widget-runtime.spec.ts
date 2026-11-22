// T41a – Level 2 widget iframe runtime: sandbox + CSP, data and selection via postMessage, onSelect back to the page,
// errors kept inside the panel. Widgets are added to the fresh backend session through the patch endpoint (the TSX
// compile of LLM widgets is T41b, so the code here is plain JavaScript in CommonJS form).
import { test, expect, type Page } from '@playwright/test';

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

async function withWidget(page: Page, panel: Record<string, unknown>) {  await page.route('**/api/sessions', async (route) => {
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
