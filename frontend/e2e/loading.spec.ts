// P5.1 – loading states for panels and chat, error banner with retry (docs/acceptance.md, T50).
// Slow or failing backend calls are simulated with page.route; the backend itself runs with the FakeProvider.
import { test, expect, type Page, type Route } from '@playwright/test';

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function send(page: Page, text: string) {
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
}

test('P5.1 panels show a loading placeholder until their data arrive', async ({ page }) => {
  await page.route('**/api/sessions/*/panel-data', async (route: Route) => {
    await delay(1500);
    await route.continue();
  });
  await page.goto('/?bundle=toy');
  const loading = page.locator('[data-testid^="loading-panel-"]');
  await expect(loading.first()).toBeVisible();
  await expect(page.locator('[data-testid^="panel-"][data-loading="true"]').first()).toBeVisible();
  await page.screenshot({ path: '../logs/screens/P5.1-panels-loading.png', fullPage: true });
  await expect(loading).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
});

test('P5.1 a failed panel shows Retry and loads on retry', async ({ page }) => {
  let fail = true;
  await page.route('**/api/sessions/*/panel-data', async (route: Route) => {
    if (fail) await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"simulated outage"}' });
    else await route.continue();
  });
  await page.goto('/?bundle=toy');
  const errors = page.locator('[data-testid^="error-panel-"]');
  await expect(errors.first()).toContainText('simulated outage');
  await page.waitForLoadState('networkidle');
  fail = false;
  const retry = page.locator('[data-testid^="retry-panel-"]');
  for (let i = 0; i < 20 && (await retry.count()) > 0; i++) await retry.first().click();
  await expect(errors).toHaveCount(0);
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
});

test('P5.1 opening a bundle fails → error banner → Retry opens it', async ({ page }) => {
  let fail = true;
  await page.route('**/api/sessions', async (route: Route) => {
    if (fail && route.request().method() === 'POST') {
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"backend restarting"}' });
    } else await route.continue();
  });
  await page.goto('/?bundle=toy');
  const banner = page.getByTestId('error-banner');
  await expect(banner).toContainText('backend restarting');
  await page.screenshot({ path: '../logs/screens/P5.1-error-banner.png' });
  fail = false;
  await page.getByTestId('error-retry').click();
  await expect(page.getByTestId('spec-version')).toHaveText('0');
  await expect(banner).toHaveCount(0);
});

/** Toy session with one enabled filter (`filter-padj-lt`, added by the FakeProvider) at version 1. */
async function withFilter(page: Page) {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');
  await send(page, 'padj below 0.001');
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await expect(page.getByTestId('filter-padj-lt')).toBeChecked();
}

test('P5.1 a change that fails on the server can be retried from the banner', async ({ page }) => {
  await withFilter(page);
  let fail = true;
  await page.route('**/api/sessions/*/patch', async (route: Route) => {
    if (fail) await route.fulfill({ status: 502, contentType: 'application/json', body: '{"detail":"bad gateway"}' });
    else await route.continue();
  });
  await page.getByTestId('filter-padj-lt').click();
  await expect(page.getByTestId('error-banner')).toContainText('bad gateway');
  await expect(page.getByTestId('spec-version')).toHaveText('1');
  fail = false;
  await page.getByTestId('error-retry').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2');
  await expect(page.getByTestId('filter-padj-lt')).not.toBeChecked();
  await expect(page.getByTestId('error-banner')).toHaveCount(0);
});

test('P5.1 a rejected change (4xx) has no Retry', async ({ page }) => {
  await withFilter(page);
  await page.route('**/api/sessions/*/patch', (route: Route) =>
    route.fulfill({ status: 422, contentType: 'application/json', body: '{"detail":{"errors":["invalid patch"]}}' }),
  );
  await page.getByTestId('filter-padj-lt').click();
  await expect(page.getByTestId('error-banner')).toContainText('invalid patch');
  await expect(page.getByTestId('error-retry')).toHaveCount(0);
});

test('P5.1 chat shows a pending state with elapsed time, and a failed request can be retried', async ({ page }) => {
  await page.goto('/?bundle=toy');
  await expect(page.getByTestId('spec-version')).toHaveText('0');

  // slow turn: pending line with a ticking timer
  await page.route('**/api/sessions/*/chat', async (route: Route) => {
    await delay(2500);
    await route.continue();
  });
  await send(page, 'Label Gene_001');
  await expect(page.getByTestId('chat-pending')).toBeVisible();
  await expect(page.getByTestId('chat-elapsed')).toBeVisible({ timeout: 3000 });
  await expect(page.getByTestId('chat-send')).toBeDisabled();
  await page.screenshot({ path: '../logs/screens/P5.1-chat-pending.png' });
  await expect(page.getByTestId('spec-version')).toHaveText('1', { timeout: 15_000 });
  await expect(page.getByTestId('chat-pending')).toHaveCount(0);
  await page.unroute('**/api/sessions/*/chat');

  // failed request: Retry in the bubble sends the same prompt again
  let fail = true;
  await page.route('**/api/sessions/*/chat', async (route: Route) => {
    if (fail) await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"llm proxy down"}' });
    else await route.continue();
  });
  await send(page, 'Label Gene_002');
  await expect(page.getByTestId('chat-message').last()).toContainText('llm proxy down');
  await expect(page.getByTestId('chat-input')).toHaveValue('');
  fail = false;
  await page.getByTestId('chat-retry').click();
  await expect(page.getByTestId('spec-version')).toHaveText('2', { timeout: 15_000 });
  await expect(page.getByTestId('chat-retry')).toHaveCount(0);
  await expect(page.locator('.js-plotly-plot').first()).toContainText('Gene_002');
});
