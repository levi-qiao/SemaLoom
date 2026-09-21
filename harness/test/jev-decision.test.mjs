import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createJevDecisionHook,
  decisionHistory,
  orderCatalog,
  semanticCandidates,
} from '../jev-decision.mjs';

test('Jev route is derived from live ontology, tools, question and bounded history', async () => {
  let request;
  const client = {
    systemOne: async value => {
      request = value;
      return {
        answers: {
          nextTool: { choice: 'find_objects', confidence: 0.93 },
          scopeComplete: { noul: 0.21 },
          semanticCandidate: { choice: 'candidate_0', confidence: 0.91 },
          semanticMatchQuality: { score: 2.7 },
        },
      };
    },
  };
  const hook = createJevDecisionHook({ client, config: { minConfidence: 0.85 } });
  const catalog = [
    { name: 'find_objects', description: 'Find ontology objects', inputSchema: { type: 'object' } },
    { name: 'present_answer', description: 'Finish', inputSchema: { type: 'object' } },
  ];
  const decision = await hook.decide({
    message: 'Show annual filings',
    locale: 'en',
    history: [{ role: 'user', content: 'Earlier question' }],
    semanticContext: {
      businessCatalog: [{ id: 'demo.Filing', kind: 'ObjectType', label: 'Filing' }],
    },
    catalog,
  });

  assert.equal(request.state.userQuestion, 'Show annual filings');
  assert.equal(request.state.ontology.businessCatalog[0].id, 'demo.Filing');
  assert.deepEqual(Object.keys(request.questions.nextTool.criteria), [
    'find_objects',
    'present_answer',
  ]);
  assert.deepEqual(decision, {
    applied: true,
    preferredTool: 'find_objects',
    preferredSemanticId: 'demo.Filing',
    requiresClarification: true,
  });
  assert.equal('confidence' in decision, false);
});

test('Jev failure and low confidence fall back without blocking the Pi loop', async () => {
  const unavailable = createJevDecisionHook({
    client: { systemOne: async () => { throw new Error('offline'); } },
  });
  assert.deepEqual(await unavailable.decide({ catalog: [{}, {}] }), { applied: false });

  const low = createJevDecisionHook({
    client: { systemOne: async () => ({ answers: {
      nextTool: { choice: 'a', confidence: 0.2 },
      scopeComplete: { noul: 0.8 },
    } }) },
  });
  assert.deepEqual(await low.decide({ catalog: [
    { name: 'a', description: '', inputSchema: {} },
    { name: 'b', description: '', inputSchema: {} },
  ] }), {
    applied: false,
    preferredTool: undefined,
    preferredSemanticId: undefined,
    requiresClarification: false,
  });
});

test('decision helpers omit tool results and move only the chosen live tool', () => {
  const history = decisionHistory([
    { role: 'user', content: 'q1' },
    { role: 'toolResult', content: 'raw business rows' },
    { role: 'assistant', content: [{ type: 'text', text: 'a1' }] },
  ]);
  assert.deepEqual(history, [
    { role: 'user', text: 'q1' },
    { role: 'assistant', text: 'a1' },
  ]);
  assert.deepEqual(orderCatalog([{ name: 'a' }, { name: 'b' }], 'b'), [
    { name: 'b' },
    { name: 'a' },
  ]);
  assert.deepEqual(
    semanticCandidates({businessCatalog: [
      {id: 'demo.Order', kind: 'ObjectType', label: 'Order'},
      {id: 'demo.amount', kind: 'Metric', objectType: 'demo.Order'},
      {kind: 'Metric'},
    ]}),
    [
      {key: 'candidate_0', id: 'demo.Order', description: {
        id: 'demo.Order', kind: 'ObjectType', label: 'Order', aliases: undefined,
        objectType: undefined, rule: undefined, dimensions: undefined,
      }},
      {key: 'candidate_1', id: 'demo.amount', description: {
        id: 'demo.amount', kind: 'Metric', label: undefined, aliases: undefined,
        objectType: 'demo.Order', rule: undefined, dimensions: undefined,
      }},
    ],
  );
});
