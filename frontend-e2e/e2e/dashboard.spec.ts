// E1.* – dashboard renders from the spec (docs/acceptance.md)
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});

test('E1.1 renders at least 4 panels including a plot and a table', async ({ page }) => {
  const panels = page.locator('[data-testid^="panel-"]');
  await expect(panels.first()).toBeVisible();
  expect(await panels.count()).toBeGreaterThanOrEqual(4);
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  await expect(page.locator('[data-testid^="table-"] tbody tr').first()).toBeVisible();
  await page.screenshot({ path: '../logs/screens/E1.1-dashboard.png', fullPage: true });
});

test('E1.2 bundle selector lists the toy bundle', async ({ page }) => {
  await expect(page.getByTestId('bundle-select')).toContainText(/toy/i);
});

test('E1.3 no error banner on a clean load', async ({ page }) => {
  await expect(page.getByTestId('error-banner')).toHaveCount(0);
});
