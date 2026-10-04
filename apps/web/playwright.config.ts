import { defineConfig, devices } from "@playwright/test";

// Smoke tests for the main journey. The web app runs with every API call mocked (MSW), so no
// API, database or Docker is needed.
const PORT = 5181;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    viewport: { width: 1280, height: 860 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } }],
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    env: { VITE_API_MOCKS: "all" },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
