// T17b – Plotly plot panels on the toy bundle's default view (volcano + MA from the default view generator).
import { test, expect } from '@playwright/test';

test('volcano and MA render as Plotly scatter plots with a categorical colour legend', async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  for (const id of ['volcano', 'ma-plot']) {
    const plot = page.getByTestId(`plot-${id}`);
    await expect(plot).toHaveClass(/js-plotly-plot/);
    await expect(plot.locator('.scatterlayer .point').first()).toBeVisible();
  }
  // colour groups from the spec's palette show up as legend entries; the raw expr is not used as legend title
  const volcano = page.getByTestId('plot-volcano');
  await expect(volcano.locator('.legendtext', { hasText: 'significant' })).toHaveCount(1);
  await expect(volcano.locator('.legendtext', { hasText: 'n.s.' })).toHaveCount(1);
  await expect(volcano.locator('.legendtitletext')).toHaveCount(0);
});

test('label values from panel-data are drawn as annotations', async ({ page }) => {
  // the default view labels nothing, so give two volcano rows a label text in the panel-data response
  await page.route('**/api/sessions/*/panel-data', async (route) => {
    const body = route.request().postDataJSON() as { panel_id: string };
    const response = await route.fetch();
    const json = (await response.json()) as { columns: string[]; rows: unknown[][] };
    const li = json.columns.indexOf('label');
    if (body.panel_id === 'volcano' && li >= 0) {
      json.rows[0][li] = 'LabelOne';
      json.rows[1][li] = 'LabelTwo';
    }
    await route.fulfill({ response, json });
  });
  await page.goto('/?bundle=toy');
  const volcano = page.getByTestId('plot-volcano');
  await expect(volcano.locator('.annotation-text', { hasText: 'LabelOne' })).toBeVisible();
  await expect(volcano.locator('.annotation-text', { hasText: 'LabelTwo' })).toBeVisible();
  await page.screenshot({ path: '../logs/screens/T17b-plots.png' });
});
