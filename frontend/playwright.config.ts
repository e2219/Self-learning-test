import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:8123', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: {width:1440,height:1050} } }],
  webServer: {
    command: '../.venv/bin/python -m uvicorn tests.browser_server:app --host 127.0.0.1 --port 8123 --app-dir ..',
    url: 'http://127.0.0.1:8123/api/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
