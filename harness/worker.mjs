import { createInterface } from 'node:readline';
import { Agent } from '@earendil-works/pi-agent-core';
import { createProvider } from './provider.mjs';
import { createSemanticPlugin } from './semantic-plugin.mjs';
import { transformContext } from './context-transform.mjs';

const send = data => process.stdout.write(JSON.stringify(data) + '\n');
const lines = createInterface({ input: process.stdin });
const pending = new Map();
let started = false;
let agent;
lines.on('line', line => {
  try {
    const data = JSON.parse(line);
    if (data.type === 'start' && !started) { started = true; void run(data); }
    else if (data.type === 'result') {
      const waiter = pending.get(data.id);
      if (waiter) { pending.delete(data.id); waiter.resolve(data.payload); }
    }
  } catch { send({type:'error',code:'HARNESS_PROTOCOL_ERROR'}); process.exitCode = 1; lines.close(); }
});
lines.on('close', () => { agent?.abort(); for (const w of pending.values()) w.reject(new Error('CANCELLED')); });

async function run(input) {
  try {
    const provider = createProvider(input.provider);
    const plugin = createSemanticPlugin({
      catalog: input.catalog, releaseDigest: input.releaseDigest,
      invoke: (id, name, args) => new Promise((resolve,reject) => {
        pending.set(id,{resolve,reject}); send({type:'call',id,name,args});
      }),
    });
    let turns = 0;
    agent = new Agent({
      initialState: { model: provider.model, systemPrompt: input.systemPrompt,
        tools: plugin.tools, messages: input.history, thinkingLevel: 'off' },
      streamFn: provider.streamFn, toolExecution: 'sequential',
      beforeToolCall: plugin.beforeToolCall, afterToolCall: plugin.afterToolCall,
      transformContext: async (messages) => transformContext(messages),
      shouldStopAfterTurn: async () => ++turns >= 12 || plugin.completed || plugin.calls >= 20,
    });
    agent.subscribe(event => {
      if (event.type === 'turn_start') send({type:'progress',stage:'model',turn:turns+1});
      if (event.type === 'tool_execution_start') send({type:'progress',stage:'tool',name:event.toolName});
      // Reasoning and unverified draft text are not user-visible facts.
    });
    await agent.prompt(input.message);
    if (!plugin.completed && turns < 12 && !agent.state.error) {
      await agent.prompt('请调用 present_answer 完成本次回答；只能引用本次真实工具返回的 evidenceId。无法回答时用 clarification 或 unsupported，不要猜测。');
    }
    if (!plugin.completed) {
      send({type:'error',code:agent.state.error ? 'MODEL_REQUEST_FAILED' : 'ANSWER_NOT_VALIDATED'});
    } else {
      // Only the server consumes history. Never deliver credentials or internal state to the browser.
      send({type:'complete',history:transformContext(agent.state.messages)});
    }
  } catch { send({type:'error',code:'MODEL_REQUEST_FAILED'}); }
  finally { lines.close(); }
}
