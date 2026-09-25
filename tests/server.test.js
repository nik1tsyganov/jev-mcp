import test from "node:test";
import assert from "node:assert/strict";

import { TOOLS, createToolRunner } from "../src/server.js";

function fakeClient() {
  const calls = [];
  return {
    calls,
    systemOne: async (args) => {
      calls.push(args);
      return { model: "jev-test", answers: {}, usage: { input_tokens: 1, output_tokens: 1 } };
    },
    listModels: async () => ({ models: ["jev-test"] }),
  };
}

test("the jev server lists exactly the Jev tools", () => {
  assert.deepEqual(
    TOOLS.map((t) => t.name),
    ["jev_ask", "jev_noul", "jev_choice", "jev_score", "jev_models", "decision_browser_action"]
  );
});

test("jev_ask sends validated questions and the model straight to Jev", async () => {
  const client = fakeClient();
  const { runTool } = createToolRunner({ client });
  const questions = { a: { type: "noul", instructions: "Is it on fire?" } };
  const res = await runTool("jev_ask", { state: "x", questions, model: "jev-custom" });
  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].model, "jev-custom");
  assert.deepEqual(Object.keys(client.calls[0].questions), ["a"]);
  assert.deepEqual(Object.keys(res).sort(), ["answers", "model", "usage"]);
});

test("single-question wrappers use the id `answer`", async () => {
  const client = fakeClient();
  const { runTool } = createToolRunner({ client });
  await runTool("jev_noul", { state: "x", instructions: "Yes?" });
  await runTool("jev_choice", { state: "x", instructions: "Which?", criteria: { a: null, b: null } });
  await runTool("jev_score", { state: "x", instructions: "How good?", criteria: ["low", "high"] });
  assert.deepEqual(client.calls.map((c) => [Object.keys(c.questions), c.questions.answer.type]), [
    [["answer"], "noul"],
    [["answer"], "choice"],
    [["answer"], "score"],
  ]);
});

test("jev_models lists models without a judgment call", async () => {
  const client = fakeClient();
  const { runTool } = createToolRunner({ client });
  assert.deepEqual(await runTool("jev_models"), { models: ["jev-test"] });
  assert.equal(client.calls.length, 0);
});

test("the removed routing tools are unknown", async () => {
  const { runTool } = createToolRunner({ client: fakeClient() });
  for (const name of ["decision_ask", "decision_bookmark_topic", "decision_status"]) {
    await assert.rejects(runTool(name, {}), /Unknown tool/);
  }
});

test("the per-call question cap stops a runaway batch before any spend", async () => {
  const client = fakeClient();
  const { runTool } = createToolRunner({ client });
  const questions = Object.fromEntries(
    Array.from({ length: 33 }, (_, i) => [`q${i}`, { type: "noul", instructions: "Yes?" }])
  );
  await assert.rejects(runTool("jev_ask", { state: "x", questions }), /exceeds the 32 cap/);
  assert.equal(client.calls.length, 0);
});

test("each Jev call carries its tool name and the MCP client label", async () => {
  const client = fakeClient();
  const { runTool } = createToolRunner({ client, clientLabel: () => "claude-code@9.9" });
  await runTool("jev_score", { state: "x", instructions: "How good?", criteria: ["low", "high"] });
  assert.deepEqual(client.calls[0].caller, { tool: "jev_score", client: "claude-code@9.9" });
});
