import { test, expect } from '@playwright/test';

test('chat separates rule definitions from evaluated claims and preserves server history', async ({ page }) => {
  const digest='a'.repeat(64);const cid='b'.repeat(32);
  const answer={kind:'answer',text:'读取成功。![external](https://example.invalid/leak)',releaseDigest:digest,
    evidence:[{id:'e1',tool:'describe_semantic',result:{kind:'Rule',id:'demo.rule',claim:'demo.claim',releaseDigest:digest}},
      {id:'e2',tool:'semantic_query',result:{releaseDigest:digest,observations:[{target:'demo.amount',value:'100.01',unit:'CNY',kind:'PRESENT'}],
        checks:[{claim:{claimId:'demo.claim',truth:'UNKNOWN'}}]}}]};
  await page.route('**/v0.1/chat/status',route=>route.fulfill({json:{enabled:true,ready:true,model:'offline-test'}}));
  await page.route('**/v0.1/chat/turns',route=>route.fulfill({contentType:'application/x-ndjson',
    body:[{type:'start',conversationId:cid,releaseDigest:digest},{type:'answer',answer},{type:'done'}].map(x=>JSON.stringify(x)).join('\n')+'\n'}));
  await page.route(`**/v0.1/chat/conversations/${cid}`,route=>route.fulfill({json:{id:cid,releaseDigest:digest,turns:[{question:'测试',answer}]}}));
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('测试');await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByText('自动规则校验：UNKNOWN')).toBeVisible();
  await expect(page.getByText('100.01 CNY')).toBeVisible();
  await expect(page.getByText('undefined')).toHaveCount(0);
  await expect(page.locator('.chat-markdown img')).toHaveCount(0);
  await page.reload();await expect(page.getByText('100.01 CNY')).toBeVisible();
  await page.getByRole('button',{name:'新建对话'}).click();
  await expect(page.getByText('从一个业务问题开始')).toBeVisible();
});

test('choice cards submit on click and other accepts inline text', async ({page}) => {
  const digest = 'a'.repeat(64);
  const cid = 'c'.repeat(32);
  const question = {
    questionId: 'q1', revision: 1, slot: 'metric',
    prompt: '你说的指标是哪种口径？', reason: '本体中该业务词对应多个指标',
    options: [
      {id: 'opt_a', label: '申报营业收入', explanation: '申报表中的营业收入', choice: {kind: 'METRIC', id: 'finance.declaredRevenue'}},
      {id: 'opt_other_input', label: '其他', explanation: '自行说明', choice: {kind: 'OTHER', id: 'free_text'}},
      {id: 'opt_abort_unclear', label: '都不符合 / 暂不清楚', explanation: '停止', choice: {kind: 'ABORT', id: 'unclear'}},
    ],
  };
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline-test'}}));
  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: [{type: 'start', conversationId: cid, releaseDigest: digest}, {type: 'choice', question, originalQuestion: '收入多少'}, {type: 'done'}].map(x => JSON.stringify(x)).join('\n') + '\n',
  }));
  let submitted: {optionIds?: string[]; otherText?: string} | null = null;
  await page.route('**/v0.1/chat/choices', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({json: {
      status: 'READY', answerReady: true, textOrigin: 'ENGINE', text: '申报营业收入合计 1.00 CNY',
      releaseDigest: digest,
      confidence: {score: 0.7, level: 'medium', label: '中', factors: [{code: 'YEAR', detail: '年份未指定，已按本体默认补齐并计入置信度'}]},
      followUps: [{label: '看平均值', message: '申报营业收入平均值'}],
      evidence: [{id: 'e1', tool: 'prepare_semantic_query', result: {values: [{metric: 'finance.declaredRevenue', aggregation: 'SUM', grain: {}, value: '1.00', unit: 'CNY'}]}}],
    }});
  });
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('收入多少');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByRole('form', {name: '业务选择'})).toBeVisible();
  await page.getByRole('button', {name: '其他', exact: true}).click();
  await page.getByLabel('其他说明').fill('申报营业收入 2024年合计');
  await page.getByRole('button', {name: '按补充说明继续'}).click();
  await expect(page.getByText('申报营业收入合计 1.00 CNY')).toBeVisible();
  await expect(page.getByText('置信度 中')).toBeVisible();
  expect(submitted?.optionIds).toEqual(['opt_other_input']);
  expect(submitted?.otherText).toBe('申报营业收入 2024年合计');
});

test('choice submit delivers engine unsupported text instead of a generic error banner', async ({page}) => {
  const digest = 'a'.repeat(64);
  const cid = 'd'.repeat(32);
  const question = {
    questionId: 'q-link', revision: 1, slot: 'metric',
    prompt: '你说的指标是哪种口径？', reason: '本体中该业务词对应多个指标',
    options: [
      {id: 'opt_a', label: '申报营业收入', explanation: '申报表中的营业收入', choice: {kind: 'METRIC', id: 'finance.declaredRevenue'}},
      {id: 'opt_abort_unclear', label: '都不符合 / 暂不清楚', explanation: '停止', choice: {kind: 'ABORT', id: 'unclear'}},
    ],
  };
  const engineText = '当前集合分析只支持同一事实表内的统计。本体中的业务关系（Link）可用于对象点查和按业务键查找关联对象，但不能在本轮直接做跨表集合 JOIN。';
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline-test'}}));
  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: [{type: 'start', conversationId: cid, releaseDigest: digest}, {type: 'choice', question, originalQuestion: '按企业合计申报营业收入'}, {type: 'done'}].map(x => JSON.stringify(x)).join('\n') + '\n',
  }));
  await page.route('**/v0.1/chat/choices', async route => {
    await route.fulfill({json: {
      status: 'UNSUPPORTED', answerReady: true, kind: 'unsupported', textOrigin: 'ENGINE',
      text: engineText, errorCode: 'LINK_ANALYSIS_UNSUPPORTED', releaseDigest: digest,
      evidence: [{id: 'e1', tool: 'prepare_semantic_query', result: {status: 'UNSUPPORTED', errorCode: 'LINK_ANALYSIS_UNSUPPORTED'}}],
    }});
  });
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('按企业合计申报营业收入');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByRole('form', {name: '业务选择'})).toBeVisible();
  await page.getByRole('button', {name: '申报营业收入'}).click();
  await expect(page.getByText(engineText)).toBeVisible();
  await expect(page.getByText('引擎结果说明', {exact: true})).toBeVisible();
  await expect(page.getByText('当前无法确定结果，请核对条件或稍后重试。')).toHaveCount(0);
  await expect(page.locator('.chat-error')).toHaveCount(0);
  const shot = process.env.SEMALOOM_UNSUPPORTED_SHOT;
  if (shot) await page.screenshot({path: shot, fullPage: true});
});

test('unconfigured chat gives a recoverable state and cannot send', async ({page})=>{
  await page.route('**/v0.1/chat/status',route=>route.fulfill({json:{enabled:false,ready:false}}));
  await page.goto('/studio/?view=chat');
  await expect(page.getByText('尚未配置模型连接。请在服务端配置 provider 后重新启动。')).toBeVisible();
  await expect(page.getByRole('button',{name:'发送',exact:true})).toBeDisabled();
});

test('population evidence shows counts, denominator and physical lineage as tables', async ({page})=>{
  await page.route('**/v0.1/chat/status',r=>r.fulfill({json:{enabled:true,ready:true,model:'offline'}}));
  const answer={kind:'answer',text:'以引擎表格为准',releaseDigest:'a'.repeat(64),evidence:[{id:'e1',tool:'analyze_population',lineage:[{id:'demo.mapping',sourceId:'demo_pg',resource:'annual_returns',fields:[{semanticField:'demo.profit',physicalField:'profit_amount',role:'value'}]}],result:{kind:'PopulationAnalysis',label:'年度利润',value:'100.01',unit:'CNY',operation:'mean',year:2025,populationCount:3,observedCount:3,missingCount:0,complete:true,comparison:{operation:'outperforms',value:'50',unit:'%',numerator:'1',denominator:'2',formula:'strictly better / peers * 100'},members:[{identity:{id:'C1'},properties:{name:'示例企业'},observation:{value:'100.01',unit:'CNY',kind:'PRESENT'}}]}}]};
  await page.route('**/v0.1/chat/turns',r=>r.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'answer',answer})+'\n'+JSON.stringify({type:'done'})+'\n'}));
  await page.goto('/studio/?view=chat');await page.getByLabel('业务问题').fill('平均利润');await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByRole('cell',{name:'annual_returns',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'profit_amount',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'分母',exact:true})).toBeVisible();
  await expect(page.locator('.chat-evidence pre')).toHaveCount(0);
  await page.getByText('业务定义与统计口径',{exact:true}).click();
  await expect(page.getByRole('cell',{name:'有效数量',exact:true})).toBeVisible();
});

test('ontology explanations show definition tables and keep the answer beginning visible', async ({page})=>{
  const definition={kind:'Metric',id:'inventory.stock',label:'库存数量',perspective:'WAREHOUSE',unit:'EA',description:'当前版本声明的库存口径'};
  const answer={kind:'explanation',textOrigin:'AI',text:'可以围绕当前库存模型提问。\n\n'+Array(30).fill('这是本体的说明，实际数值需要查询。').join('\n\n'),releaseDigest:'a'.repeat(64),evidence:[{id:'e1',tool:'list_semantics',result:{definitions:[definition],scope:'DECLARED_MODEL_NOT_SOURCE_OBSERVATIONS',hasMore:false}}]};
  await page.route('**/v0.1/chat/status',r=>r.fulfill({json:{enabled:true,ready:true,model:'offline'}}));
  await page.route('**/v0.1/chat/turns',r=>r.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'answer',answer})+'\n'+JSON.stringify({type:'done'})+'\n'}));
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('有哪些数据可问?');
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await expect(page.getByText('本体说明 · AI 解读，非数据查询结果',{exact:true})).toBeInViewport();
  await expect(page.getByText('可以围绕当前库存模型提问。',{exact:true})).toBeInViewport();
  await page.getByText(/当前业务模型目录/).click();
  await expect(page.getByRole('cell',{name:'当前版本声明的库存口径',exact:true})).toBeVisible();
  expect(await page.locator('.ontology-catalog > .evidence-table-wrap').evaluate(e=>e.getBoundingClientRect().height)).toBeLessThanOrEqual(361);
  await page.getByRole('button', {name: '查看定义'}).click();
  await expect(page.locator('.evidence-modal')).toBeVisible();
  await expect(page.locator('.evidence-modal').getByText('inventory.stock')).toBeVisible();
  await page.getByRole('button', {name: '关闭'}).click();
  await expect(page.locator('.evidence-modal')).toHaveCount(0);
  await expect(page.locator('.chat-evidence pre')).toHaveCount(0);
});
