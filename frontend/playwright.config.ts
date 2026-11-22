// Playwright e2e config for Aibex View: `make e2e` (or `npx playwright test e2e/<spec>.ts` in frontend/).
// Browsers: `npx playwright install chromium` once per machine.
// Runs the backend with the FakeProvider and the synthetic toy bundle – no network, no real data.
// E2E_REAL_DATA=<data dir> runs only the real-data specs (e2e/real-*.spec.ts, e.g. the ADAR2 view) against that
// folder instead of the toy bundle; without it those specs are ignored. Real data stay outside the repo.
import { defineConfig, devices } from '@playwright/test';

const realData = process.env.E2E_REAL_DATA;
const backendData = realData
  ? `AIBEX_DATA_DIR="${realData}" uv run uvicorn aibex.main:app --port 8000`
  : 'uv run python tests/fixtures/make_toy_bundle.py tests/fixtures/toy-data && ' +
    'AIBEX_DATA_DIR=tests/fixtures/toy-data uv run uvicorn aibex.main:app --port 8000';

export default defineConfig({
  testDir: './e2e',
  ...(realData ? { testMatch: /real-.*\.spec\.ts$/ } : { testIgnore: /real-.*\.spec\.ts$/ }),
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
      command: `cd ../backend && export LLM_PROVIDER=fake && ${backendData}`,
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
