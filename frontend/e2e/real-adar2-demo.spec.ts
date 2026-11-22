// T53 / P5.4 – screenshots of the end state of every demo prompt (docs/roadmap.md) on the real ADAR2 bundle, in the
// light and the dark theme, for the visual palette check. Opt-in, needs the data outside the repo:
//   make e2e E2E_REAL_DATA=<AIBEX_DATA_DIR> ARGS=e2e/real-adar2-demo.spec.ts
// NO LLM here: each state is built with hand-written JSON patches that stand in for what the model should produce
// (the live model runs are T26/T33). Prompt 5 uses the widget the live code model wrote (T42), if it was saved.
import { existsSync, readFileSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';

type Op = Record<string, unknown>;
const WIDGET_FILE = '../logs/widgets/live-widget-editing-adar2.json';

// stand-ins for demo prompts 1–4 (cumulative); the ADAR2 default view has the volcano at index 0
const STEPS: { n: number; summary: string; patch: Op[] }[] = [
  {
    n: 1,
    summary: 'label the 10 most significant genes',
    patch: [{ op: 'replace', path: '/panels/0/label', value: { field: 'gene_name', values: [], top_n: 10, by: 'padj' } }],
  },
  {
    n: 2,
    summary: 'padj < 0.01 and |log2FC| > 1 everywhere',
    patch: [
      { op: 'add', path: '/filters/-', value: { id: 'padj-001', table: 'de', field: 'padj', op: '<', value: 0.01, label: 'padj < 0.01', enabled: true } },
      { op: 'add', path: '/filters/-', value: { id: 'lfc-1', table: 'de', expr: 'abs(log2FoldChange) > 1', label: '|log2FC| > 1', enabled: true } },
    ],
  },
  {
    n: 3,
    summary: 'heatmap of the top 30 genes by genotype',
    patch: [
      {
        op: 'add',
        path: '/panels/-',
        value: {
          id: 'top-genes', type: 'plot', kind: 'heatmap', title: 'Top 30 genes by padj', table: 'counts',
          rows: { top_n: 30, by: 'de.padj', values: [] }, group_by: 'genotype', scale: 'row-z',
        },
      },
      { op: 'add', path: '/layout/-', value: { i: 'top-genes', x: 0, y: 0, w: 6, h: 10 } },
    ],
  },
  {
    n: 4,
    summary: 'colour the volcano by editing change',
    patch: [{ op: 'replace', path: '/panels/0/color', value: { field: 'mean_delta', label: 'mean editing Δ' } }],
  },
];

async function openWith(page: Page, patches: Op[][]): Promise<number> {
  let version = 0;
  await page.route('**/api/sessions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    const created = (await response.json()) as { session_id: string; spec: unknown; version: number };
    let body = { spec: created.spec, version: created.version };
    for (const patch of patches) {
      const r = await page.request.post(`/api/sessions/${created.session_id}/patch`, { data: { patch, summary: 'e2e demo state' } });
      expect(r.ok(), await r.text()).toBeTruthy();
      body = (await r.json()) as typeof body;
    }
    version = body.version;
    await route.fulfill({ json: { ...created, spec: body.spec, version: body.version } });
  });
  await page.goto('/?bundle=adar2-editing');
  await expect(page.getByTestId('spec-version')).not.toHaveText('–');
  return version;
}

async function settled(page: Page) {
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[data-testid^="loading-panel-"]')).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByText('Could not load')).toHaveCount(0);
  await expect(page.getByText('Could not draw')).toHaveCount(0);
  await expect(page.getByTestId('error-banner')).toHaveCount(0);
  await page.waitForTimeout(800); // let Plotly finish its resize redraw
}

for (const mode of ['light', 'dark'] as const) {
  const theme: Op[][] = mode === 'dark' ? [[{ op: 'add', path: '/theme/dark', value: true }]] : [];

  for (const step of STEPS) {
    test(`demo prompt ${step.n} end state (${mode}): ${step.summary}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await openWith(page, [...theme, ...STEPS.filter((s) => s.n <= step.n).map((s) => s.patch)]);
      await settled(page);
      await page.screenshot({ path: `../logs/screens/T53-demo-${step.n}-${mode}.png` });
    });
  }

  test(`demo prompt 5 end state (${mode}): editing sites widget for the selected gene`, async ({ page }) => {
    test.skip(!existsSync(WIDGET_FILE), `no saved live widget at ${WIDGET_FILE}`);
    const panel = JSON.parse(readFileSync(WIDGET_FILE, 'utf8')) as { id: string };
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWith(page, [
      ...theme,
      ...STEPS.map((s) => s.patch),
      [
        { op: 'add', path: '/panels/-', value: panel },
        { op: 'add', path: '/layout/-', value: { i: panel.id, x: 6, y: 0, w: 6, h: 10 } },
      ],
    ]);
    await settled(page);
    await page.getByTestId('table-edited-genes').locator('tbody tr').first().click();
    await expect(page.getByTestId('selection-bar')).toBeVisible();
    const frameEl = page.getByTestId(`widget-frame-${panel.id}`);
    await expect(frameEl.contentFrame().locator('.main-svg').first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId(`widget-error-${panel.id}`)).toHaveCount(0);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `../logs/screens/T53-demo-5-${mode}.png` });
    await frameEl.scrollIntoViewIfNeeded();
    await page.getByTestId(`panel-${panel.id}`).screenshot({ path: `../logs/screens/T53-demo-5-widget-${mode}.png` });
  });

  test(`demo prompt 6 end state (${mode}): undo the last two changes`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const v = await openWith(page, [...theme, ...STEPS.map((s) => s.patch)]);
    await settled(page);
    // the two newest changes (heatmap, colour by editing) are undone; label and filters stay
    await page.getByTestId('undo-button').click();
    await expect(page.getByTestId('spec-version')).toHaveText(String(v + 1));
    await page.getByTestId('undo-button').click();
    await expect(page.getByTestId('spec-version')).toHaveText(String(v + 2));
    await expect(page.getByTestId('panel-top-genes')).toHaveCount(0);
    await expect(page.getByTestId('filter-padj-001')).toBeChecked();
    await expect(page.locator('html')).toHaveClass(mode === 'dark' ? /dark/ : /^(?!.*dark)/);
    await settled(page);
    await page.screenshot({ path: `../logs/screens/T53-demo-6-${mode}.png` });
  });
}
