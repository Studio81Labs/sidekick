import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-player-update",
  outputDir: "test-results/e2e-player-update",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
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
      name: "player-update-boundary",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
