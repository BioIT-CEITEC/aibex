// T17a – panel grid + table panel (sort, paging) on the toy bundle's default view.
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});

test('grid shows a frame per panel and the table panel sorts and pages', async ({ page }) => {
  await expect(page.locator('[data-testid^="panel-"]').first()).toBeVisible();
  expect(await page.locator('[data-testid^="panel-"]').count()).toBeGreaterThanOrEqual(4);

  const table = page.locator('[data-testid^="table-"]').first();
  const rows = table.locator('tbody tr');
  await expect(rows.first()).toBeVisible();
  const pageSize = await rows.count();
  expect(pageSize).toBeGreaterThan(0);

  // paging: the toy DE table has more rows than one page
  const frame = page.locator('[data-testid^="panel-"]').filter({ has: table });
  await expect(frame.getByText(/^1 \/ \d+$/)).toBeVisible();
  const firstCell = await rows.first().locator('td').first().textContent();
  await frame.getByRole('button', { name: 'Next page' }).click();
  await expect(frame.getByText(/^2 \/ \d+$/)).toBeVisible();
  await expect(rows.first().locator('td').first()).not.toHaveText(firstCell ?? '');
  await frame.getByRole('button', { name: 'Previous page' }).click();

  // sorting: first column ascending then descending
  const header = table.locator('thead th').first();
  await header.getByRole('button').click();
  await expect(header).toHaveAttribute('aria-sort', 'ascending');
  const asc = await rows.first().locator('td').first().textContent();
  await header.getByRole('button').click();
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(rows.first().locator('td').first()).not.toHaveText(asc ?? '');

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '../logs/screens/T17a-grid.png', fullPage: true });
});
