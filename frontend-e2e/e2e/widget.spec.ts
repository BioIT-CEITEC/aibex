// E4.* – Level 2 widget runs in a sandboxed iframe (docs/acceptance.md)
import { test, expect } from '@playwright/test';

test('E4.1 add widget renders inside a sandboxed iframe', async ({ page }) => {
  await page.goto('/?bundle=toy');
  await page.getByTestId('chat-input').fill('add widget');
  await page.getByTestId('chat-send').click();
  const frame = page.locator('iframe[data-testid^="widget-frame-"]');
  await expect(frame).toBeVisible({ timeout: 20_000 });
  await expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  await expect(frame.contentFrame().locator('body')).toContainText(/\d+/);
  await page.screenshot({ path: '../logs/screens/E4.1-widget.png', fullPage: true });
});
