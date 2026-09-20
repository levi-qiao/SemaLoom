import { expect, test } from "@playwright/test";

test("model, source and definition workflow is complete", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /选择实体 采购订单/ }).click();
  await expect(page.getByRole("complementary")).toBeVisible();
  await expect(page.getByLabel("实体描述")).toBeVisible();
  await expect(page.getByRole("button", { name: "在实体中完整编辑" })).toBeVisible();

  await page.getByRole("button", { name: /来源/ }).click();
  await page.getByLabel("试读 orderId").first().fill("PO-001");
  await page.getByRole("button", { name: "试读", exact: true }).first().click();
  await expect(page.getByText(/命中/)).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "在实体中完整编辑" }).click();
  await expect(page.getByRole("heading", { name: "实体", exact: true })).toBeVisible();
  await page.getByLabel("领域").selectOption("tax");
  await expect(page.getByRole("button", { name: /纳税人 tax.Taxpayer/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /采购订单/ })).toHaveCount(0);
  await page.getByLabel("领域").selectOption("procurement");
  await expect(page.getByRole("button", { name: /采购订单/ })).toBeVisible();
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.getByText("一行属性对应一个表字段或接口字段")).toBeVisible();
  await expect(page.getByRole("button", { name: "添加表 / 接口" })).toBeVisible();
  await expect(page.getByLabel("数据表").first()).toHaveValue("proc_order");
  await expect(page.getByRole("button", { name: "绑定 order_id" })).toBeVisible();
  await expect(page.getByText(/属性来自 2 张表\/接口/)).toBeVisible();

  const entityName = `Widget${Date.now()}`;
  await page.getByPlaceholder("显示名称，例如 仓库").fill(entityName);
  await page.getByPlaceholder("英文语义 ID，例如 Warehouse").fill(entityName);
  await page.getByRole("button", { name: "新建实体" }).click();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /判断/ }).click();
  await expect(page.getByRole("button", { name: "添加判断" })).toBeVisible();
  await page.getByRole("button", { name: "添加判断" }).click();
  await expect(page.getByLabel("判断名称")).toHaveValue("新判断");
  await expect(page.getByRole("heading", { name: "规则输入" })).toBeVisible();
  await page.getByRole("button", { name: /操作/ }).click();
  await expect(page.getByRole("button", { name: "添加操作" })).toBeVisible();
  await page.getByRole("button", { name: "添加操作" }).click();
  await expect(page.getByLabel("操作名称")).toHaveValue("新操作");
  await expect(page.getByRole("heading", { name: "参数" })).toBeVisible();

  await page.getByRole("button", { name: "数据源" }).click();
  await expect(page.getByRole("heading", { name: "Orders PostgreSQL" })).toBeVisible();
  await page.getByRole("heading", { name: "Orders PostgreSQL" }).click();
  await expect(page.getByRole("complementary", { name: "Orders PostgreSQL" })).toBeVisible();
  await expect(page.locator(".schema-list strong", { hasText: "proc_order" })).toBeVisible();

  await page.getByRole("button", { name: "实体" }).click();
  await page.getByRole("button", { name: new RegExp(entityName) }).click();
  await page.getByRole("button", { name: "删除此实体" }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();

  expect(browserErrors).toEqual([]);
});

test("chinese entity create keeps identity after save and reload", async ({ page }) => {
  const localId = `Warehouse${Date.now()}`;
  await page.goto("/studio/?view=objects");
  await expect(page.getByRole("heading", { level: 1, name: "实体" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
  await page.getByPlaceholder("显示名称，例如 仓库").fill("仓库");
  await page.getByPlaceholder("英文语义 ID，例如 Warehouse").fill(localId);
  await page.getByRole("button", { name: "新建实体" }).click();
  await expect(page.getByRole("complementary", { name: "仓库" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "仓库" }).getByText(localId).first()).toBeVisible();

  await page.getByRole("button", { name: /属性与来源/ }).click();
  const identityId = page.getByLabel("属性 ID").first();
  await expect(identityId).toHaveValue(/Id$/);
  await expect(page.getByLabel("属性类型").first()).toHaveValue("STRING");
  await expect(page.locator(".source-record-row").first().getByText("业务键")).toBeVisible();

  await page.getByRole("button", { name: "添加属性" }).click();
  const newId = page.getByLabel("属性 ID").last();
  await newId.click({ clickCount: 3 });
  await page.keyboard.type("locationCode");
  await expect(newId).toBeFocused();
  await expect(newId).toHaveValue("locationCode");

  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: new RegExp(`仓库 \\S+\\.${localId}`) })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`仓库 \\S+\\.${localId}`) }).click();
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.getByLabel("属性 ID").first()).toHaveValue(/Id$/);
  await expect(page.getByLabel("属性 ID").nth(1)).toHaveValue("locationCode");

  await page.getByRole("button", { name: "删除此实体" }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();
});

test("source verification does not overwrite in-progress connection edits", async ({ page }) => {
  await page.goto("/studio/?view=sources");
  await expect(page.getByRole("heading", { name: "数据源" })).toBeVisible();
  await expect(page.getByText("Orders PostgreSQL", { exact: true })).toBeVisible();
  await page.getByRole("heading", { name: "Orders PostgreSQL" }).click();
  const binding = page.getByLabel("环境绑定引用");
  await expect(binding).toBeVisible();
  const original = await binding.inputValue();
  expect(original.length).toBeGreaterThan(0);
  await binding.fill("env:REVIEW_MISSING_URL");
  await page.getByRole("button", { name: "检查连接" }).click();
  await expect(binding).toHaveValue("env:REVIEW_MISSING_URL");
  await expect(page.getByText("检查结果基于已保存配置，当前修改尚未保存。")).toBeVisible();
  await expect(page.getByRole("button", { name: "保存连接" })).toBeEnabled();
});

test("api mapping preview succeeds and recovers from a distinct api failure", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=procurement.Order");
  await expect(page.getByRole("complementary", { name: "采购订单" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await page.getByRole("button", { name: "/order-risk" }).click();
  const apiCard = page.locator(".mapping-card").filter({ has: page.getByLabel("接口") });
  await expect(apiCard).toBeVisible();
  await expect(apiCard.getByLabel("接口")).not.toHaveValue("");
  await apiCard.getByLabel("试读业务键 orderId").fill("PO-001");
  await expect(apiCard.getByRole("button", { name: "试读", exact: true })).toBeEnabled();
  await apiCard.getByRole("button", { name: "试读", exact: true }).click();
  await expect(apiCard.getByText(/命中/)).toBeVisible({ timeout: 15_000 });
  await expect(apiCard.getByText(/deliveryRisk=LOW|交货风险=LOW/)).toBeVisible();

  const previous = await apiCard.getByLabel("接口").inputValue();
  try {
    await apiCard.getByLabel("接口").selectOption("/health");
    await expect(apiCard.getByText("先保存再试读")).toBeVisible();
    await expect(apiCard.getByRole("button", { name: "试读", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    await apiCard.getByLabel("试读业务键 orderId").fill("PO-001");
    await apiCard.getByRole("button", { name: "试读", exact: true }).click();
    await expect(apiCard.locator(".field-error")).toContainText(/接口/, { timeout: 15_000 });
    await expect(apiCard.getByText(/数据库中没有这条记录|数据库连接失败|数据库读取失败/)).toHaveCount(0);
  } finally {
    await apiCard.getByLabel("接口").selectOption(previous);
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
  }
});

test("deep link opens the requested entity in the inspector", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("heading", { level: 1, name: "实体" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("complementary", { name: "纳税人" }).getByText("tax.Taxpayer").first()).toBeVisible();
  await expect(page.getByRole("complementary", { name: "采购订单" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /纳税人 tax.Taxpayer/ })).toHaveClass(/active/);

  await page.goto("/studio/?view=graph&entity=tax.Taxpayer");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible();
  await expect(page.getByRole("button", { name: /选择实体 纳税人/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("complementary", { name: "采购订单" })).toHaveCount(0);
});

test("small screen keeps all primary navigation reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.getByRole("button", { name: "实体", exact: true })).toBeVisible();
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
  await page.getByRole("button", { name: "图谱" }).click();
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  expect(authenticationFailures).toEqual([]);
});

test("drawing a relation keeps entity cards on the canvas", async ({ page }) => {
  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.locator(".react-flow")).toBeVisible();
  await expect(page.getByRole("button", { name: /选择实体 采购订单/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /选择实体 纳税人/ })).toBeVisible();

  const nodes = page.locator(".react-flow__node");
  const before = await nodes.count();
  expect(before).toBeGreaterThanOrEqual(5);

  const order = page.locator(".react-flow__node").filter({ hasText: "采购订单" });
  const taxpayer = page.locator(".react-flow__node").filter({ hasText: "纳税人" });
  const orderBox = await order.boundingBox();
  const taxBox = await taxpayer.boundingBox();
  expect(orderBox && taxBox).toBeTruthy();
  const separated =
    orderBox!.x + orderBox!.width < taxBox!.x ||
    taxBox!.x + taxBox!.width < orderBox!.x ||
    orderBox!.y + orderBox!.height < taxBox!.y ||
    taxBox!.y + taxBox!.height < orderBox!.y;
  expect(separated).toBeTruthy();

  const radius = await order.evaluate((node) => getComputedStyle(node.querySelector(".flow-node")!).borderRadius);
  expect(radius).toBe("8px");

  await page.getByRole("button", { name: "Fit View" }).click();
  await order.locator(".flow-node").scrollIntoViewIfNeeded();
  await taxpayer.locator(".flow-node").scrollIntoViewIfNeeded();
  await order.hover();
  const fromHandle = order.locator(".react-flow__handle-bottom");
  const toHandle = taxpayer.locator(".react-flow__handle-top");
  await fromHandle.dragTo(toHandle);

  await expect(nodes).toHaveCount(before);
  await expect(page.getByRole("button", { name: /选择实体 采购订单/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /选择实体 供应商/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /选择实体 纳税人/ })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "关系" })).toBeVisible();
  await expect(page.getByLabel("显示名称")).toHaveValue("关联");
  await expect(page.getByLabel("基数")).toHaveValue("ONE");
  const cardinalityText = await page.getByLabel("基数").evaluate((element) => {
    const select = element as HTMLSelectElement;
    return select.options[select.selectedIndex]?.text ?? "";
  });
  expect(cardinalityText).toBe("源到目标至多一个");
  await expect(page.getByText(/对应一个/)).toBeVisible();
  await expect(page.getByText("一对一")).toHaveCount(0);
});

test("studio views share shell density and do not overflow", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const views = [
    { view: "graph", heading: "图谱" },
    { view: "objects", heading: "实体" },
    { view: "sources", heading: "数据源" },
    { view: "chat", heading: "业务问答" },
  ] as const;

  for (const size of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ] as const) {
    await page.setViewportSize(size);
    for (const item of views) {
      await page.goto(`/studio/?view=${item.view}`);
      await expect(page.getByRole("heading", { name: item.heading, exact: true, level: 1 })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole("button", { name: "实体", exact: true })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      expect(overflow, `${item.view} @${size.width}`).toBeLessThanOrEqual(1);
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/studio/?view=objects");
  await expect(page.getByRole("heading", { name: "实体", exact: true, level: 1 })).toBeVisible({ timeout: 15_000 });
  const propertiesTab = page.getByRole("button", { name: /属性与来源/ });
  if (!await propertiesTab.isVisible()) {
    await page.locator(".definition-browser-list button").first().click();
  }
  await propertiesTab.click();
  await expect(page.locator(".entity-sheet").first()).toBeVisible();
  const layout = await page.evaluate(() => {
    const main = document.querySelector(".entity-sheet-main");
    const side = document.querySelector(".entity-sheet-side");
    const row = document.querySelector(".source-record-row");
    const source = row?.querySelector("[aria-label$=' 来源']");
    const col = row?.querySelector("[aria-label$=' 列']");
    const mb = main?.getBoundingClientRect();
    const sb = side?.getBoundingClientRect();
    const sr = source?.getBoundingClientRect();
    const cr = col?.getBoundingClientRect();
    const visibleInMain = (box: DOMRect | undefined) =>
      Boolean(mb && box && box.width > 8 && box.height > 8 && box.left < mb.right - 12 && box.right > mb.left + 12);
    return {
      sideRight: Boolean(mb && sb && sb.x > mb.x + 24 && Math.abs(sb.y - mb.y) < 80),
      sideWidth: sb?.width ?? 0,
      sourceInMain: !source || visibleInMain(sr),
      colInMain: visibleInMain(cr),
    };
  });
  expect(layout.sideRight).toBeTruthy();
  expect(layout.sideWidth).toBeGreaterThan(400);
  expect(layout.sourceInMain).toBeTruthy();
  expect(layout.colInMain).toBeTruthy();
  expect(pageErrors).toEqual([]);
});

test("entity mapping preview shows sample rows and switches table versus api", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/studio/?view=objects&entity=procurement.Order");
  await expect(page.getByRole("complementary", { name: "采购订单" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.getByLabel("数据表")).toHaveValue("proc_order");
  const preview = page.locator(".mapping-preview");
  await expect(preview.getByRole("button", { name: "绑定 order_id" })).toBeVisible();
  await expect(preview.locator("tbody td").first()).not.toHaveText(/样本行暂时读不到|选择表或接口后/, { timeout: 15_000 });
  const previewBox = await preview.boundingBox();
  expect(previewBox?.width ?? 0).toBeGreaterThan(400);

  await expect(page.getByRole("button", { name: /proc_order/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /order-risk/ })).toBeVisible();
  await page.getByRole("button", { name: /order-risk/ }).click();
  await expect(page.getByLabel("接口", { exact: true })).toHaveValue("/order-risk");
  await page.getByRole("button", { name: /proc_order/ }).click();
  await expect(page.getByLabel("数据表")).toHaveValue("proc_order");
  await expect(page.getByText(/属性来自 2 张表\/接口/)).toBeVisible();
});

test("entity tabs share a two-column sheet and prompt join keys", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/studio/?view=objects&entity=procurement.Order");
  await expect(page.getByRole("complementary", { name: "采购订单" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.locator(".entity-sheet").first()).toBeVisible();
  await expect(page.getByText(/属性来自 2 张表\/接口/)).toBeVisible();
  await expect(page.getByLabel("proc_order orderId 关联键").first()).toHaveValue("order_id");
  const propertyMain = await page.locator(".entity-sheet-main").first().boundingBox();
  const propertySide = await page.locator(".entity-sheet-side").first().boundingBox();
  expect(propertyMain && propertySide).toBeTruthy();
  expect(propertySide!.x).toBeGreaterThan(propertyMain!.x + 40);

  await page.getByRole("button", { name: /关系 / }).click();
  await expect(page.locator(".entity-sheet .form-grid").first()).toBeVisible();
  await expect(page.locator(".entity-dsl-container")).toBeVisible();
  const relationMain = await page.locator(".entity-sheet-main").first().boundingBox();
  const relationSide = await page.locator(".entity-sheet-side").first().boundingBox();
  expect(relationMain && relationSide).toBeTruthy();
  expect(relationSide!.x).toBeGreaterThan(relationMain!.x + 40);
  await expect(page.getByLabel("起点实体").first()).toBeVisible();
  await expect(page.getByLabel("终点实体").first()).toBeVisible();
});

test("numeric property mapping preview after save", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=procurement.Order");
  await expect(page.getByRole("complementary", { name: "采购订单" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.getByText(/合计、平均在提问时选择/)).toBeVisible();
  const amountUnit = page.getByLabel("属性单位").first();
  await expect(amountUnit).toHaveValue("CNY");
  await expect(page.getByLabel("可加性").first()).toHaveValue("FULL");

  const mapping = page.locator(".mapping-card").first();
  await expect(mapping.getByLabel("amount 列")).toHaveValue("amount");
  await mapping.getByLabel("试读业务键 orderId").fill("PO-001");
  await mapping.getByRole("button", { name: "试读", exact: true }).click();
  await expect(mapping.getByText(/命中/)).toBeVisible({ timeout: 15_000 });
});

test("published query and claims return evidence for tax and procurement", async ({ request }) => {
  const tax = await request.post("/v0.1/query", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      metric: "tax.reportedIncome",
      bindings: { taxpayerId: "TAXPAYER-A", taxYear: 2024, perspective: "TAX_RETURN" },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
    },
  });
  expect(tax.ok()).toBeTruthy();
  const taxBody = await tax.json();
  expect(taxBody.observations[0].kind).toBe("PRESENT");
  expect(taxBody.observations[0].value).not.toBe("0");
  expect(taxBody.sourceActivities[0].mappingId).toBeTruthy();
  expect(taxBody.sourceActivities[0].sourceId).toBe("tax_pg");
  expect(taxBody.releaseDigest).toBeTruthy();

  const order = await request.post("/v0.1/query", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      metric: "procurement.orderAmount",
      bindings: { orderId: "PO-001" },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
    },
  });
  expect(order.ok()).toBeTruthy();
  const orderBody = await order.json();
  expect(orderBody.observations[0].kind).toBe("PRESENT");
  expect(orderBody.observations[0].value).not.toBe("0");
  expect(orderBody.sourceActivities[0].sourceId).toBe("orders_pg");

  const taxClaim = await request.post("/v0.1/claims/evaluate", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      claimId: "tax.incomeReconciles",
      bindings: { taxpayerId: "TAXPAYER-A", taxYear: 2024 },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
      dimensions: { jurisdiction: "CN" },
    },
  });
  expect(taxClaim.ok()).toBeTruthy();
  const taxClaimBody = await taxClaim.json();
  expect(taxClaimBody.claim.truth).toBe("TRUE");
  expect(taxClaimBody.claim.evaluationId).toBeTruthy();
  expect(taxClaimBody.observations.length).toBeGreaterThan(0);

  const procClaim = await request.post("/v0.1/claims/evaluate", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      claimId: "procurement.amountWithinLimit",
      bindings: { orderId: "PO-001", organizationId: "ORG-A" },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
      dimensions: { organizationId: "ORG-A" },
    },
  });
  expect(procClaim.ok()).toBeTruthy();
  const procClaimBody = await procClaim.json();
  expect(procClaimBody.claim.truth).toBe("TRUE");
  expect(procClaimBody.releaseDigest).toBeTruthy();
});

test("fixed graph load stays within the interaction budget", async ({ page }) => {
  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  const navigationMs = await page.evaluate(
    () => performance.getEntriesByType("navigation")[0]?.duration ?? Number.POSITIVE_INFINITY,
  );
  const selectionStarted = Date.now();
  await page.getByRole("button", { name: "选择实体 供应商" }).click();
  await expect(page.getByRole("complementary", { name: "供应商" })).toBeVisible();
  const selectionMs = Date.now() - selectionStarted;

  const budget = process.env.CI ? 2_500 : 1_000;
  expect(navigationMs).toBeLessThan(budget);
  expect(selectionMs).toBeLessThan(budget);
});

async function ready(page: import("@playwright/test").Page) {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
}

test("save activates the model for public query", async ({ page, request }) => {
  test.setTimeout(60_000);
  const note = `保存即生效 ${Date.now()}`;
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("实体描述").fill(note);
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "变更" })).toHaveCount(0);

  const releases = await page.request.get("/v0.1/studio/releases");
  expect(releases.ok()).toBeTruthy();
  const activeDigest = (await releases.json()).activeDigest as string;
  expect(activeDigest.length).toBeGreaterThan(16);
  const query = await request.post("/v0.1/query", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      metric: "tax.reportedIncome",
      bindings: { taxpayerId: "TAXPAYER-A", taxYear: 2024, perspective: "TAX_RETURN" },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
    },
  });
  expect(query.ok()).toBeTruthy();
  const body = await query.json();
  expect(body.releaseDigest).toBe(activeDigest);
  expect(body.observations[0].kind).toBe("PRESENT");

  await page.reload();
  await ready(page);
  const releasesAfter = await page.request.get("/v0.1/studio/releases");
  expect((await releasesAfter.json()).activeDigest).toBe(activeDigest);
});

test("revision conflict keeps local edits recoverable", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  const description = page.getByLabel("实体描述");
  await description.fill(`冲突本地 ${Date.now()}`);
  await expect(page.getByText("有未保存修改")).toBeVisible();

  const csrf = (await page.context().cookies()).find((item) => item.name === "semaloom_csrf")?.value;
  const origin = new URL(page.url()).origin;
  const model = await page.request.get("/v0.1/studio/drafts/default");
  expect(model.ok()).toBeTruthy();
  const payload = await model.json();
  const docs = payload.documents as Array<Record<string, unknown>>;
  const taxpayer = docs.find((item) => item.id === "tax.Taxpayer");
  expect(taxpayer).toBeTruthy();
  taxpayer!.description = `冲突远端 ${Date.now()}`;
  const remote = await page.request.put("/v0.1/studio/drafts/default", {
    headers: {
      Origin: origin,
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    data: { expectedRevision: payload.revision, documents: docs },
  });
  expect(remote.ok()).toBeTruthy();

  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByRole("alert")).toContainText("保存冲突");
  await page.getByRole("button", { name: "用当前修改重试保存" }).click();
  await expect(page.getByText("已保存", { exact: true })).toBeVisible({ timeout: 15_000 });
});

test("header has no persona switcher and save is available", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await ready(page);
  await expect(page.getByLabel("本地身份")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "退出会话" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "保存" })).toBeVisible();
});

test('graph canvas toolbar creates in place and edge labels are independent of paths', async ({page})=>{
  await page.goto('/studio/?view=graph');
  await expect(page.getByLabel('图谱建模工具栏')).toBeVisible();
  await page.getByRole('button',{name:'＋ 新建实体',exact:true}).click();
  await expect(page).toHaveURL(/view=graph/);
  await expect(page.getByText('新建实体',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'连接实体',exact:true}).click();
  await expect(page.getByText('请选择起点实体',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'取消',exact:true}).last().click();
  await page.getByRole('button',{name:'自动整理',exact:true}).click();
  await expect(page.locator('.react-flow__edgelabel-renderer .edge-label').first()).toBeVisible();
  await expect(page.locator('.react-flow__edge-text')).toHaveCount(0);
});

test("api tier provides dedicated management, endpoint inspect, and auth settings", async ({ page }) => {
  await page.goto("/studio/?view=apis");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1, name: "API 接口" })).toBeVisible();
  await expect(page.getByText("API 服务列表")).toBeVisible();
  await expect(page.locator(".api-tier-page").getByText("proc_draft_api").first()).toBeVisible();

  // Click on proc_draft_api
  await page.locator(".api-tier-page").getByRole("button", { name: /proc_draft_api/ }).click();
  await expect(page.getByRole("button", { name: /端点清单/ })).toBeVisible();
  await expect(page.getByText("/order-risk")).toBeVisible();
  await expect(page.getByText("/drafts")).toBeVisible();

  // Check auth tab
  await page.getByRole("button", { name: /鉴权配置/ }).click();
  await expect(page.getByText("鉴权类型 (Authentication Scheme)")).toBeVisible();

  // Check associations tab
  await page.getByRole("button", { name: /关联管理/ }).click();
  await expect(page.getByText("关联的本体操作 (Actions)")).toBeVisible();
});

test("api online import supports openapi spec text and adds service with endpoints", async ({ page }) => {
  await page.goto("/studio/?view=apis");
  await ready(page);
  await page.getByRole("button", { name: "线上导入", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "线上导入 API" })).toBeVisible();

  // Switch to paste tab
  await page.getByRole("button", { name: "直接粘贴规范 (JSON/YAML)" }).click();
  const sampleSpec = JSON.stringify({
    openapi: "3.0.0",
    info: { title: "Payment Service", version: "1.0.0" },
    paths: {
      "/payments/charge": {
        post: {
          operationId: "chargePayment",
          summary: "扣减账户资金",
          parameters: [{ name: "amount", in: "query", required: true }],
        },
      },
    },
  });

  await page.locator(".text-import-group textarea").fill(sampleSpec);
  await page.getByRole("button", { name: "解析内容" }).click();
  await expect(page.getByText("已成功解析出 1 个接口端点：")).toBeVisible();
  await expect(page.locator(".op-path").getByText("/payments/charge")).toBeVisible();

  await page.getByRole("button", { name: "确认导入该 API 服务" }).click();
  await expect(page.getByRole("dialog", { name: "线上导入 API" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Payment Service" })).toBeVisible();
});

test("entity sheet features codemirror json dsl editor and action links api endpoints", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=procurement.Order");
  await ready(page);

  // Verify CodeMirror DSL container is visible on the right
  await expect(page.locator(".entity-dsl-container")).toBeVisible();
  await expect(page.locator(".dsl-codemirror-root")).toBeVisible();
  await expect(page.getByRole("button", { name: "实体本体 (JSON)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "关联全貌 (DSL)" })).toBeVisible();

  // Test scope switch
  await page.getByRole("button", { name: "关联全貌 (DSL)" }).click();
  await expect(page.getByRole("button", { name: "关联全貌 (DSL)" })).toHaveClass(/active/);

  // Switch to Actions tab and check API linking
  await page.getByRole("button", { name: /操作/ }).click();
  await expect(page.getByLabel("关联外部 API 接口")).toBeVisible();
  await expect(page.getByText("已绑定外部微服务")).toBeVisible();
});

