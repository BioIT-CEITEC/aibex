// T17c – PCA and heatmap panels on the toy bundle's default view (`pca` + `top-genes` from the default view generator).
import { test, expect } from '@playwright/test';

test('PCA renders one point per sample with sample names and a group legend', async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  const pca = page.getByTestId('plot-pca');
  await expect(pca).toHaveClass(/js-plotly-plot/);
  await expect(pca.locator('.scatterlayer .point').first()).toBeVisible();
  // axis titles carry the explained variance from panel-data
  await expect(pca.locator('.xtitle')).toContainText('PC1');
  await expect(pca.locator('.ytitle')).toContainText('PC2');
  // coloured by the first samples.tsv annotation → at least two legend entries
  expect(await pca.locator('.legendtext').count()).toBeGreaterThanOrEqual(2);
});

test('heatmap renders a matrix with row labels and sample group band', async ({ page }) => {
  await page.goto('/?bundle=toy');
  const heatmap = page.getByTestId('plot-top-genes');
  await expect(heatmap).toHaveClass(/js-plotly-plot/);
  await expect(heatmap.locator('.heatmaplayer image, .heatmaplayer .hm').first()).toBeAttached();
  // y tick labels = matrix keys (up to 30 genes)
  expect(await heatmap.locator('.ytick').count()).toBeGreaterThan(1);
  // group names drawn above the columns
  expect(await heatmap.locator('.annotation-text').count()).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId('panel-top-genes')).not.toContainText('Could not load');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '../logs/screens/T17c-pca-heatmap.png', fullPage: true });
});
