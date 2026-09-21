import test from 'node:test';
import assert from 'node:assert/strict';

import { createSemanticDecisionProvider } from '../semantic-decision-provider.mjs';

test('decision provider is disabled without configuration', async () => {
  const provider = createSemanticDecisionProvider();
  assert.equal(provider.enabled, false);
  assert.deepEqual(await provider.decide({}), { applied: false });
});

test('decision adapters are replaceable behind one bounded interface', async () => {
  let received;
  const provider = createSemanticDecisionProvider({
    config: { kind: 'local' },
    providers: {
      local: () => ({
        enabled: true,
        decide: async input => {
          received = input;
          return { applied: true, preferredTool: 'search_semantics' };
        },
      }),
    },
  });
  const input = {
    message: '查订单',
    catalog: [{ name: 'search_semantics' }],
    semanticContext: { businessCatalog: [{ id: 'procurement.Order' }] },
  };
  assert.deepEqual(await provider.decide(input), {
    applied: true,
    preferredTool: 'search_semantics',
  });
  assert.equal(provider.provider, 'local');
  assert.equal(received, input);
});

test('unknown configured decision provider fails closed at startup', () => {
  assert.throws(
    () => createSemanticDecisionProvider({ config: { kind: 'unknown' } }),
    /UNSUPPORTED_DECISION_PROVIDER:unknown/,
  );
});
