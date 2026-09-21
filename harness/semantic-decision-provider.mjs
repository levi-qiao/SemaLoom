import { createJevDecisionHook, orderCatalog } from './jev-decision.mjs';

const PROVIDERS = Object.freeze({
  jev: ({ config, client }) => createJevDecisionHook({ config, client }),
});

const disabled = Object.freeze({
  enabled: false,
  provider: 'none',
  decide: async () => ({ applied: false }),
});

/**
 * One decision seam for Pi orchestration. Adapters may rank only the bounded
 * tools and ontology candidates supplied by the server; Python remains the
 * authority for semantic validation and execution.
 */
export function createSemanticDecisionProvider({ config, client, providers = PROVIDERS } = {}) {
  if (!config) return disabled;
  const kind = config.kind ?? 'jev';
  const factory = providers[kind];
  if (typeof factory !== 'function') {
    throw new Error(`UNSUPPORTED_DECISION_PROVIDER:${kind}`);
  }
  const adapter = factory({ config, client });
  return {
    enabled: adapter.enabled,
    provider: kind,
    decide: input => adapter.decide(input),
  };
}

export { orderCatalog };
