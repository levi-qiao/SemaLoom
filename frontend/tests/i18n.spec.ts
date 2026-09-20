import { expect, test } from "@playwright/test";

test("English locale drives the Studio shell and Chat request", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("semaloom.locale", "en"));
  await page.route("**/v0.1/chat/status", route =>
    route.fulfill({ json: { enabled: true, ready: true, model: "offline-test" } }),
  );
  let locale = "";
  await page.route("**/v0.1/chat/turns", async route => {
    locale = route.request().postDataJSON().locale;
    await route.fulfill({
      contentType: "application/x-ndjson",
      body: [
        { type: "start", conversationId: "e".repeat(32), releaseDigest: "a".repeat(64) },
        {
          type: "choice",
          originalQuestion: "Show annual filings",
          question: {
            questionId: "q1",
            revision: 1,
            slot: "year",
            prompt: "Which business year should be used?",
            reason: "A year is required to determine the population.",
            options: [
              {
                id: "y2025",
                label: "2025",
                explanation: "Business year available in the published source",
                choice: { kind: "YEAR", id: "2025" },
              },
            ],
          },
        },
        { type: "done" },
      ].map(item => JSON.stringify(item)).join("\n") + "\n",
    });
  });

  await page.goto("/studio/?view=chat");
  await expect(page.getByRole("heading", { name: "Business Q&A" })).toBeVisible();
  await page.getByLabel("Business question").fill("Show annual filings");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("Which business year should be used?")).toBeVisible();
  expect(locale).toBe("en");
});
