import { expect, test } from "@playwright/test";

test("model, source and definition workflow is complete", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/studio/?view=graph");
  await expect(page.getByRole("heading", { name: "图谱" })).toBeVisible();
  await expect(page.getByText("已同步")).toBeVisible({ timeout: 15_000 });
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
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "数据源" }).click();
  await expect(page.getByRole("heading", { name: "Orders PostgreSQL" })).toBeVisible();
  await page.getByRole("heading", { name: "Orders PostgreSQL" }).click();
  await expect(page.getByRole("complementary", { name: "Orders PostgreSQL" })).toBeVisible();
  await expect(page.locator(".schema-list strong", { hasText: "proc_order" })).toBeVisible();

  await page.getByRole("button", { name: "实体" }).click();
  await page.getByRole("button", { name: new RegExp(entityName) }).click();
  await page.getByRole("button", { name: "删除此实体" }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();

  expect(browserErrors).toEqual([]);
});

test("chinese entity create keeps identity after save and reload", async ({ page }) => {
  const localId = `Warehouse${Date.now()}`;
  await page.goto("/studio/?view=objects");
  await expect(page.getByRole("heading", { level: 1, name: "实体" })).toBeVisible();
  await expect(page.getByText("已同步")).toBeVisible({ timeout: 15_000 });
  await page.getByPlaceholder("显示名称，例如 仓库").fill("仓库");
  await page.getByPlaceholder("英文语义 ID，例如 Warehouse").fill(localId);
  await page.getByRole("button", { name: "新建实体" }).click();
  await expect(page.getByRole("complementary", { name: "仓库" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "仓库" }).getByText(localId)).toBeVisible();

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

  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: new RegExp(`仓库 \\S+\\.${localId}`) })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`仓库 \\S+\\.${localId}`) }).click();
  await page.getByRole("button", { name: /属性与来源/ }).click();
  await expect(page.getByLabel("属性 ID").first()).toHaveValue(/Id$/);
  await expect(page.getByLabel("属性 ID").nth(1)).toHaveValue("locationCode");

  await page.getByRole("button", { name: "删除此实体" }).click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
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
  await apiCard.getByPlaceholder("例如 PO-001").fill("PO-001");
  await expect(apiCard.getByRole("button", { name: "试读", exact: true })).toBeEnabled();
  await apiCard.getByRole("button", { name: "试读", exact: true }).click();
  await expect(apiCard.getByText(/命中/)).toBeVisible({ timeout: 15_000 });
  await expect(apiCard.getByText(/deliveryRisk=LOW|交货风险=LOW/)).toBeVisible();

  const previous = await apiCard.getByLabel("接口").inputValue();
  try {
    await apiCard.getByLabel("接口").selectOption("/health");
    await expect(apiCard.getByText("先保存草稿再试读")).toBeVisible();
    await expect(apiCard.getByRole("button", { name: "试读", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "草稿保存" }).click();
    await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
    await apiCard.getByPlaceholder("例如 PO-001").fill("PO-001");
    await apiCard.getByRole("button", { name: "试读", exact: true }).click();
    await expect(apiCard.locator(".field-error")).toContainText(/接口/, { timeout: 15_000 });
    await expect(apiCard.getByText(/数据库中没有这条记录|数据库连接失败|数据库读取失败/)).toHaveCount(0);
  } finally {
    await apiCard.getByLabel("接口").selectOption(previous);
    await page.getByRole("button", { name: "草稿保存" }).click();
    await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
  }
});

test("deep link opens the requested entity in the inspector", async ({ page }) => {
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("heading", { level: 1, name: "实体" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("complementary", { name: "纳税人" }).getByText("tax.Taxpayer")).toBeVisible();
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
    { view: "release", heading: "变更与发布" },
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
  await expect(page.locator(".sheet-help").getByText("关系", { exact: true })).toBeVisible();
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

  const mapping = page.locator(".mapping-card").first();
  await expect(mapping.getByLabel("amount 列")).toHaveValue("amount");
  await mapping.getByPlaceholder("例如 PO-001").fill("PO-001");
  await mapping.getByRole("button", { name: "试读", exact: true }).click();
  await expect(mapping.getByText(/命中/)).toBeVisible({ timeout: 15_000 });
});

test("published query and claims return evidence for tax and procurement", async ({ request }) => {
  const tax = await request.post("/v0.1/query", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      metric: "tax.reportedIncome",
      bindings: { taxpayer: "TAXPAYER-A", taxYear: 2024, perspective: "TAX_RETURN" },
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
      bindings: { taxpayer: "TAXPAYER-A", taxYear: 2024 },
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
  await expect(page.getByText(/已同步|已重新载入|已切换为/)).toBeVisible({ timeout: 15_000 });
}

async function switchPersona(page: import("@playwright/test").Page, persona: string) {
  await page.getByLabel("本地身份").selectOption(persona);
  await expect(page.getByText(`已切换为 ${persona}`)).toBeVisible({ timeout: 15_000 });
}

async function validateCandidate(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "校验候选" }).click();
  await expect(page.getByText(/验证：通过|验证：失败/)).toBeVisible({ timeout: 15_000 });
  if (await page.getByText("验证：失败").isVisible()) {
    await page.getByRole("button", { name: "检查来源连接" }).click();
    await expect(page.getByText(/来源检查已完成/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "校验候选" }).click();
  }
  await expect(page.getByText("验证：通过")).toBeVisible({ timeout: 15_000 });
}

test("draft save validate independent review publish and public query use the digest", async ({ page, request }) => {
  test.setTimeout(60_000);
  const note = `G3 发布说明 ${Date.now()}`;
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("实体描述").fill(note);
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
  await expect(page.getByText("已发布", { exact: true })).toHaveCount(0);
  await expect(page.getByText("发布：已发布")).toHaveCount(0);

  await page.getByRole("button", { name: "变更" }).click();
  await expect(page.getByRole("heading", { name: "变更与发布" })).toBeVisible();
  await expect(page.getByText("tax.Taxpayer")).toBeVisible();
  await validateCandidate(page);

  await page.getByRole("button", { name: "批准候选" }).click();
  await expect(page.getByRole("alert")).toContainText("INDEPENDENT_REVIEW_REQUIRED");
  await expect(page.getByRole("alert")).toContainText("作者不能批准自己的候选");

  await switchPersona(page, "reviewer");
  await expect(page.getByRole("button", { name: "校验候选" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发布到当前环境" })).toHaveCount(0);
  await page.getByRole("button", { name: "批准候选" }).click();
  await expect(page.getByText(/已独立批准/)).toBeVisible();

  await switchPersona(page, "publisher");
  await expect(page.getByRole("button", { name: "批准候选" })).toHaveCount(0);
  const candidate = (await page.getByLabel("candidateDigest").innerText()).trim();
  expect(candidate.length).toBeGreaterThan(16);
  await page.getByRole("button", { name: "发布到当前环境" }).click();
  await expect(page.getByText("发布：已发布")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByLabel("activeDigest")).toHaveText(candidate);
  await expect(page.getByText(new RegExp(`已激活 ${candidate}`))).toBeVisible();

  const releases = await page.request.get("/v0.1/studio/releases");
  expect(releases.ok()).toBeTruthy();
  expect((await releases.json()).activeDigest).toBe(candidate);

  const query = await request.post("/v0.1/query", {
    headers: { Authorization: "Bearer tenant-a-analyst" },
    data: {
      metric: "tax.reportedIncome",
      bindings: { taxpayer: "TAXPAYER-A", taxYear: 2024, perspective: "TAX_RETURN" },
      periodFrom: "2024-01-01",
      periodTo: "2025-01-01",
    },
  });
  expect(query.ok()).toBeTruthy();
  const body = await query.json();
  expect(body.releaseDigest).toBe(candidate);
  expect(body.observations[0].kind).toBe("PRESENT");

  await page.reload();
  await ready(page);
  await expect(page.getByLabel("activeDigest")).toHaveText(candidate);
  await expect(page.getByLabel("candidateDigest")).toHaveText(candidate);
});

test("stale revision and source change require a new validation", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/studio/?view=objects&entity=tax.Taxpayer");
  await expect(page.getByRole("complementary", { name: "纳税人" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("实体描述").fill(`G3 过期校验 ${Date.now()}`);
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "变更" }).click();
  await validateCandidate(page);

  await page.getByRole("button", { name: "实体" }).click();
  await page.getByLabel("实体描述").fill(`G3 过期校验再改 ${Date.now()}`);
  await page.getByRole("button", { name: "草稿保存" }).click();
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "变更" }).click();
  await expect(page.getByText("验证：过期")).toBeVisible();
  await expect(page.getByText("发布：已批准")).toHaveCount(0);

  await switchPersona(page, "reviewer");
  await page.getByRole("button", { name: "批准候选" }).click();
  await expect(page.getByRole("alert")).toContainText("VALIDATION_REQUIRED");

  await switchPersona(page, "studio-admin");
  await validateCandidate(page);

  await page.getByRole("button", { name: "数据源" }).click();
  await page.getByRole("heading", { name: "Tax PostgreSQL" }).click();
  const label = page.getByLabel("显示名称");
  const original = await label.inputValue();
  try {
    await label.fill(`${original} g3`);
    await page.getByRole("button", { name: "保存连接" }).click();
    await expect(page.getByRole("button", { name: "保存连接" })).toBeDisabled();
    await page.getByRole("button", { name: "变更" }).click();
    await expect(page.getByText("验证：过期")).toBeVisible();
    await switchPersona(page, "reviewer");
    await page.getByRole("button", { name: "批准候选" }).click();
    await expect(page.getByRole("alert")).toContainText("VALIDATION_REQUIRED");
    await switchPersona(page, "studio-admin");
    await validateCandidate(page);
    await switchPersona(page, "reviewer");
    await page.getByRole("button", { name: "批准候选" }).click();
    await expect(page.getByText(/已独立批准/)).toBeVisible();
  } finally {
    await switchPersona(page, "studio-admin");
    await page.getByRole("button", { name: "数据源" }).click();
    await page.getByRole("heading", { name: /Tax PostgreSQL/ }).first().click();
    const restore = page.getByLabel("显示名称");
    await restore.fill(original);
    if (await page.getByRole("button", { name: "保存连接" }).isEnabled()) {
      await page.getByRole("button", { name: "保存连接" }).click();
      await expect(page.getByRole("button", { name: "保存连接" })).toBeDisabled();
    }
  }
});

test("viewer has no release controls and logout rejects the next write", async ({ page }) => {
  await page.goto("/studio/?view=release");
  await expect(page.getByRole("heading", { name: "变更与发布" })).toBeVisible();
  await ready(page);
  await page.getByRole("button", { name: "退出会话" }).click();
  await expect(page.getByText("已退出会话")).toBeVisible();
  await page.getByRole("button", { name: "校验候选" }).click();
  await expect(page.getByRole("alert")).toContainText(/会话已失效|UNAUTHENTICATED|SESSION_/);

  await switchPersona(page, "viewer");
  await expect(page.getByRole("button", { name: "校验候选" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "批准候选" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发布到当前环境" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "草稿保存" })).toHaveCount(0);
  await expect(page.getByText("只读，无管理操作")).toBeVisible();

  const origin = new URL(page.url()).origin;
  const csrf = (await page.context().cookies()).find((item) => item.name === "semaloom_csrf")?.value;
  const denied = await page.request.post("/v0.1/studio/drafts/default/validate", {
    headers: {
      Origin: origin,
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
  });
  expect(denied.status()).toBe(403);
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
