import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  timeout: 45000,
  use: {
    baseURL: process.env.NEBULA_E2E_URL || 'http://localhost:14321',
    headless: true,
    trace: 'off',
  },
  reporter: 'list',
});
