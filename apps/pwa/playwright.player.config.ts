import { defineConfig, devices } from "@playwright/test";

const playerUrl = "http://127.0.0.1:8765";
const workerUrl = "http://127.0.0.1:8787";
const workerBackendUrl = "http://127.0.0.1:8788";

export default defineConfig({
  testDir: "./e2e-player",
  outputDir: "test-results/e2e-player",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "player-boundary",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node ../../scripts/e2e_worker_backend_sink.mjs",
      url: `${workerBackendUrl}/__recording`,
      timeout: 30_000,
      gracefulShutdown: {
        signal: "SIGTERM",
        timeout: 5_000,
      },
      reuseExistingServer: false,
    },
    {
      command: `pnpm exec wrangler dev --local --ip 127.0.0.1 --port 8787 --var BACKEND_URL:${workerBackendUrl} --log-level warn`,
      url: workerUrl,
      timeout: 120_000,
      gracefulShutdown: {
        signal: "SIGTERM",
        timeout: 5_000,
      },
      reuseExistingServer: false,
    },
    {
      command: "sh ../../scripts/start-player-e2e.sh",
      url: playerUrl,
      timeout: 120_000,
      gracefulShutdown: {
        signal: "SIGTERM",
        timeout: 5_000,
      },
      reuseExistingServer: false,
    },
  ],
});
