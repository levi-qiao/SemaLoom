import { choice, noul, score, TypeSafeClient } from '@typesafe-ai/sdk';

const DEFAULT_MIN_CONFIDENCE = 0.85;
const MAX_HISTORY_CHARS = 6000;

function contentText(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content
    .filter(part => part && part.type === 'text' && typeof part.text === 'string')
    .map(part => part.text)
    .join('\n');
}

export function decisionHistory(messages, maxChars = MAX_HISTORY_CHARS) {
  const rows = [];
  let used = 0;
  for (const message of [...(messages ?? [])].reverse()) {
    if (!message || !['user', 'assistant', 'compactionSummary'].includes(message.role)) continue;
    const value = message.role === 'compactionSummary'
      ? String(message.summary ?? '')
      : contentText(message.content);
    if (!value) continue;
    const available = maxChars - used;
    if (available <= 0) break;
    rows.push({ role: message.role, text: value.slice(-available) });
    used += Math.min(value.length, available);
  }
  return rows.reverse();
}

export function orderCatalog(catalog, preferredTool) {
  if (!preferredTool) return catalog;
  return [...catalog].sort((left, right) =>
    Number(right.name === preferredTool) - Number(left.name === preferredTool));
}

export function semanticCandidates(semanticContext, maxCandidates = 48) {
  const catalog = Array.isArray(semanticContext?.businessCatalog)
    ? semanticContext.businessCatalog : [];
  return catalog
    .filter(item => item && typeof item.id === 'string' && typeof item.kind === 'string')
    .slice(0, maxCandidates)
    .map((item, index) => ({
      key: `candidate_${index}`,
      id: item.id,
      description: {
        id: item.id,
        kind: item.kind,
        label: item.label,
        aliases: item.aliases,
        objectType: item.objectType,
        rule: item.rule,
        dimensions: item.dimensions,
      },
    }));
}

export function createJevDecisionHook({ config, client } = {}) {
  if (!config?.apiKey && !client) {
    return { enabled: false, decide: async () => ({ applied: false }) };
  }
  const sdk = client ?? new TypeSafeClient({
    apiKey: config.apiKey,
    baseURL: config.baseURL,
    defaultModel: config.model ?? 'jev-latest',
    timeout: config.timeoutMs ?? 5000,
    retry: { maxRetries: config.maxRetries ?? 1 },
    logLevel: 'off',
  });
  const minConfidence = config?.minConfidence ?? DEFAULT_MIN_CONFIDENCE;

  return {
    enabled: true,
    async decide({ message, history, semanticContext, catalog, locale }) {
      if (!Array.isArray(catalog) || catalog.length < 2) return { applied: false };
      const criteria = Object.fromEntries(catalog.map(tool => [
        tool.name,
        { description: tool.description, inputSchema: tool.inputSchema },
      ]));
      const candidates = semanticCandidates(semanticContext);
      const semanticCriteria = Object.fromEntries([
        ...candidates.map(item => [item.key, item.description]),
        ['no_semantic_match', {
          description: 'None of the supplied authorized ontology definitions matches the request.',
        }],
      ]);
      try {
        const response = await sdk.systemOne({
          model: config?.model ?? 'jev-latest',
          state: {
            userQuestion: message,
            locale,
            conversationSummary: decisionHistory(history),
            ontology: semanticContext,
            availableTools: catalog.map(tool => ({ name: tool.name, description: tool.description })),
          },
          questions: {
            nextTool: choice(
              {
                task: 'select_next_semantic_tool',
                rule: 'Choose only from the supplied tools. Prefer clarification when essential business scope is missing.',
              },
              criteria,
            ),
            scopeComplete: noul(
              {
                task: 'judge_scope_completeness',
                rule: 'The user and conversation provide enough business scope to execute the selected semantic operation without guessing.',
              },
              {
                true: 'All material business choices are explicit in the state.',
                false: 'At least one material business choice must be obtained from the user.',
              },
            ),
            ...(candidates.length ? {
              semanticCandidate: choice(
                {
                  task: 'classify_request_against_authorized_ontology',
                  rule: 'Select only one supplied candidate key, or no_semantic_match. Use labels, aliases, kinds and relationships; never invent a semantic id.',
                },
                semanticCriteria,
              ),
              semanticMatchQuality: score(
                {
                  task: 'score_best_authorized_semantic_match',
                  rule: 'Score how directly the best supplied ontology candidate matches the current request. Do not score answer correctness or data availability.',
                },
                [
                  'No supplied candidate is relevant.',
                  'A candidate is only loosely related and clarification is necessary.',
                  'A candidate plausibly matches but another candidate or context may change the meaning.',
                  'One supplied candidate directly and unambiguously matches the request wording and context.',
                ],
              ),
            } : {}),
          },
        });
        const route = response.answers?.nextTool;
        const scope = response.answers?.scopeComplete;
        const semantic = response.answers?.semanticCandidate;
        const match = response.answers?.semanticMatchQuality;
        const preferredTool =
          route?.confidence >= minConfidence && criteria[route.choice] ? route.choice : undefined;
        const chosen = candidates.find(item => item.key === semantic?.choice);
        const preferredSemanticId =
          semantic?.confidence >= minConfidence && Number(match?.score ?? 0) >= 2 && chosen
            ? chosen.id : undefined;
        return {
          applied: Boolean(preferredTool),
          preferredTool,
          preferredSemanticId,
          requiresClarification: typeof scope?.noul === 'number' ? scope.noul < 0.5 : undefined,
        };
      } catch {
        // Jev is an optimization and decision aid. Python validation and the
        // normal Pi loop remain available when the provider is unavailable.
        return { applied: false };
      }
    },
  };
}
