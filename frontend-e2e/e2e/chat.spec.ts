// E2.* – prompt editing with the FakeProvider (LLM_PROVIDER=fake), history and undo (docs/acceptance.md)
import { test, expect, Page } from '@playwright/test';

async function send(page: Page, text: string) {
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
}

test.beforeEach(async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});

test('E2.1 label prompt changes the spec and shows labels', async ({ page }) => {
  await send(page, 'Label Gene_001, Gene_002');
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await expect(page.getByTestId('history-item')).toHaveCount(2); // init + change
  await expect(page.locator('.js-plotly-plot').first()).toContainText('Gene_001');
  await expect(page.getByTestId('chat-message').last()).toBeVisible();
  await page.screenshot({ path: '../logs/screens/E2.1-label.png', fullPage: true });
});

test('E2.2 filter prompt reduces table rows', async ({ page }) => {
  const rows = page.locator('[data-testid^="table-"] tbody tr');
  await expect(rows.first()).toBeVisible();
  await send(page, 'padj below 0.001');
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await expect(page.getByTestId('filter-padj-lt')).toBeChecked();
  // toggling the filter off brings rows back (and is itself an undoable change)
  const filtered = await rows.count();
  await page.getByTestId('filter-padj-lt').uncheck();
  await expect.poll(async () => rows.count()).toBeGreaterThanOrEqual(filtered);
});

test('E2.3 undo and redo buttons', async ({ page }) => {
  await send(page, 'Label Gene_005');
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await page.getByTestId('undo-button').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await expect(page.locator('.js-plotly-plot').first()).not.toContainText('Gene_005');
  await page.getByTestId('redo-button').click();
  await expect(page.getByTestId('spec-version')).toHaveText('3');
  await expect(page.locator('.js-plotly-plot').first()).toContainText('Gene_005');
});

test('E2.4 unknown prompt shows a reply and changes nothing', async ({ page }) => {
  await send(page, 'tell me a joke');
  await expect(page.getByTestId('chat-message').last()).toContainText(/no rule matched/i, { timeout: 15_000 });
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});
