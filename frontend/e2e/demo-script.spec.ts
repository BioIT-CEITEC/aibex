// P5.3 – demo-script panel: the 6 demo prompts (docs/roadmap.md), click to send (FakeProvider, toy bundle)
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
});

test('P5.3 demo script lists the six demo prompts', async ({ page }) => {
  const script = page.getByTestId('demo-script');
  await expect(script).toBeVisible();
  await expect(script.locator('[data-testid^="demo-prompt-"]')).toHaveCount(6);
  await expect(page.getByTestId('demo-prompt-1')).toContainText('Label the 10 most significant genes');
  await expect(page.getByTestId('demo-prompt-6')).toContainText('Undo the last two changes.');
  await expect(page.getByTestId('demo-prompt-1')).toBeEnabled();
  await page.screenshot({ path: '../logs/screens/P5.3-demo-script.png', fullPage: true });
});

test('P5.3 clicking a demo prompt sends it as a chat message', async ({ page }) => {
  const input = page.getByTestId('chat-input');
  // two changes first, then demo prompt 6 undoes both (FakeProvider rule "undo the last two changes")
  await input.fill('Label Gene_001');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await input.fill('padj below 0.001');
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2', { timeout: 15_000 });
  await expect(page.getByTestId('filter-padj-lt')).toBeChecked();

  await page.getByTestId('demo-prompt-6').click();
  await expect(page.getByTestId('chat-user-message').last()).toHaveText('Undo the last two changes.');
  await expect(page.getByTestId('spec-version')).toHaveText('3', { timeout: 15_000 });
  await expect(page.getByTestId('filter-padj-lt')).toHaveCount(0);
  await expect(page.locator('.js-plotly-plot').first()).not.toContainText('Gene_001');
  // the input is left untouched and the prompts are usable again once the turn is over
  await expect(input).toHaveValue('');
  await expect(page.getByTestId('demo-prompt-1')).toBeEnabled();
  await page.screenshot({ path: '../logs/screens/P5.3-demo-prompt-sent.png', fullPage: true });
});
