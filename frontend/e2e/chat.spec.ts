import { expect, test } from "@playwright/test";
import { E2E_ENABLED, seedSettings } from "./helpers";

/**
 * Chat happy path against the running compose stack. Assumes at least one
 * document has been ingested (the upload spec, or `make seed`).
 */
test.describe("chat happy path", () => {
  test.skip(!E2E_ENABLED, "Set E2E_BASE_URL to run e2e tests against the compose stack");

  test.beforeEach(async ({ page }) => {
    await seedSettings(page);
  });

  test("streams an answer with citations, sources and usage", async ({ page }) => {
    await page.goto("/");

    // Fresh conversation so the assertion targets exactly one exchange.
    await page.getByTestId("new-chat").click();

    const question = "What is this corpus about? Answer briefly.";
    await page.getByTestId("chat-input").fill(question);
    await page.getByTestId("send-button").click();

    // Optimistic user message appears immediately.
    await expect(page.getByText(question)).toBeVisible();

    // The assistant answer streams in and finalizes with a usage footer.
    const assistant = page.getByTestId("assistant-message").last();
    await expect(assistant).toBeVisible();
    await expect(page.getByTestId("usage-footer").last()).toBeVisible({ timeout: 90_000 });

    // Inline [n] markers render as clickable chips…
    const chips = page.getByTestId("citation-chip");
    await expect(chips.first()).toBeVisible();

    // …and the sources panel lists the retrieved contexts with the
    // cited-vs-retrieved distinction.
    const sources = page.getByTestId("sources-panel");
    await expect(sources.getByText(/retrieved/i).first()).toBeVisible();
    await expect(sources.getByText("Cited").first()).toBeVisible();

    // Clicking a chip highlights the matching source entry.
    await chips.first().click();
    await expect(sources.locator("button.border-primary")).toHaveCount(1);
  });
});
