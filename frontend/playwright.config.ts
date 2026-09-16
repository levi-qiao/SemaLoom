import { defineConfig, devices } from "@playwright/test";

const isolated = Boolean(process.env.SEMALOOM_E2E_ISOLATED);

export default defineConfig({
  testDir: "./tests",
  timeout: isolated ? 90_000 : 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL:
      process.env.SEMALOOM_E2E_URL ??
      (isolated ? "http://127.0.0.1:18082" : "http://127.0.0.1:8000"),
    trace: isolated ? "on" : "retain-on-failure",
  },
  webServer: isolated
    ? {
        command: "uv run python tests/e2e_isolated_chat_server.py",
        cwd: "..",
        url: "http://127.0.0.1:18082/identity",
        timeout: 120_000,
        reuseExistingServer: false,
      }
    : undefined,
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
