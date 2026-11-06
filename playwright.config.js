const { defineConfig } = require('@playwright/test');

// The specs' own servers, on ports no dev server or demo uses: the page, and a
// stand-in for every backend it talks to (tests/e2e/no-backend.mjs), so what a
// spec has not scripted is answered 503 rather than by a joe or a qmcp that
// happens to be running. Neither is reused.
const PAGE = 3100;
const NO_BACKEND = 3199;

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  reporter: process.env.CI ? 'dot' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${PAGE}`,
    headless: true,
  },
  webServer: [
    {
      command: 'node tests/e2e/no-backend.mjs',
      url: `http://127.0.0.1:${NO_BACKEND}/__ready`,
      env: { ...process.env, PORT: String(NO_BACKEND) },
      reuseExistingServer: false,
      timeout: 15000,
    },
    {
      command: `npm run dev -- --port ${PAGE} --strictPort`,
      url: `http://localhost:${PAGE}`,
      env: { ...process.env, JOE_API_URL: `http://127.0.0.1:${NO_BACKEND}`, QMCP_URL: `http://127.0.0.1:${NO_BACKEND}` },
      reuseExistingServer: false,
      timeout: 15000,
    },
  ],
});
