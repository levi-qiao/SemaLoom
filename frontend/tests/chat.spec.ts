import { test, expect } from '@playwright/test';

test('chat separates rule definitions from evaluated claims and preserves server history', async ({ page }) => {
  const digest='a'.repeat(64);const cid='b'.repeat(32);
  const answer={kind:'answer',text:'读取成功。![external](https://example.invalid/leak)',releaseDigest:digest,
    presentation:{version:'semaloom/presentation-v0.1',metrics:'invalid'},
    evidence:[{id:'e1',tool:'describe_semantic',result:{kind:'Rule',id:'demo.rule',claim:'demo.claim',releaseDigest:digest}},
      {id:'e2',tool:'semantic_query',result:{releaseDigest:digest,observations:[{target:'demo.amount',value:'100.01',unit:'CNY',kind:'PRESENT'}],
        checks:[{claim:{claimId:'demo.claim',truth:'UNKNOWN'}}]}}]};
  await page.route('**/v0.1/chat/status',route=>route.fulfill({json:{enabled:true,ready:true,model:'offline-test'}}));
  await page.route('**/v0.1/chat/turns',route=>route.fulfill({contentType:'application/x-ndjson',
    body:[{type:'start',conversationId:cid,releaseDigest:digest},{type:'answer',answer},{type:'done'}].map(x=>JSON.stringify(x)).join('\n')+'\n'}));
  await page.route(`**/v0.1/chat/conversations/${cid}`,route=>route.fulfill({json:{id:cid,releaseDigest:digest,turns:[{question:'测试',answer}]}}));
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('测试');await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.locator('.evidence-card > summary').nth(1).click();
  await expect(page.getByText('自动规则校验：UNKNOWN')).toBeVisible();
  await expect(page.getByText('100.01 CNY')).toBeVisible();
  await expect(page.getByText('undefined')).toHaveCount(0);
  await expect(page.getByRole('region',{name:'业务结果概览'})).toHaveCount(0);
  await expect(page.locator('.chat-markdown img')).toHaveCount(0);
  await page.reload();
  await page.locator('.evidence-card > summary').nth(1).click();
  await expect(page.getByText('100.01 CNY')).toBeVisible();
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

test('collection evidence shows counts, denominator and physical lineage as tables', async ({page})=>{
  await page.route('**/v0.1/chat/status',r=>r.fulfill({json:{enabled:true,ready:true,model:'offline'}}));
  const answer={kind:'answer',text:'以引擎表格为准',releaseDigest:'a'.repeat(64),evidence:[{id:'e1',tool:'prepare_semantic_query',lineage:[{id:'demo.mapping',sourceId:'demo_pg',resource:'annual_returns',fields:[{semanticField:'demo.profit',physicalField:'profit_amount',role:'value'}]}],result:{values:[{metric:'demo.profit',aggregation:'AVG',grain:{},value:'100.01',unit:'CNY'}],scope:{populationCount:3,observedCount:3,missingCount:0,complete:true,comparison:{operation:'outperforms',value:'50',unit:'%',numerator:'1',denominator:'2',formula:'strictly better / peers * 100'}}}}]};
  await page.route('**/v0.1/chat/turns',r=>r.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'answer',answer})+'\n'+JSON.stringify({type:'done'})+'\n'}));
  await page.goto('/studio/?view=chat');await page.getByLabel('业务问题').fill('平均利润');await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.locator('.evidence-card > summary').click();
  await expect(page.getByRole('cell',{name:'annual_returns',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'profit_amount',exact:true})).toBeVisible();
  await expect(page.getByRole('cell',{name:'分母',exact:true})).toBeVisible();
  await expect(page.locator('.chat-evidence pre')).toHaveCount(0);
  await page.getByText('业务定义与统计口径',{exact:true}).click();
  await expect(page.getByRole('cell',{name:'有效数量',exact:true})).toBeVisible();
});

test('authorized engine rows render as exact metrics with smooth chart and table views', async ({page}) => {
  const digest = 'a'.repeat(64);
  const answer = {
    kind: 'answer', textOrigin: 'ENGINE', text: '按年度展示已授权营业收入。', releaseDigest: digest,
    evidence: [{
      id: 'e-report', tool: 'prepare_semantic_query', result: {
        labels: {'finance.revenue': '营业收入'},
        values: [
          {metric: 'finance.revenue', aggregation: 'SUM', grain: {year: 2023}, value: '928.5000', unit: 'CNY'},
          {metric: 'finance.revenue', aggregation: 'SUM', grain: {year: 2024}, value: '1200.0000', unit: 'CNY'},
          {metric: 'finance.revenue', aggregation: 'SUM', grain: {year: 2025}, value: '1468.2500', unit: 'CNY'},
        ],
        evidence: {
          title: '年度营业收入',
          columns: [{id: 'year', label: '年度'}, {id: 'revenue', label: '营业收入'}, {id: 'orders', label: '订单数'}],
          rows: [['2023', '928.5000', '18'], ['2024', '1200.0000', '24'], ['2025', '1468.2500', '29']],
        },
      },
    }],
    presentation: {
      version: 'semaloom/presentation-v0.1',
      metrics: [
        {id: 'm-2023', label: '营业收入', value: '928.5000', displayValue: '928.5', unit: 'CNY', meta: '合计 · 2023', tone: 'neutral'},
        {id: 'm-2024', label: '营业收入', value: '1200.0000', displayValue: '1200', unit: 'CNY', meta: '合计 · 2024', tone: 'neutral'},
        {id: 'm-2025', label: '营业收入', value: '1468.2500', displayValue: '1468.25', unit: 'CNY', meta: '合计 · 2025', tone: 'neutral'},
      ],
      reports: [{
        id: 'report-annual', title: '年度营业收入',
        description: '图形与表格使用同一组引擎结果；切换视图不会重新计算。',
        columns: [
          {key: 'c0', semanticId: 'year', label: '年度', role: 'CATEGORY', valueType: 'INTEGER', unit: null},
          {key: 'c1', semanticId: 'revenue', label: '营业收入', role: 'MEASURE', valueType: 'DECIMAL', unit: 'CNY'},
          {key: 'c2', semanticId: 'orders', label: '订单数', role: 'MEASURE', valueType: 'INTEGER', unit: 'count'},
        ],
        rows: [
          {c0: '2023', c1: '928.5', c2: '18'},
          {c0: '2024', c1: '1200', c2: '24'},
          {c0: '2025', c1: '1468.25', c2: '29'},
        ],
        categoryKey: 'c0',
        series: [{key: 'c1', label: '营业收入', unit: 'CNY'}, {key: 'c2', label: '订单数', unit: 'count'}],
        preferredView: 'line',
        truncated: false, rowCount: 3,
      }],
    },
  };
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline'}}));
  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: JSON.stringify({type: 'answer', answer}) + '\n' + JSON.stringify({type: 'done'}) + '\n',
  }));
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('按年度看营业收入');
  await page.getByRole('button', {name: '发送', exact: true}).click();

  const result = page.getByRole('region', {name: '业务结果概览'});
  await expect(result).toBeVisible();
  await expect(result.getByText('1200', {exact: true})).toBeVisible();
  await expect(result.getByText('1200.0000', {exact: true})).toHaveCount(0);
  await expect(result.locator('.result-view-tabs [role="tab"][aria-selected="true"]')).toHaveText('趋势');
  await expect(result.locator('.result-chart[role="img"]')).toBeVisible();
  await expect(result.locator('.recharts-line')).toHaveCount(2);
  await result.getByLabel('图表指标').selectOption({label: '营业收入'});
  await expect(result.locator('.recharts-line')).toHaveCount(1);
  await result.getByLabel('图表指标').selectOption({label: '全部指标'});
  await result.getByRole('tab', {name: '柱状'}).click();
  await expect(result.locator('.recharts-rectangle')).toHaveCount(6);

  await result.getByRole('tab', {name: '表格'}).click();
  await expect(result.getByRole('cell', {name: '1468.25', exact: true})).toBeVisible();
  await result.getByRole('tab', {name: '趋势'}).focus();
  await page.keyboard.press('Enter');
  await expect(result.getByRole('tab', {name: '趋势'})).toHaveAttribute('aria-selected', 'true');
  await expect(result.locator('.recharts-line')).toHaveCount(2);

  await page.setViewportSize({width: 390, height: 844});
  await expect(result).toBeVisible();
  const box = await result.boundingBox();
  expect(box?.width ?? 999).toBeLessThanOrEqual(362);
  const shot = process.env.SEMALOOM_RESULT_PRESENTATION_SHOT;
  if (shot) {
    await result.scrollIntoViewIfNeeded();
    await page.screenshot({path: shot});
  }
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
  await expect(page.getByRole('cell',{name:'当前版本声明的库存口径',exact:true})).toBeVisible();
  expect(await page.locator('.ontology-catalog > .evidence-table-wrap').evaluate(e=>e.getBoundingClientRect().height)).toBeLessThanOrEqual(361);
  await page.getByRole('button', {name: '查看定义'}).click();
  await expect(page.locator('.evidence-modal')).toBeVisible();
  await expect(page.locator('.evidence-modal').getByText('inventory.stock')).toBeVisible();
  await page.getByRole('button', {name: '关闭'}).click();
  await expect(page.locator('.evidence-modal')).toHaveCount(0);
  await expect(page.locator('.chat-evidence pre')).toHaveCount(0);
});

test('dimension questions use the server-owned select without duplicate cards', async ({page}) => {
  const digest = 'a'.repeat(64);
  const cid = 'e'.repeat(32);
  const question = {
    questionId: 'q-dim', revision: 1, slot: 'dimension', control: 'SELECT',
    prompt: '请选择区域', reason: '这个问题依赖本体配置的取值字典',
    options: [
      {id: 'opt_east', label: '华东区', explanation: '本体字典取值', choice: {kind: 'DIMENSION_VALUE', id: 'EAST'}},
      {id: 'opt_north', label: '华北区', explanation: '本体字典取值', choice: {kind: 'DIMENSION_VALUE', id: 'NORTH'}},
      {id: 'opt_other_input', label: '其他', explanation: '自行说明', choice: {kind: 'OTHER', id: 'free_text'}},
      {id: 'opt_abort_unclear', label: '都不符合 / 暂不清楚', explanation: '停止', choice: {kind: 'ABORT', id: 'unclear'}},
    ],
  };
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline-test'}}));
  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: [{type: 'start', conversationId: cid, releaseDigest: digest}, {type: 'choice', question, originalQuestion: '区域采购额'}, {type: 'done'}].map(x => JSON.stringify(x)).join('\n') + '\n',
  }));
  let submitted: {optionIds?: string[]} | null = null;
  await page.route('**/v0.1/chat/choices', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({json: {
      status: 'READY', answerReady: true, textOrigin: 'ENGINE', text: '华东区采购额合计 150.01 CNY',
      releaseDigest: digest,
      evidence: [{id: 'e1', tool: 'prepare_semantic_query', result: {values: [{value: '150.01', unit: 'CNY'}]}}],
    }});
  });
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('区域采购额');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByRole('form', {name: '业务选择'})).toBeVisible();
  await expect(page.getByRole('combobox', {name: '请选择区域'})).toBeVisible();
  await expect(page.locator('.chat-choice-cards')).toHaveCount(0);
  await page.getByRole('combobox', {name: '请选择区域'}).selectOption('opt_east');
  await expect(page.getByText('华东区采购额合计 150.01 CNY')).toBeVisible();
  expect(submitted?.optionIds).toEqual(['opt_east']);
});

test('claim subject questions expose an object select', async ({page}) => {
  const digest = 'a'.repeat(64);
  const cid = 'f'.repeat(32);
  const question = {
    questionId: 'q-claim-subject', revision: 1, slot: 'claimSubject',
    prompt: '要核验哪个对象？', reason: '判断必须钉到唯一对象',
    options: [
      {id: 'opt_a', label: 'Demo Co', explanation: '当前筛选范围内的对象', choice: {kind: 'SUBJECT', id: 'TAXPAYER-A', field: 'taxpayerId'}},
      {id: 'opt_b', label: 'Gap Co', explanation: '当前筛选范围内的对象', choice: {kind: 'SUBJECT', id: 'TAXPAYER-B', field: 'taxpayerId'}},
      {id: 'opt_abort_unclear', label: '都不符合 / 暂不清楚', explanation: '停止', choice: {kind: 'ABORT', id: 'unclear'}},
    ],
  };
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline-test'}}));
  await page.route('**/v0.1/chat/turns', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: [{type: 'start', conversationId: cid, releaseDigest: digest}, {type: 'choice', question, originalQuestion: '收入是否一致'}, {type: 'done'}].map(x => JSON.stringify(x)).join('\n') + '\n',
  }));
  let submitted: {optionIds?: string[]} | null = null;
  await page.route('**/v0.1/chat/choices', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({json: {
      status: 'READY', answerReady: true, textOrigin: 'ENGINE', text: '规则校验通过',
      releaseDigest: digest, tool: 'evaluate_claim',
      evidence: [{id: 'e1', tool: 'evaluate_claim', result: {claim: {truth: 'TRUE'}}}],
    }});
  });
  await page.goto('/studio/?view=chat');
  await page.getByLabel('业务问题').fill('收入是否一致');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByRole('form', {name: '业务选择'})).toBeVisible();
  await expect(page.getByRole('combobox', {name: '要核验哪个对象？'})).toBeVisible();
  await page.getByRole('combobox', {name: '要核验哪个对象？'}).selectOption('opt_a');
  await expect(page.getByText('规则校验通过')).toBeVisible();
  expect(submitted?.optionIds).toEqual(['opt_a']);
});

test('chat history drawer lists past conversations and switches active conversation', async ({page}) => {
  const digest = 'a'.repeat(64);
  const conv1 = 'c1'.padEnd(32, '0');
  const conv2 = 'c2'.padEnd(32, '0');
  await page.route('**/v0.1/chat/status', route => route.fulfill({json: {enabled: true, ready: true, model: 'offline-test'}}));
  await page.route('**/v0.1/chat/conversations', route => route.fulfill({
    json: {
      conversations: [
        {id: conv1, releaseDigest: digest, updatedAt: '2026-09-20T10:00:00Z', turnCount: 2, title: '华东地区都有什么数据'},
        {id: conv2, releaseDigest: digest, updatedAt: '2026-09-20T09:00:00Z', turnCount: 1, title: '采购订单总额'},
      ],
    },
  }));
  await page.route(`**/v0.1/chat/conversations/${conv1}`, route => route.fulfill({
    json: {
      id: conv1,
      releaseDigest: digest,
      turns: [
        {
          question: '华东地区都有什么数据',
          answer: {
            kind: 'answer',
            textOrigin: 'ENGINE',
            text: '华东地区采购金额合计 1200 CNY',
            releaseDigest: digest,
            evidence: [],
          },
        },
      ],
    },
  }));

  await page.goto('/studio/?view=chat');
  await page.getByRole('button', {name: '历史会话'}).click();
  await expect(page.getByRole('complementary', {name: '历史会话列表'})).toBeVisible();
  await expect(page.getByText('华东地区都有什么数据')).toBeVisible();
  await expect(page.getByText('采购订单总额')).toBeVisible();

  await page.getByText('华东地区都有什么数据').click();
  await expect(page.getByRole('complementary', {name: '历史会话列表'})).toHaveCount(0);
  await expect(page.getByText('华东地区采购金额合计 1200 CNY')).toBeVisible();

  await page.getByRole('button', {name: '历史会话'}).click();
  await expect(page.getByText('当前', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: '关闭历史会话'}).click();

  // Continue conversation in the loaded historical session
  let continuedReq: {message?: string; conversationId?: string} | null = null;
  await page.route('**/v0.1/chat/turns', async route => {
    continuedReq = route.request().postDataJSON();
    await route.fulfill({
      contentType: 'application/x-ndjson',
      body: [
        {type: 'start', conversationId: conv1, releaseDigest: digest},
        {type: 'answer', answer: {kind: 'answer', textOrigin: 'ENGINE', text: '华东区前三供应商如下', releaseDigest: digest, evidence: []}},
        {type: 'done'},
      ].map(x => JSON.stringify(x)).join('\n') + '\n',
    });
  });

  await page.getByLabel('业务问题').fill('前三的供应商是谁？');
  await page.getByRole('button', {name: '发送', exact: true}).click();
  await expect(page.getByText('华东区前三供应商如下')).toBeVisible();
  await expect(page.getByText('华东地区采购金额合计 1200 CNY')).toBeVisible();
  expect(continuedReq?.conversationId).toBe(conv1);
  expect(continuedReq?.message).toBe('前三的供应商是谁？');
});

