// Playwright e2e config for Aibex View. Move this folder's contents into frontend/ once the frontend exists:
//   frontend/playwright.config.ts, frontend/e2e/*.spec.ts ; then `npm i -D @playwright/test && npx playwright install chromium`
// Runs the backend with the FakeProvider and the synthetic toy bundle – no network, no real data.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../logs/playwright-report' }]],
  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command:
        'cd ../backend && uv run python tests/fixtures/make_toy_bundle.py tests/fixtures/toy-data && ' +
        'LLM_PROVIDER=fake AIBEX_DATA_DIR=tests/fixtures/toy-data uv run uvicorn aibex.main:app --port 8000',
      url: 'http://localhost:8000/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
