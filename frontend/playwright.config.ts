import { defineConfig, devices } from "@playwright/test";

const isolated = Boolean(process.env.SEMALOOM_E2E_ISOLATED);
const isolatedURL = `http://127.0.0.1:${process.env.SEMALOOM_E2E_HTTP_PORT ?? "18082"}`;

export default defineConfig({
  testDir: "./tests",
  timeout: isolated ? 90_000 : 30_000,
  fullyParallel: false,
  workers: isolated ? 1 : undefined,
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL:
      process.env.SEMALOOM_E2E_URL ??
      (isolated ? isolatedURL : "http://127.0.0.1:8000"),
    trace: isolated ? "on" : "retain-on-failure",
  },
  webServer: isolated
    ? {
        command: "uv run python tests/e2e_isolated_chat_server.py",
        cwd: "..",
        url: `${isolatedURL}/identity`,
        timeout: 120_000,
        reuseExistingServer: false,
        gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
      }
    : undefined,
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
