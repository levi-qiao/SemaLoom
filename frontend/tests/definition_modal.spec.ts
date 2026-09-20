import { test, expect } from '@playwright/test';

test('definition modal renders ontology labels and physical provenance for action and object type', async ({ page }) => {
  const actionDef = {
    kind: 'Action',
    id: 'procurement.CreatePurchaseDraft',
    label: '创建采购草稿',
    description: '在采购业务系统中生成采购草稿，经授权额度核验后可转为正式采购订单',
    targetObject: 'procurement.Order',
    effect: 'Create a purchase draft in the synthetic order system',
    preconditions: ['procurement.amountWithinLimit'],
    parameters: [
      { name: 'amount', valueType: 'DECIMAL', required: true },
      { name: 'supplierId', valueType: 'STRING', required: true },
      { name: 'note', valueType: 'STRING', required: false },
    ],
    sources: [
      {
        type: 'actionBinding',
        id: 'ab_proc_draft',
        label: '采购协同开放接口',
        sourceId: 'proc_draft_api',
        provider: 'openapi',
        resource: 'POST /drafts',
        operation: 'createPurchaseDraft',
        idempotent: true,
        reconcilable: true,
      }
    ],
    version: '1.0.0',
    apiVersion: 'semaloom/v0.1',
    releaseDigest: 'sha256:abcd1234efgh5678',
  };

  const objectDef = {
    kind: 'ObjectType',
    id: 'procurement.Order',
    label: '采购订单',
    description: '核心采购业务单据，记录采购物料、供应商、总金额及执行状态',
    sources: [
      {
        id: 'm_order',
        label: '采购主数据库',
        sourceId: 'orders_pg',
        provider: 'database',
        resource: 'proc_order',
        fields: [
          { semanticField: 'orderId', physicalField: 'order_id', role: 'KEY' },
          { semanticField: 'amount', physicalField: 'amount', role: 'MEASURE' },
          { semanticField: 'supplierId', physicalField: 'supplier_id', role: 'ATTRIBUTE' },
          { semanticField: 'status', physicalField: 'status', role: 'STATE' },
        ]
      }
    ],
    version: '1.0.0',
    apiVersion: 'semaloom/v0.1',
    releaseDigest: 'sha256:abcd1234efgh5678',
  };

  const labels = {
    'procurement.CreatePurchaseDraft': '创建采购草稿',
    'procurement.Order': '采购订单',
    'procurement.amountWithinLimit': '金额未超授权',
    amount: '金额',
    supplierId: '供应商编号',
    orderId: '订单编号',
    proc_draft_api: '采购协同开放接口',
    orders_pg: '采购主数据库',
  };

  const answer = {
    kind: 'explanation',
    textOrigin: 'AI',
    text: '查询到相关业务定义。',
    releaseDigest: 'a'.repeat(64),
    evidence: [{
      id: 'e1',
      tool: 'list_semantics',
      result: {
        definitions: [actionDef, objectDef],
        labels,
        scope: 'DECLARED_MODEL_NOT_SOURCE_OBSERVATIONS',
        hasMore: false,
      }
    }]
  };

  await page.route('**/v0.1/chat/status', r => r.fulfill({ json: { enabled: true, ready: true, model: 'offline' } }));
  await page.route('**/v0.1/chat/turns', r => r.fulfill({
    contentType: 'application/x-ndjson',
    body: JSON.stringify({ type: 'answer', answer }) + '\n' + JSON.stringify({ type: 'done' }) + '\n'
  }));

  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('有哪些采购定义?');
  await page.getByRole('button', { name: '发送', exact: true }).click();

  // Provenance is closed by default; definition inspection is available only
  // after the user deliberately opens the evidence drawer.
  await page.locator('details.evidence-card > summary').click();
  const inspectBtns = page.getByRole('button', { name: '查看定义' });
  await inspectBtns.first().click();

  const modal = page.locator('.evidence-modal');
  await expect(modal).toBeVisible();

  await expect(modal.getByRole('heading', { name: '创建采购草稿' })).toBeVisible();
  await expect(modal.getByText('procurement.CreatePurchaseDraft')).toBeVisible();
  await expect(modal.getByText('在采购业务系统中生成采购草稿，经授权额度核验后可转为正式采购订单')).toBeVisible();
  await expect(modal.getByText('采购订单').first()).toBeVisible();
  await expect(modal.getByText('金额未超授权')).toBeVisible();
  await expect(modal.getByText('前置强制核验')).toBeVisible();

  await expect(modal.getByRole('cell', { name: '金额', exact: true })).toBeVisible();
  await expect(modal.getByRole('cell', { name: '供应商编号', exact: true })).toBeVisible();
  await expect(modal.getByText('必填').first()).toBeVisible();

  await expect(modal.getByText('采购协同开放接口')).toBeVisible();
  await expect(modal.getByText('POST /drafts')).toBeVisible();
  await expect(modal.getByText('createPurchaseDraft', { exact: true })).toBeVisible();
  await expect(modal.getByText('幂等执行保障')).toBeVisible();
  await expect(modal.getByText('支持对账与补偿')).toBeVisible();

  await page.getByRole('button', { name: '关闭' }).click();
  await expect(modal).toHaveCount(0);

  await inspectBtns.nth(1).click();
  await expect(modal).toBeVisible();

  await expect(modal.getByRole('heading', { name: '采购订单' })).toBeVisible();
  await expect(modal.getByText('procurement.Order')).toBeVisible();
  await expect(modal.getByText('核心采购业务单据')).toBeVisible();

  await expect(modal.getByText('采购主数据库')).toBeVisible();
  await expect(modal.getByText('proc_order')).toBeVisible();
  await expect(modal.getByRole('cell', { name: '订单编号' })).toBeVisible();
  await expect(modal.getByRole('cell', { name: 'order_id' })).toBeVisible();
  await expect(modal.getByRole('cell', { name: '金额' })).toBeVisible();
  await expect(modal.getByRole('cell', { name: 'amount' })).toBeVisible();
});
