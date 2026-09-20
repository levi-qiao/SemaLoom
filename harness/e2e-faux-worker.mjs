/** Official pi Agent + pi-ai faux for isolated Chat e2e. No coding-agent UI. */
import { createInterface } from "node:readline";
import { Agent } from "@earendil-works/pi-agent-core";
import {
  createModels,
  fauxProvider,
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai";
import { createSemanticPlugin } from "./semantic-plugin.mjs";
import { transformContext } from "./context-transform.mjs";

const send = (data) => process.stdout.write(JSON.stringify(data) + "\n");
const lines = createInterface({ input: process.stdin });
const pending = new Map();
let started = false;
let agent;

lines.on("line", (line) => {
  try {
    const data = JSON.parse(line);
    if (data.type === "start" && !started) {
      started = true;
      void run(data);
    } else if (data.type === "result") {
      const waiter = pending.get(data.id);
      if (waiter) {
        pending.delete(data.id);
        waiter.resolve(data.payload);
      }
    }
  } catch {
    send({ type: "error", code: "HARNESS_PROTOCOL_ERROR" });
    process.exitCode = 1;
    lines.close();
  }
});
lines.on("close", () => {
  agent?.abort();
  for (const waiter of pending.values()) waiter.reject(new Error("CANCELLED"));
});

async function run(input) {
  try {
    const faux = fauxProvider();
    const models = createModels();
    models.setProvider(faux.provider);
    faux.setResponses([
      fauxAssistantMessage(
        [fauxToolCall("prepare_semantic_query", { question: input.message })],
        { stopReason: "toolUse" },
      ),
    ]);
    const plugin = createSemanticPlugin({
      catalog: input.catalog,
      releaseDigest: input.releaseDigest,
      invoke: (id, name, args) =>
        new Promise((resolve, reject) => {
          pending.set(id, { resolve, reject });
          send({ type: "call", id, name, args });
        }),
    });
    agent = new Agent({
      initialState: {
        model: faux.getModel(),
        systemPrompt: input.systemPrompt,
        tools: plugin.tools,
        messages: input.history,
        thinkingLevel: "off",
      },
      streamFn: models.streamSimple.bind(models),
      toolExecution: "sequential",
      beforeToolCall: plugin.beforeToolCall,
      afterToolCall: plugin.afterToolCall,
      transformContext: async (messages) => transformContext(messages),
    });
    agent.subscribe((event) => {
      if (event.type === "turn_start") send({ type: "progress", stage: "model" });
      if (event.type === "tool_execution_start")
        send({ type: "progress", stage: "tool", name: event.toolName });
    });
    await agent.prompt(input.message);
    if (!plugin.completed) {
      send({
        type: "error",
        code: agent.state.error ? "MODEL_REQUEST_FAILED" : "ANSWER_NOT_VALIDATED",
      });
    } else {
      send({ type: "complete", history: transformContext(agent.state.messages) });
    }
  } catch {
    send({ type: "error", code: "MODEL_REQUEST_FAILED" });
  } finally {
    lines.close();
  }
}
