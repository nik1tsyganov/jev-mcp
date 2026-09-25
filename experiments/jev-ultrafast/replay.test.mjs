import test from "node:test";
import assert from "node:assert/strict";
import {
  REPETITIONS,
  analyzeUpstream,
  canonical,
  normalizeInstructions,
  parseArgs,
  parseCaptures,
  planCalls,
  runJevComparison,
  runLayaReplay,
  selectStates,
  summarizeJev,
  summarizeLaya,
  validateChoiceAnswer,
} from "./replay.mjs";

// Fake-only fixtures: no fixture internals, no providers, no credentials.

function makeState(n) {
  return { page: { url: `https://example.test/${n}`, title: `t${n}`, text: "state text" }, elements: [], recent_actions: [] };
}

function makeQuestions() {
  return {
    operation: {
      type: "choice",
      instructions: { goal: "g", rules: "NEXT_ACTION" },
      criteria: { CLICK: "click", TYPE_TEXT: "type", DONE: "done" },
    },
    click_target: {
      type: "choice",
      instructions: { goal: "g", operation: "CLICK", rules: ["NEXT_ACTION", "TARGET"] },
      criteria: { 1: { element: "[1] a" }, 2: { element: "[2] b" } },
    },
    type_text_target: {
      type: "choice",
      instructions: { goal: "g", operation: "TYPE_TEXT", rules: ["NEXT_ACTION", "TARGET"] },
      criteria: { 3: { element: "[3] field" } },
    },
  };
}

function capture(id, n, overrides = {}) {
  return JSON.stringify({ id, task_id: `task-${n}`, state: makeState(n), questions: makeQuestions(), response: null, model: "m", latency_ms: n, ...overrides });
}

function validChoiceAnswer(ids, pick = ids[0]) {
  const p = 1 / ids.length;
  return {
    type: "choice",
    choice: pick,
    confidence: 0.9,
    probabilities: Object.fromEntries(ids.map((id) => [id, p])),
  };
}

function fakeAnswers(questions) {
  return Object.fromEntries(
    Object.entries(questions).map(([qid, q]) => [qid, validChoiceAnswer(Object.keys(q.criteria), qid === "operation" ? "CLICK" : undefined)])
  );
}

function fakeJev(calls, { failOn } = {}) {
  return async ({ state, questions }) => {
    const ids = Object.keys(questions);
    calls.push(ids);
    if (failOn && failOn(ids, calls.length)) throw new Error("boom");
    return { model: "jev-fake", answers: fakeAnswers(questions), usage: { input_tokens: 1, output_tokens: 1 } };
  };
}

test("parses captures and selects first 12 distinct state/questions hashes in order", () => {
  const lines = [capture("a", 1), capture("a-dup", 1), ...Array.from({ length: 13 }, (_, i) => capture(`s${i}`, i + 2))];
  const parsed = parseCaptures(lines.join("\n"));
  const states = selectStates(parsed, 12);
  assert.equal(states.length, 12);
  assert.equal(states[0].id, "a");
  assert.equal(states[1].id, "s0"); // the duplicate hash row is skipped
  assert.ok(states.every((s, i) => i === 0 || states[i - 1].line < s.line));
  // Captured objects are preserved untouched.
  assert.equal(states[0].questions.operation.instructions.goal, "g");
  assert.equal(typeof states[0].normalizedQuestions.operation.instructions, "string");
});

test("invalid records are retained as rows and excluded from selection", () => {
  const parsed = parseCaptures([capture("a", 1), JSON.stringify({ id: "bad", state: {} }), capture("b", 2)].join("\n"));
  assert.equal(parsed[1].invalid, "missing questions");
  const states = selectStates(parsed, 12);
  assert.deepEqual(states.map((s) => s.id), ["a", "b"]);
  assert.throws(() => parseCaptures("{not json"), /Line 1: invalid JSON/);
});

test("normalization is deterministic and touches only object instructions", () => {
  const a = makeQuestions();
  const b = makeQuestions();
  b.operation.instructions = { rules: "NEXT_ACTION", goal: "g" }; // same content, different key order
  const na = normalizeInstructions(a);
  const nb = normalizeInstructions(b);
  assert.equal(na.questions.operation.instructions, nb.questions.operation.instructions);
  assert.equal(na.questions.click_target.instructions, canonical({ goal: "g", operation: "CLICK", rules: ["NEXT_ACTION", "TARGET"] }));
  assert.equal(na.changed, 3);
  const already = { q: { type: "noul", instructions: "already a string" } };
  assert.equal(normalizeInstructions(already).changed, 0);
  assert.equal(normalizeInstructions(already).questions.q.instructions, "already a string");
  // Original is never mutated.
  assert.equal(typeof a.operation.instructions, "object");
});

test("plan reports exact call counts per provider", () => {
  const states = selectStates(parseCaptures([capture("a", 1), capture("b", 2)].join("\n")), 12);
  const jev = planCalls(states, "jev");
  assert.equal(jev.jevCalls, REPETITIONS * (2 + 2 * 3)); // 3 reps x (1 batch + 3 sequential) x 2 states
  assert.equal(jev.layaCalls, 0);
  const laya = planCalls(states, "laya");
  assert.equal(laya.layaCalls, 2);
  assert.equal(laya.jevCalls, 0); // provider isolation: laya mode plans zero Jev calls
  assert.equal(laya.repetitions, 1);
});

test("jev comparison issues exact call counts with alternating pairing", async () => {
  const states = selectStates(parseCaptures([capture("a", 1)].join("\n")), 12);
  const calls = [];
  const pairs = await runJevComparison({ states, systemOne: fakeJev(calls), now: fakeClock() });
  assert.equal(pairs.length, REPETITIONS);
  assert.equal(calls.length, REPETITIONS * (1 + 3));
  // Rep 1 batch-first: one call with all 3 question ids, then three single-question calls.
  assert.deepEqual(calls[0], ["operation", "click_target", "type_text_target"]);
  assert.deepEqual(calls[1], ["operation"]);
  assert.deepEqual(calls[3], ["type_text_target"]);
  // Rep 2 sequential-first.
  assert.deepEqual(pairs[1].order, ["sequential", "batch"]);
  assert.deepEqual(calls[4], ["operation"]);
  assert.deepEqual(calls[7], ["operation", "click_target", "type_text_target"]);
  // Each pair holds exactly one batch arm and one sequential arm.
  for (const p of pairs) {
    assert.equal(p.batch.calls.length, 1);
    assert.equal(p.sequential.calls.length, 3);
  }
  const summary = summarizeJev(pairs);
  assert.equal(summary.callsAttempted, calls.length);
  assert.equal(summary.callsFailed, 0);
  assert.equal(summary.operationAgreementRate, 1);
  assert.equal(summary.selectedTargetAgreementRate, 1);
});

test("failed calls stay in rows and denominators", async () => {
  const states = selectStates(parseCaptures([capture("a", 1)].join("\n")), 12);
  const calls = [];
  // Fail every single-question call for click_target.
  const jev = fakeJev(calls, { failOn: (ids) => ids.length === 1 && ids[0] === "click_target" });
  const pairs = await runJevComparison({ states, systemOne: jev, now: fakeClock() });
  const summary = summarizeJev(pairs);
  assert.equal(summary.callsAttempted, calls.length);
  assert.equal(summary.callsFailed, REPETITIONS);
  const failed = pairs.flatMap((p) => p.sequential.calls.filter((c) => !c.ok));
  assert.equal(failed.length, REPETITIONS);
  assert.equal(failed[0].questionId, "click_target");
  assert.match(failed[0].error, /boom/);
  // A failed sequential head leaves that arm's selected head unvalidated, not silently absent.
  assert.equal(pairs[0].sequential.answers.click_target, undefined);
});

test("upstream analysis validates only the selected target head", () => {
  const questions = normalizeInstructions(makeQuestions()).questions;
  const answers = fakeAnswers(questions);
  answers.operation = validChoiceAnswer(["CLICK", "TYPE_TEXT", "DONE"], "CLICK");
  answers.click_target = validChoiceAnswer(["1", "2"], "2");
  answers.type_text_target = { type: "choice", choice: "nope", confidence: 2, probabilities: { 3: 5 } }; // malformed speculative head
  const analysis = analyzeUpstream(questions, answers);
  assert.equal(analysis.operation, "CLICK");
  assert.equal(analysis.operationValid, true);
  assert.equal(analysis.selectedHeadId, "click_target");
  assert.equal(analysis.selectedHeadValid, true);
  assert.equal(analysis.selectedTarget, "2");
  // DONE carries no target head upstream.
  const done = analyzeUpstream(questions, { ...answers, operation: validChoiceAnswer(["CLICK", "TYPE_TEXT", "DONE"], "DONE") });
  assert.equal(done.selectedHeadId, null);
  // An invalid operation fails the row upstream rather than degrading quietly.
  const bad = analyzeUpstream(questions, { ...answers, operation: { type: "choice", choice: "CLICK" } });
  assert.equal(bad.operationValid, false);
  assert.equal(bad.operation, null);
});

test("validateChoiceAnswer ports upstream semantics", () => {
  const ids = ["1", "2"];
  assert.equal(validateChoiceAnswer(validChoiceAnswer(ids, "2"), ids), true);
  assert.equal(validateChoiceAnswer({ ...validChoiceAnswer(ids), choice: "9" }, ids), false);
  assert.equal(validateChoiceAnswer({ ...validChoiceAnswer(ids), probabilities: { 1: 1 } }, ids), false); // coverage
  assert.equal(validateChoiceAnswer({ ...validChoiceAnswer(ids), probabilities: { 1: 0.8, 2: 0.8 } }, ids), false); // sum
  assert.equal(validateChoiceAnswer({ ...validChoiceAnswer(ids), probabilities: { 1: 0.4, 2: 0.6 }, choice: "1" }, ids), false); // argmax
  assert.equal(validateChoiceAnswer({ ...validChoiceAnswer(ids), confidence: 1.5 }, ids), false);
  assert.equal(validateChoiceAnswer(null, ids), false);
});

test("laya replay calls only the local client and records compatibility", async () => {
  const states = selectStates(parseCaptures([capture("a", 1), capture("b", 2)].join("\n")), 12);
  const predictCalls = [];
  const err = new Error("question 'operation': input would be truncated to the 1024-token model budget");
  err.code = "input_truncated";
  const client = {
    calls: predictCalls,
    status: () => ({ available: true, checkpoint: "ckpt", revision: "rev", reason: null }),
    predict: async ({ state, questions }) => {
      predictCalls.push({ state, questions });
      if (predictCalls.length === 2) throw err;
      return {
        model: "ckpt@rev",
        checkpoint: "ckpt",
        revision: "rev",
        answers: fakeAnswers(questions),
        usage: { input_tokens: 10, output_tokens: 0 },
        elapsed_ms: 2.5,
      };
    },
    close: () => {},
  };
  const { status, rows } = await runLayaReplay({ states, client, now: fakeClock() });
  assert.equal(predictCalls.length, 2); // exactly one predict per selected state
  // Identical normalized payloads: instructions arrive as strings.
  assert.equal(typeof predictCalls[0].questions.operation.instructions, "string");
  assert.equal(rows[0].ok, true);
  assert.equal(rows[0].checkpointMatch, true);
  assert.equal(rows[0].schemaCompatible, true);
  assert.equal(rows[0].heads.operation.upstreamValid, true);
  assert.equal(rows[0].heads.operation.argmaxAligned, true);
  assert.equal(rows[1].ok, false);
  assert.equal(rows[1].errorCode, "input_truncated");
  const summary = summarizeLaya({ rows });
  assert.equal(summary.attempted, 2);
  assert.equal(summary.succeeded, 1);
  assert.equal(summary.truncationRejections, 1);
  assert.equal(summary.firstCallMs, rows[0].durationMs);
  assert.equal(summary.warmMs.length, 0); // the only warm call failed, so no warm sample
  assert.equal(status.checkpoint, "ckpt");
});

test("provider isolation: laya mode has no Jev path and unknown providers are rejected", () => {
  assert.throws(() => parseArgs(["--input", "x.jsonl", "--provider", "other"]), /Unknown provider/);
  assert.equal(parseArgs(["--input", "x.jsonl"]).provider, "jev");
  assert.equal(parseArgs(["--input", "x.jsonl", "--provider", "laya"]).provider, "laya");
  // runLayaReplay takes no Jev injectable; this is structural isolation —
  // the only inference surface is the passed client's predict.
});

function fakeClock() {
  let t = 0;
  return () => (t += 1);
}


test("timing includes awaited inference work", async () => {
  const states = selectStates(parseCaptures(capture("timing", 1)), 1);
  let clock = 0;
  const pairs = await runJevComparison({states, now: () => clock,
    systemOne: async ({questions}) => {
      await Promise.resolve();
      clock += 37;
      return {model: "fake", answers: fakeAnswers(questions)};
    }});
  assert.equal(pairs[0].batch.wallMs, 37);
  assert.equal(pairs[0].sequential.wallMs, 111);
  assert.equal(pairs[0].latencyDeltaMs, 74);
});


test("selected sequential baseline asks only operation and its chosen target", async () => {
  const states = selectStates(parseCaptures(capture("selected", 1)), 1);
  const calls = [];
  const pairs = await runJevComparison({states, systemOne: fakeJev(calls), sequentialMode: "selected"});
  assert.equal(calls.length, REPETITIONS * 3);
  for (const pair of pairs) {
    assert.deepEqual(pair.sequential.calls.map(c => c.questionId), ["operation", "click_target"]);
    assert.equal(pair.agreement.operation, true);
    assert.equal(pair.agreement.selectedTarget, true);
  }
});
