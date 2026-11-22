// T18 / M1 – visual pass at 1440×900 on the toy bundle's default view: every panel drawn, nothing overlapping or
// clipped, then screenshots into logs/screens/ (viewport + full page) for the human check.
import { test, expect } from '@playwright/test';

test('M1: default view is readable at 1440x900', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  const frames = page.locator('[data-testid^="panel-"]');
  await expect(frames.first()).toBeVisible();
  const n = await frames.count();
  expect(n).toBeGreaterThanOrEqual(4);

  // every plot drawn, no panel error
  for (const id of ['volcano', 'ma-plot', 'pca', 'top-genes']) {
    await expect(page.getByTestId(`plot-${id}`)).toHaveClass(/js-plotly-plot/);
  }
  await expect(page.locator('[data-testid^="table-"] tbody tr').first()).toBeVisible();
  await expect(page.getByText('Could not load')).toHaveCount(0);
  await expect(page.getByTestId('error-banner')).toHaveCount(0);

  // no horizontal page scroll at 1440 px
  const overflowX = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflowX).toBeLessThanOrEqual(0);

  // panel frames do not overlap each other
  const boxes = [];
  for (let i = 0; i < n; i++) {
    const b = await frames.nth(i).boundingBox();
    if (b) boxes.push(b);
  }
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      const ox = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
      const oy = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
      expect(ox > 1 && oy > 1, `panels ${i} and ${j} overlap`).toBe(false);
    }
  }

  // each plot fits inside its frame (no clipping by the card)
  for (const id of ['volcano', 'ma-plot', 'pca', 'top-genes']) {
    const frame = await page.getByTestId(`panel-${id}`).boundingBox();
    const plot = await page.getByTestId(`plot-${id}`).locator('.main-svg').first().boundingBox();
    expect(frame && plot).toBeTruthy();
    expect(plot!.x).toBeGreaterThanOrEqual(frame!.x - 1);
    expect(plot!.x + plot!.width).toBeLessThanOrEqual(frame!.x + frame!.width + 1);
    expect(plot!.y + plot!.height).toBeLessThanOrEqual(frame!.y + frame!.height + 1);
    expect(plot!.height).toBeGreaterThan(150);
  }

  await page.waitForTimeout(300); // let Plotly finish its resize redraw
  await page.screenshot({ path: '../logs/screens/M1-viewport-1440x900.png' });
  await page.screenshot({ path: '../logs/screens/M1-full-1440.png', fullPage: true });
});
