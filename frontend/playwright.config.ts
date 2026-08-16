import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against the full compose stack (backend on :8000, frontend
 * on :3000). They are env-gated: without E2E_BASE_URL every spec self-skips,
 * so `pnpm test:e2e` is safe to run anywhere.
 *
 *   E2E_BASE_URL=http://localhost:3000 E2E_API_KEY=<key> pnpm test:e2e
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  timeout: 120_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
