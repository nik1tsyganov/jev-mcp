import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createLayaService } from "../src/laya-service.js";
import { createLayaClient } from "../src/laya-client.js";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { loadPolicy, questionsFingerprint, resolveProfileId, selectProvider } from "../src/provider-policy.js";
import { loadBookmarkQuestions } from "../src/bookmark-questions.js";

const QUESTIONS = {
  route: { type: "choice", instructions: "Pick one.", criteria: { a: null, b: null } },
};
const V2 = "technical-bookmark-topic-v2";

function fakeWorker(config = {}, { probability = 0.9, failure, mutate } = {}) {
  const worker = {
    calls: [],
    closed: 0,
    status: () => ({ available: true, checkpoint: config.checkpoint ?? "cp", revision: config.revision ?? "rev" }),
    async predict(input) {
      this.calls.push(input);
      if (failure) throw failure;
      const answers = {};
      for (const [id, question] of Object.entries(input.questions)) {
        const labels = question.type === "choice" ? Object.keys(question.criteria)
          : question.type === "score" ? question.criteria.map((_, i) => String(i)) : [];
        answers[id] = question.type === "noul" ? { type: "noul", noul: probability } : {
          type: question.type,
          probabilities: Object.fromEntries(labels.map((label, i) => [label, i === 0 ? probability : (1 - probability) / (labels.length - 1)])),
          ...(question.type === "choice" ? { choice: labels[0] } : {
            score: 0,
            legend: Object.fromEntries(question.criteria.map((label, i) => [String(i), label])),
          }),
        };
      }
      const result = { model: "laya:test", checkpoint: this.status().checkpoint, revision: this.status().revision,
        usage: { input_tokens: 3, output_tokens: 1 }, answers };
      if (mutate) mutate(result);
      return result;
    },
    async close() { this.closed++; },
  };
  return worker;
}

function setup(t, options = {}, workerOptions = {}) {
  const dir = mkdtempSync(join(tmpdir(), "laya-service-"));
  const logPath = join(dir, "decisions.jsonl");
  const workers = [];
  const local = fakeWorker({}, workerOptions);
  let jevCalls = 0;
  const service = createLayaService({
    laya: local,
    policy: loadPolicy(),
    createClient(config) {
      const worker = fakeWorker(config, workerOptions);
      workers.push(worker);
      return worker;
    },
    // A legacy injected Jev callback must never be invoked, including on failure.
    jev: () => { jevCalls++; throw new Error("Jev must never run"); },
    logPath,
    ...options,
  });
  t.after(async () => {
    await service.close();
    assert.equal(jevCalls, 0);
    rmSync(dir, { recursive: true, force: true });
  });
  return { service, workers, local, logPath };
}

test("exact bookmark questions resolve to the default pinned profile", async (t) => {
  const { service, workers, local } = setup(t);
  const result = await service.ask({ state: "bookmark", questions: loadBookmarkQuestions() });
  assert.deepEqual(Object.keys(result), ["provider", "profile", "checkpoint", "revision", "qualification", "accepted", "reason", "answers"]);
  assert.equal(result.provider, "laya");
  assert.equal(result.profile, V2);
  assert.equal(result.checkpoint, loadPolicy().profiles[V2].checkpoint);
  assert.equal(result.revision, loadPolicy().profiles[V2].revision);
  assert.equal(result.qualification, "FAILED");
  assert.equal(result.accepted, true);
  assert.equal(result.reason, null);
  assert.equal(workers[0].calls.length, 1);
  assert.equal(local.calls.length, 0);
});

test("generic choice, noul and score results are UNQUALIFIED", async (t) => {
  const { service, local } = setup(t);
  const questions = { ...QUESTIONS,
    yes: { type: "noul", instructions: "Is the banner blue?" },
    grade: { type: "score", instructions: "How vivid is the banner?", criteria: ["muted", "vivid"] },
  };
  const result = await service.ask({ state: { banner: "blue" }, questions });
  assert.equal(result.profile, null);
  assert.equal(result.qualification, "UNQUALIFIED");
  assert.equal(result.accepted, true);
  assert.equal(result.reason, null);
  assert.equal(local.calls.length, 1);
  assert.deepEqual(Object.keys(result.answers), Object.keys(questions));
});

test("generic inference rejects calibrated pack overlap", async (t) => {
  const { service, local } = setup(t);
  await assert.rejects(service.ask({ state: "s", questions: {
    route: { type: "choice", instructions: "How should this file be handled before merge?",
      criteria: { read_required: "read", skim: "skim", no_read_needed: "mechanical" } },
  } }), /pack-overlap/);
  assert.equal(local.calls.length, 0);
});

test("explicit unknown, disabled and mismatched profiles never become generic", async (t) => {
  const policy = loadPolicy();
  policy.profiles[V2].enabled = false;
  const { service, local } = setup(t, { policy });
  await assert.rejects(service.ask({ state: "s", questions: QUESTIONS, profile: "unknown" }), /profile-unknown/);
  await assert.rejects(service.ask({ state: "s", questions: loadBookmarkQuestions(), profile: V2 }), /profile-disabled/);
  policy.profiles[V2].enabled = true;
  await assert.rejects(service.ask({ state: "s", questions: QUESTIONS, profile: V2 }), /questions-hash-mismatch/);
  for (const profile of [null, {}, ""]) {
    await assert.rejects(service.ask({ state: "s", questions: QUESTIONS, profile }), /registered profile id/);
  }
  assert.equal(local.calls.length, 0);
});

test("below-threshold selected label returns answers and accepted:false", async (t) => {
  const { service } = setup(t, {}, { probability: 0.1 });
  const result = await service.ask({ state: "s", questions: loadBookmarkQuestions(), profile: V2 });
  assert.equal(result.accepted, false);
  assert.equal(result.reason, "below_threshold");
  assert.equal(result.qualification, "FAILED");
  const answer = result.answers.topic;
  assert.equal(answer.probabilities[answer.choice], 0.1);
});

test("worker failure throws a sanitized error without calling Jev", async (t) => {
  const { service, logPath } = setup(t, {}, { failure: new Error("worker failed: Bearer secret-value token=private") });
  await assert.rejects(service.ask({ state: "private-state", questions: QUESTIONS }), (error) => {
    assert.match(error.message, /worker failed/);
    assert.doesNotMatch(error.message, /secret-value|private/);
    return true;
  });
  const log = readFileSync(logPath, "utf8");
  assert.doesNotMatch(log, /secret-value|private-state/);
  assert.equal(JSON.parse(log).reason, "local-error");
});

test("invalid worker output fails instead of returning an accepted result", async (t) => {
  for (const mutate of [
    (result) => { result.truncated = true; },
    (result) => { result.revision = "wrong"; },
    (result) => { result.answers.route.probabilities.a = 1.5; },
    (result) => { result.answers = {}; },
    (result) => { delete result.usage; },
  ]) {
    const { service } = setup(t, {}, { mutate });
    await assert.rejects(service.ask({ state: "s", questions: QUESTIONS }), /local-invalid/);
  }
});

test("generic inference requires a trusted registry and an available runtime", async (t) => {
  const { service } = setup(t, { policy: { version: 2, profiles: {} } });
  await assert.rejects(service.ask({ state: "s", questions: QUESTIONS }), /profile-absent/);
  const unavailable = fakeWorker();
  unavailable.status = () => ({ available: false });
  const other = setup(t, { laya: unavailable });
  await assert.rejects(other.service.ask({ state: "s", questions: QUESTIONS }), /local-unavailable/);
});

test("requests are validated and snapshotted before worker inference", async (t) => {
  const { service, local } = setup(t);
  await assert.rejects(service.ask({ state: "s", questions: {} }), /questions/);
  await assert.rejects(service.ask({ state: "x".repeat(200001), questions: QUESTIONS }), /limit/);
  const state = { note: "before" };
  const questions = structuredClone(QUESTIONS);
  const pending = service.ask({ state, questions });
  state.note = "after";
  questions.route.instructions = "changed";
  await pending;
  assert.equal(local.calls[0].state.note, "before");
  assert.equal(local.calls[0].questions.route.instructions, "Pick one.");
});

test("profile workers are reused, refreshed on identity change, and closed once", async (t) => {
  const registry = loadPolicy();
  const policy = { loadPolicy: () => registry, questionsFingerprint, resolveProfileId, selectProvider };
  const { service, workers, local } = setup(t, { policy });
  const input = { state: "s", questions: loadBookmarkQuestions(), profile: V2 };
  await service.ask(input);
  await service.ask(input);
  assert.equal(workers.length, 1);
  assert.equal(workers[0].calls.length, 2);
  registry.profiles[V2].runtime.modelPath += "-updated";
  await service.ask(input);
  assert.equal(workers.length, 2);
  assert.equal(workers[0].closed, 1);
  assert.equal(service.status().profiles[V2].resident, true);
  await service.close();
  await service.close();
  assert.equal(workers[1].closed, 1);
  assert.equal(local.closed, 1);
  await assert.rejects(service.ask(input), /closed/);
});

test("local telemetry keeps hashes and override metadata without provider-routing fields", async (t) => {
  const { service, logPath } = setup(t);
  await service.ask({ state: "private-state", questions: loadBookmarkQuestions() });
  const row = JSON.parse(readFileSync(logPath, "utf8"));
  assert.equal(row.adoptionMode, "owner_override");
  assert.equal(row.qualificationStatus, "FAILED");
  assert.match(row.inputHash, /^[a-f0-9]{64}$/);
  assert.match(row.fingerprint, /^[a-f0-9]{64}$/);
  for (const key of ["fallback", "shadowScheduled", "jevModel", "state", "questions", "answers"]) {
    assert.equal(Object.hasOwn(row, key), false);
  }
  const status = service.status();
  for (const key of ["credentialAvailable", "deploymentMode", "shadowRate"]) {
    assert.equal(Object.hasOwn(status, key), false);
  }
  assert.equal(status.counters.accepted, 1);
});

test("a worker crash does not leave Laya unavailable: the next ask respawns", async (t) => {
  const builder = fakeWorker({ checkpoint: "c", revision: "r" });
  const spawned = [];
  const spawn = () => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.stdin = new PassThrough();
    child.kill = () => {};
    child.stdin.on("data", async (chunk) => {
      const req = JSON.parse(chunk.toString());
      if (spawned.length === 1) return child.emit("exit", 1, null);
      const result = await builder.predict({ questions: req.questions });
      child.stdout.write(JSON.stringify({ type: "result", id: req.id, result: { ...result, model: "c@r" } }) + "\n");
    });
    spawned.push(child);
    setImmediate(() => child.stdout.write(JSON.stringify({ type: "ready", checkpoint: "c", revision: "r" }) + "\n"));
    return child;
  };
  const laya = createLayaClient({ spawn, python: "/py", modelPath: "/m", checkpoint: "c", revision: "r", workerPath: "/w" });
  const { service } = setup(t, { laya });
  await assert.rejects(service.ask({ state: "s", questions: QUESTIONS }), /worker exited/);
  const result = await service.ask({ state: "s", questions: QUESTIONS });
  assert.equal(result.provider, "laya");
  assert.equal(result.accepted, true);
  assert.equal(spawned.length, 2);
});

test("unprofiled questions registered to a non-default profile require that profile", async (t) => {
  const policy = loadPolicy();
  policy.profiles["technical-bookmark-topic-v1"].questionsHash = questionsFingerprint(QUESTIONS);
  const { service, local, logPath } = setup(t, { policy });
  await assert.rejects(service.ask({ state: "s", questions: QUESTIONS }), /profile-required/);
  assert.equal(local.calls.length, 0);
  assert.equal(JSON.parse(readFileSync(logPath, "utf8")).reason, "profile-required");
});

const ENV_KEYS = ["LAYA_PYTHON", "LAYA_MODEL_DIR", "LAYA_CHECKPOINT", "LAYA_MODEL_REVISION", "LAYA_TIMEOUT_MS", "LAYA_MAX_QUEUE"];

// Points LAYA_* at the V2 profile runtime, with overrides, and restores the env after the test.
function envLikeV2(t, overrides = {}) {
  const saved = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));
  t.after(() => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });
  const v2 = loadPolicy().profiles[V2];
  const vars = { LAYA_PYTHON: v2.runtime.python, LAYA_MODEL_DIR: v2.runtime.modelPath,
    LAYA_CHECKPOINT: v2.checkpoint, LAYA_MODEL_REVISION: v2.revision, ...overrides };
  for (const key of ENV_KEYS) {
    if (vars[key] === undefined) delete process.env[key];
    else process.env[key] = vars[key];
  }
}

test("an env runtime identical to a profile runtime shares one worker", async (t) => {
  envLikeV2(t);
  const { service, workers } = setup(t, { laya: undefined });
  assert.equal(workers.length, 1);
  const profiled = await service.ask({ state: "bookmark", questions: loadBookmarkQuestions() });
  assert.equal(profiled.profile, V2);
  const generic = await service.ask({ state: "s", questions: QUESTIONS });
  assert.equal(generic.profile, null);
  assert.equal(workers.length, 1);
  assert.equal(workers[0].calls.length, 2);
  assert.equal(service.status().profiles[V2].resident, true);
  await service.close();
  assert.equal(workers[0].closed, 1);
});

test("an env runtime that differs in revision or timeout gets its own worker", async (t) => {
  for (const overrides of [{ LAYA_MODEL_REVISION: "other-revision" }, { LAYA_TIMEOUT_MS: "60000" }]) {
    envLikeV2(t, overrides);
    const { service, workers } = setup(t, { laya: undefined });
    await service.ask({ state: "bookmark", questions: loadBookmarkQuestions() });
    assert.equal(workers.length, 2);
    assert.equal(workers[0].calls.length, 0);
    assert.equal(workers[1].calls.length, 1);
  }
});

test("refresh and eviction never close the shared env worker", async (t) => {
  envLikeV2(t);
  const registry = loadPolicy();
  for (const id of ["x1", "x2", "x3"]) {
    registry.profiles[id] = structuredClone(registry.profiles[V2]);
    registry.profiles[id].runtime.modelPath += `-${id}`;
  }
  const policy = { loadPolicy: () => registry, questionsFingerprint, resolveProfileId, selectProvider };
  const { service, workers } = setup(t, { laya: undefined, policy });
  const shared = workers[0];
  const questions = loadBookmarkQuestions();
  await service.ask({ state: "s", questions, profile: V2 });
  // The clones fail the evidence check, but each worker is created before that gate.
  for (const profile of ["x1", "x2", "x3"]) await service.ask({ state: "s", questions, profile }).catch(() => {});
  assert.equal(workers.length, 4);
  assert.equal(workers[1].closed, 1);
  const modelPath = registry.profiles[V2].runtime.modelPath;
  registry.profiles[V2].runtime.modelPath += "-updated";
  await service.ask({ state: "s", questions, profile: V2 });
  registry.profiles[V2].runtime.modelPath = modelPath;
  await service.ask({ state: "s", questions, profile: V2 });
  assert.equal(shared.closed, 0);
  assert.equal(shared.calls.length, 2);
  await service.close();
  assert.equal(shared.closed, 1);
});

// The first worker holds its request until released; retirement waits for in-flight work.
function gatedWorkers() {
  const workers = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  function createClient(config) {
    const worker = fakeWorker(config);
    const held = workers.length === 0;
    const predict = worker.predict;
    let inFlight = 0;
    worker.retired = false;
    worker.predict = async function (input) {
      if (this.retired) throw new Error("client is retiring");
      inFlight++;
      if (held) await gate;
      try { return await predict.call(this, input); } finally {
        inFlight--;
        if (this.retired && !inFlight) this.closed++;
      }
    };
    worker.closeWhenIdle = function () {
      this.retired = true;
      if (!inFlight) this.closed++;
    };
    workers.push(worker);
    return worker;
  }
  return { workers, createClient, release };
}

test("refresh retires a busy profile worker without failing its in-flight request", async (t) => {
  const registry = loadPolicy();
  const policy = { loadPolicy: () => registry, questionsFingerprint, resolveProfileId, selectProvider };
  const { workers, createClient, release } = gatedWorkers();
  const { service } = setup(t, { policy, createClient });
  const input = { state: "s", questions: loadBookmarkQuestions(), profile: V2 };
  const slow = service.ask(input);
  await new Promise((resolve) => setImmediate(resolve));
  const modelPath = registry.profiles[V2].runtime.modelPath;
  registry.profiles[V2].runtime.modelPath += "-updated";
  await service.ask(input);
  registry.profiles[V2].runtime.modelPath = modelPath;
  assert.equal(workers[0].retired, true);
  assert.equal(workers[0].closed, 0);
  release();
  assert.equal((await slow).provider, "laya");
  assert.equal(workers[0].closed, 1);
  await service.ask(input);
  assert.equal(workers.length, 3);
  assert.equal(workers[0].calls.length, 1);
  assert.equal(workers[2].calls.length, 1);
});

test("eviction retires a busy profile worker without failing its in-flight request", async (t) => {
  const registry = loadPolicy();
  for (const id of ["x1", "x2"]) {
    registry.profiles[id] = structuredClone(registry.profiles[V2]);
    registry.profiles[id].runtime.modelPath += `-${id}`;
  }
  const policy = { loadPolicy: () => registry, questionsFingerprint, resolveProfileId, selectProvider };
  const { workers, createClient, release } = gatedWorkers();
  const { service } = setup(t, { policy, createClient });
  const questions = loadBookmarkQuestions();
  const slow = service.ask({ state: "s", questions, profile: V2 });
  await new Promise((resolve) => setImmediate(resolve));
  // The clones fail the evidence check, but each worker is created before that gate.
  for (const profile of ["x1", "x2"]) await service.ask({ state: "s", questions, profile }).catch(() => {});
  assert.equal(workers[0].retired, true);
  assert.equal(workers[0].closed, 0);
  release();
  assert.equal((await slow).provider, "laya");
  assert.equal(workers[0].closed, 1);
  await service.ask({ state: "s", questions, profile: V2 });
  assert.equal(workers.length, 4);
  assert.equal(workers[3].calls.length, 1);
});
