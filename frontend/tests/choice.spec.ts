import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const evidenceDir =
  process.env.SEMALOOM_Q3_EVIDENCE ??
  join(process.cwd(), "test-results", "q3-choice");

test.use({ trace: "on" });

test.beforeAll(() => {
  mkdirSync(evidenceDir, { recursive: true });
});

test("choice cards against isolated Python Chat: three rounds, tables, refresh restore", async ({
  page,
}) => {
  test.skip(!process.env.SEMALOOM_E2E_ISOLATED, "requires isolated Chat e2e app on :18082");
  const shot = (name: string) => page.screenshot({ path: join(evidenceDir, name), fullPage: true });
  await page.goto("/studio/?view=chat");
  await expect(page.getByLabel("业务问题")).toBeVisible({ timeout: 45_000 });
  await shot("01-chat-ready.png");

  await page.getByLabel("业务问题").fill("收入多少");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("form", { name: "业务选择" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("都不符合 / 暂不清楚")).toBeVisible();
  await expect(page.getByRole("button", { name: "其他" })).toBeVisible();

  const expiredStatus = await page.evaluate(async () => {
    const cid = sessionStorage.getItem("semaloom.chat.tenant-a.local-studio-admin");
    if (!cid) return 0;
    const conv = await (await fetch(`/v0.1/chat/conversations/${cid}`)).json();
    const csrf = document.cookie
      .split("; ")
      .find((item) => item.startsWith("semaloom_csrf="))
      ?.split("=")
      .slice(1)
      .join("=");
    const response = await fetch("/v0.1/chat/choices", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
      },
      body: JSON.stringify({
        conversationId: cid,
        questionId: conv.pendingQuestion.questionId,
        revision: conv.pendingQuestion.revision + 99,
        optionIds: [conv.pendingQuestion.options[0].id],
      }),
    });
    return response.status;
  });
  expect(expiredStatus).toBe(409);

  await page.setViewportSize({ width: 390, height: 844 });
  await shot("02-choice-390.png");
  await page.setViewportSize({ width: 1280, height: 800 });
  await shot("03-choice-1280.png");

  await page.reload();
  await expect(page.getByRole("form", { name: "业务选择" })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("收入多少")).toBeVisible();
  await expect(page.getByText("从一个业务问题开始")).toHaveCount(0);
  await shot("04-refresh-restore.png");

  const firstLive = page
    .locator(".chat-choice-option")
    .filter({ hasNotText: "都不符合" })
    .filter({ hasNotText: "其他" })
    .first();
  await firstLive.click();

  await expect(page.locator(".chat-evidence table").first()).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("引擎结果说明")).toBeVisible();
  await expect(page.getByText(/置信度/)).toBeVisible();
  await page.getByText("引擎结果说明").scrollIntoViewIfNeeded();
  await expect(page.locator(".chat-evidence pre")).toHaveCount(0);
  await shot("05-result-tables.png");
});
