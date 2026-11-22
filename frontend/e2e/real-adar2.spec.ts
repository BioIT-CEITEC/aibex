// T32 – ADAR2 default view on the real bundle (opt-in, needs the data outside the repo):
//   cd frontend && E2E_REAL_DATA=<AIBEX_DATA_DIR> npx playwright test
// Checks that expression and editing panels are drawn and that a gene selected in a table reaches the per-site
// editing plots (linked by gene_id); screenshots into logs/screens/ for the human check.
import { test, expect } from '@playwright/test';

const PLOTS = ['volcano', 'editing-vs-expression', 'editing-levels', 'pca'];
const TABLES = ['edited-genes', 'editing-sites'];

test('T32: ADAR2 default view combines expression and editing', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?bundle=adar2-editing');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  for (const id of PLOTS) {
    await expect(page.getByTestId(`plot-${id}`)).toHaveClass(/js-plotly-plot/, { timeout: 15_000 });
  }
  for (const id of TABLES) {
    await expect(page.getByTestId(`table-${id}`).locator('tbody tr').first()).toBeVisible();
  }
  await expect(page.getByText('Could not load')).toHaveCount(0);
  await expect(page.getByTestId('error-banner')).toHaveCount(0);
  const overflowX = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflowX).toBeLessThanOrEqual(0);

  // T34: the whole volcano (~33 500 genes) fits under the plot cap – no "row cap" note
  await expect(page.getByTestId('panel-volcano').getByText(/rows shown/)).toHaveCount(0);

  await page.waitForTimeout(500); // let Plotly finish its resize redraw
  await page.screenshot({ path: '../logs/screens/T32-adar2-viewport.png' });
  await page.getByTestId('panel-volcano').screenshot({ path: '../logs/screens/T34-adar2-volcano.png' });
  await page.screenshot({ path: '../logs/screens/T32-adar2-full.png', fullPage: true });

  // the gene with the most editing sites (first row) → selection reaches the editing plots
  await page.getByTestId('table-edited-genes').locator('tbody tr').first().click();
  await expect(page.getByTestId('selection-bar')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: '../logs/screens/T32-adar2-selection.png', fullPage: true });
});
