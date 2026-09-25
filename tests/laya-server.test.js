import test from "node:test";
import assert from "node:assert/strict";
import { createLayaToolRunner } from "../src/laya-server.js";
import { BOOKMARK_PROFILE_IDS, loadBookmarkQuestions } from "../src/bookmark-questions.js";

function fakeService() {
  return {
    calls: [],
    async ask(args) { this.calls.push(args); return { provider: "laya", accepted: true }; },
    status() { this.calls.push("status"); return { closed: false }; },
  };
}

test("Laya exposes exactly three local tools without model arguments", () => {
  const { tools } = createLayaToolRunner(fakeService());
  assert.deepEqual(tools.map((tool) => tool.name), ["laya_ask", "laya_bookmark_topic", "laya_status"]);
  for (const tool of tools) {
    assert.equal(Object.hasOwn(tool.inputSchema.properties, "model"), false);
    assert.match(tool.description, /local offline model/);
    assert.match(tool.description, /never calls Jev/);
    assert.match(tool.description, /accepted:false.*jev_ask/);
  }
  assert.deepEqual(tools[1].inputSchema.properties.profile.enum, BOOKMARK_PROFILE_IDS);
  assert.equal(tools[1].inputSchema.properties.profile.default, "technical-bookmark-topic-v2");
});

test("laya_ask dispatches its input to the service", async () => {
  const service = fakeService();
  const args = { state: "s", questions: { ok: { type: "noul", instructions: "Is it blue?" } }, profile: "p" };
  assert.deepEqual(await createLayaToolRunner(service).runTool("laya_ask", args), { provider: "laya", accepted: true });
  assert.deepEqual(service.calls, [args]);
});

test("bookmark dispatch defaults to v2 and supports each frozen profile", async () => {
  const service = fakeService();
  const { runTool } = createLayaToolRunner(service);
  await runTool("laya_bookmark_topic", { state: "s" });
  assert.deepEqual(service.calls[0], { state: "s", profile: "technical-bookmark-topic-v2", questions: loadBookmarkQuestions() });
  for (const profile of BOOKMARK_PROFILE_IDS) {
    await runTool("laya_bookmark_topic", { state: "s", profile });
    assert.deepEqual(service.calls.at(-1), { state: "s", profile, questions: loadBookmarkQuestions(profile) });
  }
});

test("laya_status dispatches to the service", async () => {
  const service = fakeService();
  assert.deepEqual(await createLayaToolRunner(service).runTool("laya_status"), { closed: false });
  assert.deepEqual(service.calls, ["status"]);
});

test("unknown tools, bookmark profiles and model arguments fail before dispatch", async () => {
  const service = fakeService();
  const { runTool } = createLayaToolRunner(service);
  await assert.rejects(runTool("jev_ask"), /Unknown tool/);
  for (const profile of ["missing", "constructor", "__proto__", null]) {
    await assert.rejects(runTool("laya_bookmark_topic", { state: "s", profile }), /Unknown bookmark topic profile/);
  }
  for (const tool of ["laya_ask", "laya_bookmark_topic", "laya_status"]) {
    await assert.rejects(runTool(tool, { model: "jev" }), /Unsupported tool argument/);
  }
  assert.deepEqual(service.calls, []);
});
