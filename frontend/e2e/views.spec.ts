// P5.2 – saved views per bundle (T51): save the current spec under a title, load it as an undoable version.
// Views are written to the toy bundle's views/ folder (gitignored test data); every run uses a fresh title.
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});

test('P5.2 save a view, load it as a new version, undo it', async ({ page }) => {
  const stamp = Date.now().toString(36);
  const title = `E2E view ${stamp}`;
  const header = page.locator('header');
  const before = await header.locator('span.truncate').first().textContent();

  await page.getByTestId('save-view-button').click();
  await page.getByTestId('view-title-input').fill(title);
  await expect(page.getByTestId('save-view-form')).toContainText(`e2e-view-${stamp}`);
  await page.screenshot({ path: '../logs/screens/P5.2-save-view.png' });
  await page.getByTestId('view-save-confirm').click();
  await expect(page.getByTestId('save-view-form')).toHaveCount(0);
  await expect(page.getByTestId('view-saved')).toBeVisible();
  // saving does not change the session
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  const select = page.getByTestId('view-select');
  await expect(select.locator('option', { hasText: title })).toHaveCount(1);
  await select.selectOption({ label: title });

  await expect(page.getByTestId('spec-version')).toHaveText('1');
  await expect(header).toContainText(title);
  await expect(page.locator('[data-testid="history-item"][data-current="true"]')).toContainText(
    `load view e2e-view-${stamp}`,
  );
  await expect(page.getByTestId('error-banner')).toHaveCount(0);
  await page.screenshot({ path: '../logs/screens/P5.2-loaded-view.png', fullPage: true });

  await page.getByTestId('undo-button').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await expect(header.locator('span.truncate').first()).toHaveText(before ?? '');
});

test('P5.2 a title without letters or digits cannot be saved', async ({ page }) => {
  await page.getByTestId('save-view-button').click();
  await page.getByTestId('view-title-input').fill('  ---  ');
  await expect(page.getByTestId('view-save-confirm')).toBeDisabled();
});

test('P5.2 a save the backend rejects shows its reason in the form', async ({ page }) => {
  await page.route('**/api/bundles/toy/views', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 422, contentType: 'application/json', body: '{"detail":{"errors":["panels.0: bad"]}}' })
      : route.continue(),
  );
  await page.getByTestId('save-view-button').click();
  await page.getByTestId('view-title-input').fill('Rejected');
  await page.getByTestId('view-save-confirm').click();
  await expect(page.getByTestId('view-save-error')).toHaveText('panels.0: bad');
  await expect(page.getByTestId('save-view-form')).toBeVisible();
});
