import { defineConfig, devices } from "@playwright/test";

const frontendUrl = "http://127.0.0.1:4174";
const backendUrl = "http://127.0.0.1:8010";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: [
    {
      command: "sh ../../scripts/start-e2e-backend.sh",
      url: `${backendUrl}/api/health`,
      timeout: 120_000,
      gracefulShutdown: {
        signal: "SIGTERM",
        timeout: 5_000,
      },
      reuseExistingServer: false,
    },
    {
      command: `VITE_API_BASE_URL=${backendUrl} pnpm build && cp e2e/fixtures/sw-e2e-update.js dist/sw-e2e-update.js && pnpm exec vite preview --host 127.0.0.1 --port 4174 --strictPort`,
      url: frontendUrl,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
