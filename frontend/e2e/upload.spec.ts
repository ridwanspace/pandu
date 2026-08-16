import { expect, test } from "@playwright/test";
import { E2E_ENABLED, seedSettings } from "./helpers";

const FIXTURE = {
  name: "pandu-e2e-fixture.md",
  mimeType: "text/markdown",
  buffer: Buffer.from(
    [
      "# Pandu e2e fixture",
      "",
      "## Purpose",
      "This document exists so the upload flow e2e test has a deterministic file.",
      "It is small, parses fast, and mentions the word pandu-fixture-marker.",
    ].join("\n"),
    "utf-8",
  ),
};

test.describe("document upload flow", () => {
  test.skip(!E2E_ENABLED, "Set E2E_BASE_URL to run e2e tests against the compose stack");

  test.beforeEach(async ({ page }) => {
    await seedSettings(page);
  });

  test("uploads a file and tracks it to Ready", async ({ page }) => {
    await page.goto("/documents");

    await page.getByTestId("file-input").setInputFiles(FIXTURE);

    const table = page.getByTestId("documents-table");
    const row = table.locator("tr", { hasText: FIXTURE.name }).first();
    await expect(row).toBeVisible();

    // Ingestion runs in the background; the table polls until terminal state.
    await expect(row.getByText("Ready")).toBeVisible({ timeout: 120_000 });

    // Chunk inspector shows the parsed chunks.
    await row.getByRole("button", { name: `Inspect chunks of ${FIXTURE.name}` }).click();
    await expect(page.getByRole("dialog").getByText(/pandu-fixture-marker/)).toBeVisible();
    await page.keyboard.press("Escape");

    // Clean up so reruns start fresh.
    await row.getByRole("button", { name: `Delete ${FIXTURE.name}` }).click();
    await page.getByRole("button", { name: "Delete" }).click();
    await expect(table.locator("tr", { hasText: FIXTURE.name })).toHaveCount(0);
  });
});
