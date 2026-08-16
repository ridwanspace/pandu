import type { Page } from "@playwright/test";

export const E2E_ENABLED = Boolean(process.env.E2E_BASE_URL);
export const API_BASE_URL = process.env.E2E_API_BASE_URL ?? "http://localhost:8000";
export const API_KEY = process.env.E2E_API_KEY ?? "dev-key";

/**
 * Seed connection settings before the app boots. Mirrors the zustand
 * `persist` envelope for the `pandu-settings` localStorage key.
 */
export async function seedSettings(page: Page): Promise<void> {
  await page.addInitScript(
    ([apiBaseUrl, apiKey]) => {
      window.localStorage.setItem(
        "pandu-settings",
        JSON.stringify({ state: { apiBaseUrl, apiKey }, version: 0 }),
      );
    },
    [API_BASE_URL, API_KEY],
  );
}
