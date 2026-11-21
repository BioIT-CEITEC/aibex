// T17d – filters bar: one checkbox per spec filter; toggling is a user patch (new, undoable version).
// The toy default view has no filters, so the session-creation response is intercepted: the test adds a filter to
// the fresh backend session via the patch endpoint and hands the patched spec to the page (backend and UI agree).
import { test, expect } from '@playwright/test';

test('filter checkbox toggles the filter as a new version and changes the table rows', async ({ page }) => {
  await page.route('**/api/sessions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    const created = (await response.json()) as { session_id: string };
    const patched = await page.request.post(`/api/sessions/${created.session_id}/patch`, {
      data: {
        patch: [
          {
            op: 'add',
            path: '/filters/-',
            value: { id: 'sig', table: 'de', field: 'padj', op: '<', value: 0.05, label: 'padj < 0.05', enabled: true },
          },
        ],
        summary: 'e2e: add filter',
      },
    });
    expect(patched.ok()).toBeTruthy();
    const body = (await patched.json()) as { spec: unknown; version: number };
    await route.fulfill({ json: { ...created, spec: body.spec, version: body.version } });
  });

  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('1');

  const box = page.getByTestId('filter-sig');
  await expect(box).toBeChecked();
  await expect(page.getByText('padj < 0.05')).toBeVisible();

  const table = page.locator('[data-testid^="table-"]').first();
  const frame = page.locator('[data-testid^="panel-"]').filter({ has: table });
  const rowCount = async () => Number((await frame.getByText(/^\d+ rows/).textContent())?.match(/^(\d+)/)?.[1] ?? NaN);
  await expect(table.locator('tbody tr').first()).toBeVisible();
  const filtered = await rowCount();
  expect(filtered).toBeGreaterThan(0);

  // off → version 2, more rows
  await box.uncheck();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await expect(box).not.toBeChecked();
  await expect.poll(rowCount).toBeGreaterThan(filtered);

  // on again → version 3, back to the filtered count
  await box.check();
  await expect(page.getByTestId('spec-version')).toHaveText('3');
  await expect(box).toBeChecked();
  await expect.poll(rowCount).toBe(filtered);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '../logs/screens/T17d-filters.png' });
});
