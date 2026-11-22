// T42 / M4 – the widget the real code model wrote for demo prompt 5 ("editing sites along the transcript") renders on
// the real ADAR2 bundle. Opt-in, needs the data outside the repo and the widget saved by the live acceptance test:
//   cd backend && uv run pytest -q tests/acceptance -m live -k widget_editing -s   (→ logs/widgets/…json, gitignored)
//   make e2e E2E_REAL_DATA=<AIBEX_DATA_DIR> ARGS=e2e/real-adar2-widget.spec.ts
// No LLM call here: the saved panel is added to a fresh session through the patch endpoint.
import { existsSync, readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

const WIDGET_FILE = '../logs/widgets/live-widget-editing-adar2.json';

test('M4: live-generated editing-sites widget renders on ADAR2 and follows the gene selection', async ({ page }) => {
  test.skip(!existsSync(WIDGET_FILE), `no saved live widget at ${WIDGET_FILE}`);
  const panel = JSON.parse(readFileSync(WIDGET_FILE, 'utf8')) as { id: string; type: string };
  expect(panel.type).toBe('widget');

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('**/api/sessions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    const created = (await response.json()) as { session_id: string };
    const patched = await page.request.post(`/api/sessions/${created.session_id}/patch`, {
      data: {
        patch: [
          { op: 'add', path: '/panels/-', value: panel },
          { op: 'add', path: '/layout/-', value: { i: panel.id, x: 0, y: 100, w: 12, h: 10 } },
        ],
        summary: 'e2e: add the live-generated widget',
      },
    });
    expect(patched.ok(), await patched.text()).toBeTruthy();
    const body = (await patched.json()) as { spec: unknown; version: number };
    await route.fulfill({ json: { ...created, spec: body.spec, version: body.version } });
  });
  await page.goto('/?bundle=adar2-editing');
  await expect(page.getByTestId('spec-version')).toHaveText('1');

  const frameEl = page.getByTestId(`widget-frame-${panel.id}`);
  await expect(frameEl).toHaveAttribute('sandbox', 'allow-scripts');
  await frameEl.scrollIntoViewIfNeeded();
  const frame = frameEl.contentFrame();
  // nothing selected yet: the widget shows its own hint, no error
  await expect(frame.locator('body')).toContainText(/select/i, { timeout: 20_000 });
  await expect(page.getByTestId(`widget-error-${panel.id}`)).toHaveCount(0);

  // the gene with the most editing sites (first row of edited-genes) → $selected → sites along the gene
  await page.getByTestId('table-edited-genes').locator('tbody tr').first().click();
  await expect(page.getByTestId('selection-bar')).toBeVisible();
  await expect(frame.locator('.main-svg').first()).toBeVisible({ timeout: 20_000 });
  await frameEl.scrollIntoViewIfNeeded();
  await page.waitForTimeout(800); // let Plotly finish drawing
  await page.getByTestId(`panel-${panel.id}`).screenshot({ path: '../logs/screens/T42-adar2-widget.png' });
  await expect(frame.locator('.scatterlayer .point').first()).toBeAttached({ timeout: 10_000 });
  await expect(page.getByTestId(`widget-error-${panel.id}`)).toHaveCount(0);

  await page.screenshot({ path: '../logs/screens/T42-adar2-widget-page.png' });
});
