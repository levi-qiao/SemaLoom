/** A domain-neutral pi-core plugin. Python owns authorization, rules and answer evidence. */
export function createSemanticPlugin({ catalog, invoke, releaseDigest, maxCalls = 20, preferredTool }) {
  const allowed = new Set(catalog.map(t => t.name));
  let calls = 0;
  let completed = false;
  let routeRepairAvailable = Boolean(preferredTool && allowed.has(preferredTool));
  return {
    tools: catalog.map(t => ({
      name: t.name, label: t.name, description: t.description,
      parameters: t.inputSchema,
      execute: async (id, args, signal) => {
        if (signal?.aborted) throw new Error('CANCELLED');
        const payload = await invoke(id, t.name, args, signal);
        return { content: [{ type: 'text', text: JSON.stringify(payload) }], details: payload };
      },
    })),
    beforeToolCall: async ({ toolCall }) => {
      if (completed || !allowed.has(toolCall.name))
        return { block: true, reason: 'TOOL_NOT_ALLOWED', terminate: true };
      if (routeRepairAvailable && toolCall.name !== preferredTool) {
        routeRepairAvailable = false;
        return { block: true, reason: 'DECISION_ROUTE_MISMATCH', terminate: false };
      }
      routeRepairAvailable = false;
      if (++calls > maxCalls)
        return { block: true, reason: 'TOOL_BUDGET_EXCEEDED', terminate: true };
    },
    afterToolCall: async ({ toolCall, result, isError }) => {
      const data = result.details;
      if (isError || data?.error) return { isError: true };
      if (data?.releaseDigest !== releaseDigest)
        return { isError: true, content: [{type:'text',text:'RELEASE_MISMATCH'}], details: {}, terminate: true };
      if ((toolCall.name === 'present_answer' && data?.accepted === true) ||
          data?.answerReady === true || data?.waiting === true) {
        completed = true;
        return { terminate: true };
      }
    },
    get completed() { return completed; },
    get calls() { return calls; },
  };
}
