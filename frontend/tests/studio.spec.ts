import { expect, test } from "@playwright/test";

test("model, source and release workflow is complete", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "实体关系" })).toBeVisible();
  await expect(page.getByRole("button", { name: "选择实体 Purchase order" })).toBeVisible();
  await page.getByRole("button", { name: "放大图谱" }).click();
  await page.getByRole("button", { name: "适应" }).click();

  await page.getByRole("button", { name: "来源映射" }).click();
  await expect(page.getByText("/deliveryRisk", { exact: true })).toBeVisible();
  await expect(page.getByText("procurement.Order.riskApi", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "模型草稿" }).click();
  await page.getByRole("button", { name: /riskApi/ }).click();
  await expect(page.getByLabel("路径")).toHaveValue("/order-risk");
  await expect(page.getByLabel("JSON Pointer").nth(1)).toHaveValue("/deliveryRisk");
  await page.getByRole("button", { name: /Purchase order/ }).click();
  const newLabel = `Purchase order reviewed ${Date.now()}`;
  const label = page.getByLabel("显示名称");
  await label.fill(newLabel);
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText(/已保存 · r/)).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: new RegExp(newLabel) }).click();
  await expect(page.getByLabel("显示名称")).toHaveValue(newLabel);

  await page.getByRole("button", { name: "数据源" }).click();
  const sourceId = `e2e_pg_${Date.now()}`;
  await page.getByLabel("新来源 ID").fill(sourceId);
  await page.getByRole("button", { name: "注册来源" }).click();
  await expect(page.getByText(sourceId, { exact: true }).first()).toBeVisible();
  await page.getByLabel("环境绑定引用").fill("env:SEMALOOM_TAX_DATABASE_URL");
  await page.getByRole("button", { name: "保存来源配置" }).click();
  await page.getByRole("button", { name: "验证全部来源" }).click();
  await expect(page.getByText("可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("不可连接", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "校验与发布" }).click();
  await page.getByRole("button", { name: "校验候选" }).click();
  await expect(page.getByRole("button", { name: "批准候选" })).toBeVisible();
  await loginAs(page, "reviewer");
  await page.getByRole("button", { name: "批准候选" }).click();
  await loginAs(page, "publisher");
  await page.getByRole("button", { name: "发布到当前环境" }).click();
  await expect(page.getByRole("heading", { name: "发布历史" })).toBeVisible();
  await expect(page.getByText(/环境 r[1-9]/)).toBeVisible();

  expect(browserErrors).toEqual([]);
});

test("small screen keeps all primary navigation reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "实体关系" })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验与发布" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("management deep links wait for the Studio session", async ({ page }) => {
  const authenticationFailures: string[] = [];
  page.on("response", (response) => {
    if (response.status() === 401 && response.url().includes("/v0.1/studio/")) {
      authenticationFailures.push(response.url());
    }
  });

  await page.goto("/studio/?view=sources");
  await expect(page.getByText("Orders PostgreSQL", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "校验与发布" }).click();
  await expect(page.getByRole("heading", { name: "发布历史" })).toBeVisible();
  expect(authenticationFailures).toEqual([]);
});

test("fixed graph load stays within the interaction budget", async ({ page }) => {
  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "实体关系" })).toBeVisible();
  const navigationMs = await page.evaluate(
    () => performance.getEntriesByType("navigation")[0]?.duration ?? Number.POSITIVE_INFINITY,
  );
  const selectionStarted = Date.now();
  await page.getByRole("button", { name: "选择实体 Supplier" }).click();
  await expect(page.getByRole("heading", { name: "Supplier" })).toBeVisible();
  const selectionMs = Date.now() - selectionStarted;

  expect(navigationMs).toBeLessThan(1_000);
  expect(selectionMs).toBeLessThan(1_000);
});

async function loginAs(page: import("@playwright/test").Page, persona: string) {
  await page.evaluate(async (selectedPersona) => {
    const response = await fetch("/v0.1/studio/session/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona: selectedPersona }),
    });
    if (!response.ok) throw new Error(`demo login failed: ${response.status}`);
  }, persona);
}
