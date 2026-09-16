import { test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const outDir = join(process.cwd(), 'test-results', 'visual');

test('capture chat ui layout screenshots', async ({ page }) => {
  mkdirSync(outDir, { recursive: true });
  await page.setViewportSize({ width: 1920, height: 1080 });

  // 1. Visit chat page
  await page.goto('/studio/?view=chat');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: join(outDir, '01-empty-state.png'), fullPage: true });

  // 2. Mock realistic ontology explanation turn like user's screenshot
  const definition1 = { kind: 'ObjectType', id: 'procurement.Order', label: '采购订单', description: '企业向供应商发出的采购订单，用订单编号标识。金额、数量来自订单库，交货风险来自独立接口。' };
  const definition2 = { kind: 'Metric', id: 'inventory.stock', label: '库存数量', perspective: 'WAREHOUSE', unit: 'EA', description: '当前版本声明的库存口径' };
  const definition3 = { kind: 'Rule', id: 'procurement.amountWithinLimit', label: '金额未超授权', description: '判断采购订单金额是否不超过该组织的授权额度。成立后才允许创建采购草稿。' };
  const definition4 = { kind: 'Action', id: 'procurement.CreatePurchaseDraft', label: '创建采购草稿', description: '在满足授权额度与审批要求后生成草稿' };

  const answer = {
    kind: 'explanation',
    textOrigin: 'AI',
    text: `系统支持采购域和税务域的业务概念与数据分析：\n\n- **采购域**：支持采购订单（\`procurement.Order\`）、供应商（\`procurement.Supplier\`）、采购组织（\`procurement.Organization\`）等核心实体。\n- **税务域**：支持纳税人（\`tax.Taxpayer\`）、纳税申报（\`tax.Filing\`）等实体与核对规则。\n\n所有概念均具备确定的属性与度量，您可以通过自然语言提问具体金额、风险或核对关系。`,
    releaseDigest: 'a'.repeat(64),
    evidence: [{
      id: 'e1',
      tool: 'list_semantics',
      result: {
        definitions: [definition1, definition2, definition3, definition4],
        scope: 'DECLARED_MODEL_NOT_SOURCE_OBSERVATIONS',
        hasMore: false,
      }
    }]
  };

  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: JSON.stringify({ type: 'answer', answer }) + '\n' + JSON.stringify({ type: 'done' }) + '\n',
  }));

  await page.getByLabel('业务问题').fill('有哪些数据可问？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForTimeout(500);

  // Screenshot 2: Default collapsed evidence card
  await page.screenshot({ path: join(outDir, '02-collapsed-chat.png'), fullPage: true });

  // 3. Expand catalog
  await page.getByText(/当前业务模型目录/).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(outDir, '03-expanded-catalog.png'), fullPage: true });

  // 4. Click inspect definition modal
  const inspectButtons = page.getByRole('button', { name: '查看定义' });
  await inspectButtons.first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(outDir, '04-definition-modal.png'), fullPage: true });
});

test('capture complex query result layout', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });

  const answer = {
    kind: 'answer',
    text: `### 采购订单金额最高供应商分析\n\n根据系统采购与交货风险数据，前三个供应商的金额与交货风险汇总如下：\n\n| 供应商名称 | 采购订单号 | 订单金额 (CNY) | 交货风险评级 | 风险状态 |\n| :--- | :--- | :--- | :--- | :--- |\n| **北京信源科技** | \`PO-2025-001\` | **520,000.00** | 低风险 (\`0.12\`) | 正常履约 |\n| **上海华泰制造** | \`PO-2025-003\` | **380,000.00** | 中风险 (\`0.45\`) | 关注账期 |\n| **深圳联创微电** | \`PO-2025-002\` | **210,000.00** | 低风险 (\`0.18\`) | 正常履约 |\n\n> **核心结论**：北京信源科技订单金额最高（52.00 万元），风险指标处于低位，履约表现良好。`,
    releaseDigest: 'a'.repeat(64),
    confidence: {
      score: 0.88,
      level: 'high',
      label: '高',
      factors: [
        { code: 'CORROBORATED', detail: '已关联采购订单表与外部交货风险 API 进行交叉验证' },
        { code: 'TIME_SYNC', detail: '来源观测时间与当前快照一致' }
      ]
    },
    evidence: [
      {
        id: 'e1',
        tool: 'find_objects',
        result: {
          releaseDigest: 'a'.repeat(64),
          objects: [
            { identity: { id: 'PO-2025-001' }, properties: { supplier: '北京信源科技', amount: '520000.00', risk: '0.12' } },
            { identity: { id: 'PO-2025-003' }, properties: { supplier: '上海华泰制造', amount: '380000.00', risk: '0.45' } },
            { identity: { id: 'PO-2025-002' }, properties: { supplier: '深圳联创微电', amount: '210000.00', risk: '0.18' } }
          ]
        }
      },
      {
        id: 'e2',
        tool: 'evaluate_claim',
        result: {
          releaseDigest: 'a'.repeat(64),
          claim: {
            claimId: 'procurement.amountWithinLimit',
            truth: 'TRUE',
            reason: '各笔采购订单金额均在对应组织授权限额（1,000,000.00 CNY）内'
          },
          observations: [
            { target: 'PO-2025-001', value: '520000.00', unit: 'CNY', kind: 'PRESENT', observedAt: '2025-05-10T10:00:00Z' }
          ]
        }
      }
    ]
  };

  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: JSON.stringify({ type: 'answer', answer }) + '\n' + JSON.stringify({ type: 'done' }) + '\n',
  }));

  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('采购订单金额最高的前三个供应商是谁？他们的交货风险如何？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForTimeout(500);

  await page.screenshot({ path: join(outDir, '05-query-result-layout.png'), fullPage: true });
});
