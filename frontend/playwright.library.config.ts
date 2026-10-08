import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e-library',
  workers: 1,
  timeout: 90000,
  outputDir: 'test-results/library',
  use: {
    baseURL: 'http://127.0.0.1:8124',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'library-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1050 } },
    },
  ],
  webServer: [
    {
      command:
        '../.venv/bin/python -m uvicorn tests.library_server:app --host 127.0.0.1 --port 8124 --app-dir ..',
      url: 'http://127.0.0.1:8124/api/health',
      reuseExistingServer: false,
    },
    {
      command:
        '../.venv/bin/python -m uvicorn tests.browser_server:app --host 127.0.0.1 --port 8123 --app-dir ..',
      url: 'http://127.0.0.1:8123/api/health',
      reuseExistingServer: false,
    },
  ],
});
