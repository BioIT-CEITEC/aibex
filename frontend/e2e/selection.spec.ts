// T17e – linked selection across panels (by `spec.selection.key`) and drag/resize written back as user patches.
// Toy bundle default view: `volcano` scatter and `genes` table both read the DE table, selection key = its key.
import { test, expect, type Page } from '@playwright/test';

type Trace = { name?: string; selectedpoints?: number[] };

/** Plotly keeps the drawn traces on the graph div (`gd.data`). */
async function traces(page: Page, plotId: string): Promise<Trace[]> {
  return page.getByTestId(`plot-${plotId}`).evaluate((el) =>
    ((el as unknown as { data?: Trace[] }).data ?? []).map((t) => ({ name: t.name, selectedpoints: t.selectedpoints })),
  );
}

test('clicking a table row or a plot point selects it in every linked panel; Clear resets', async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
  const table = page.getByTestId('table-genes');
  const volcano = page.getByTestId('plot-volcano');
  await expect(table.locator('tbody tr').first()).toBeVisible();
  await expect(volcano.locator('.scatterlayer .point').first()).toBeVisible();
  await expect(page.getByTestId('selection-bar')).toHaveCount(0);

  // table row → selection (view state: no new version), row highlighted, volcano gets the ring trace
  await table.locator('tbody tr').nth(2).click();
  await expect(page.getByTestId('selection-bar')).toContainText('1 selected');
  await expect(table.locator('tbody tr[data-selected]')).toHaveCount(1);
  await expect(table.locator('tbody tr').first()).toHaveAttribute('data-selected', 'true'); // selected rows first
  await expect.poll(async () => (await traces(page, 'volcano')).some((t) => t.name === 'selected')).toBe(true);
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  // shift-click a second row → two selected
  await table.locator('tbody tr').nth(4).click({ modifiers: ['Shift'] });
  await expect(page.getByTestId('selection-bar')).toContainText('2 selected');
  await expect(table.locator('tbody tr[data-selected]')).toHaveCount(2);

  // Clear → nothing selected, no highlight
  await page.getByTestId('selection-clear').click();
  await expect(page.getByTestId('selection-bar')).toHaveCount(0);
  await expect(table.locator('tbody tr[data-selected]')).toHaveCount(0);
  await expect.poll(async () => (await traces(page, 'volcano')).some((t) => t.name === 'selected')).toBe(false);

  // click a volcano point → that gene is selected and shown first in the table
  const point = volcano.locator('.scatterlayer .point').first();
  const box = await point.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await expect(page.getByTestId('selection-bar')).toContainText('1 selected');
  await expect(table.locator('tbody tr').first()).toHaveAttribute('data-selected', 'true');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '../logs/screens/T17e-selection.png' });
});

test('dragging and resizing a panel sends user patches (new, undoable versions)', async ({ page }) => {
  // StrictMode may create two sessions and keep the later one; only the live session asks for panel-data
  const panelData = page.waitForRequest((r) => r.url().includes('/panel-data'));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?bundle=toy');
  const sid = (await panelData).url().match(/\/sessions\/([^/]+)\/panel-data/)![1];
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  type Item = { i: string; x: number; y: number; w: number; h: number };
  const session = async () =>
    (await (await page.request.get(`/api/sessions/${sid}`)).json()) as {
      spec: { layout: Item[] };
      history: { summary: string; source: string }[];
    };
  const before = (await session()).spec.layout.find((it) => it.i === 'volcano')!;

  // drag the volcano by its title bar half the grid to the right
  const handle = page.getByTestId('panel-volcano').locator('.panel-drag-handle');
  const hb = (await handle.boundingBox())!;
  const grid = (await page.getByTestId('dashboard-grid').boundingBox())!;
  const dx = before.x < 6 ? grid.width / 2 : -grid.width / 2;
  await page.mouse.move(hb.x + 40, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + 40 + dx / 2, hb.y + hb.height / 2, { steps: 8 });
  await page.mouse.move(hb.x + 40 + dx, hb.y + hb.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByTestId('spec-version')).toHaveText('1');
  let s = await session();
  // where exactly it lands depends on vertical compaction; it must have moved
  const after = s.spec.layout.find((it) => it.i === 'volcano')!;  expect([after.x, after.y]).not.toEqual([before.x, before.y]);
  expect(s.history.at(-1)).toMatchObject({ source: 'user' });
  expect(s.history.at(-1)!.summary).toContain('move panel volcano');

  // resize the table panel at its bottom-right handle: taller by ~3 rows
  const tableBefore = s.spec.layout.find((it) => it.i === 'genes')!;
  const resize = page.locator('.react-grid-item', { has: page.getByTestId('panel-genes') }).locator('.react-resizable-handle');
  await resize.scrollIntoViewIfNeeded();
  const rb = (await resize.boundingBox())!;
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2 + 80, { steps: 8 });
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2 + 160, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  s = await session();
  expect(s.spec.layout.find((it) => it.i === 'genes')!.h).toBeGreaterThan(tableBefore.h);
  expect(s.history.at(-1)!.summary).toContain('resize panel genes');

  // a plain click on the title bar (no movement) changes nothing
  await handle.click();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await page.screenshot({ path: '../logs/screens/T17e-layout.png' });
});
