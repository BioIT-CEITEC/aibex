// P5.4 – light/dark theme (T53): the theme lives in the spec (`theme.dark`), the header button patches it with source
// `user` (a new, undoable version), and the whole app follows: shell colours, Plotly ink/background, widget frames.
import { test, expect, type Page } from '@playwright/test';

const PLOTS = ['volcano', 'ma-plot', 'pca', 'top-genes'];

async function plotsDrawn(page: Page) {
  for (const id of PLOTS) await expect(page.getByTestId(`plot-${id}`)).toHaveClass(/js-plotly-plot/);
}

/** Fill colour of the first x-axis tick label of a plot (Plotly writes the font colour inline). */
async function tickColour(page: Page, id: string): Promise<string> {
  return page
    .getByTestId(`plot-${id}`)
    .locator('.xtick text')
    .first()
    .evaluate((el) => getComputedStyle(el).fill);
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
  await plotsDrawn(page);
});

test('P5.4 dark theme is an undoable spec change and recolours shell and plots', async ({ page }) => {
  const html = page.locator('html');
  await expect(html).not.toHaveClass(/dark/);
  const lightBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const lightTick = await tickColour(page, 'volcano');

  const toggle = page.getByTestId('theme-toggle');
  await expect(toggle).toHaveText(/Dark/);
  await toggle.click();
  await expect(page.getByTestId('spec-version')).toHaveText('1');
  await expect(html).toHaveClass(/dark/);
  await expect(toggle).toHaveText(/Light/);
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('history-item').filter({ hasText: 'dark theme' })).toHaveCount(1);

  // the shell and the plot ink changed; the plot background stays transparent (the card shows through)
  const darkBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(darkBg).not.toBe(lightBg);
  await plotsDrawn(page);
  await expect.poll(() => tickColour(page, 'volcano')).not.toBe(lightTick);
  const paper = await page
    .getByTestId('plot-volcano')
    .locator('.main-svg')
    .first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(paper).toBe('rgba(0, 0, 0, 0)');
  await expect(page.getByText('Could not draw')).toHaveCount(0);

  await page.waitForTimeout(400); // let Plotly finish its redraw
  await page.screenshot({ path: '../logs/screens/P5.4-dark.png' });

  // undo brings the light theme back
  await page.getByTestId('undo-button').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await expect(html).not.toHaveClass(/dark/);
  await expect.poll(() => tickColour(page, 'volcano')).toBe(lightTick);
  await page.waitForTimeout(400);
  await page.screenshot({ path: '../logs/screens/P5.4-light.png' });
});

test('P5.4 widget frames follow the theme', async ({ page }) => {
  await page.getByTestId('chat-input').fill('add widget');
  await page.getByTestId('chat-send').click();
  const frameEl = page.getByTestId('widget-frame-row-count');
  const frame = frameEl.contentFrame();
  await expect(frame.getByText('50', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(frame.locator('html')).toHaveAttribute('data-theme', 'light');

  await page.getByTestId('theme-toggle').click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(frame.locator('html')).toHaveAttribute('data-theme', 'dark');
  // widget text is light ink on the dark card, and the frame stays transparent (no white box)
  const ink = await frame.locator('body').evaluate((el) => getComputedStyle(el).color);
  expect(ink).toBe('rgb(240, 239, 236)');
  await expect(page.getByTestId('widget-error-row-count')).toHaveCount(0);
  await frameEl.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.getByTestId('panel-row-count').screenshot({ path: '../logs/screens/P5.4-dark-widget.png' });
});

test('P5.4 linked selection stays visible in the dark theme', async ({ page }) => {
  await page.getByTestId('theme-toggle').click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  const row = page.locator('[data-testid^="table-"] tbody tr').first();
  await row.click();
  await expect(page.getByTestId('selection-bar')).toBeVisible();
  // the selected row uses the theme's highlight token, not the light amber
  const bg = await row.evaluate((el) => getComputedStyle(el).backgroundColor);
  const page_bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).not.toBe(page_bg);
  expect(bg).not.toBe('rgba(0, 0, 0, 0)');
  await page.waitForTimeout(400);
  await page.screenshot({ path: '../logs/screens/P5.4-dark-selection.png' });
});
