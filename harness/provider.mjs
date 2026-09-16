import { streamSimple } from '@earendil-works/pi-ai/api/openai-completions';

export function createProvider(config) {
  const model = {
    id: config.model, name: config.model, api: 'openai-completions',
    provider: 'bailian-token-plan', baseUrl: config.baseUrl.trim(),
    reasoning: false, input: ['text'],
    // Unknown subscription cost; never present these SDK placeholders as billing figures.
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 64000, maxTokens: 2048,
    compat: { supportsStore: false, supportsDeveloperRole: false,
      supportsReasoningEffort: false, supportsStrictMode: false,
      maxTokensField: 'max_tokens', thinkingFormat: 'qwen' },
  };
  return { model, streamFn: (m, context, options) => streamSimple(m, context, {
    ...options, apiKey: config.apiKey, maxTokens: 2048,
    onPayload: (payload) => { payload.enable_thinking = false; },
  }) };
}
