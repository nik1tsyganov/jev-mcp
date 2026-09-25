import test from "node:test";
import assert from "node:assert/strict";

import { browserActionTool, createBrowserDecision } from "../src/browser-decision.js";
import { DEFAULT_MODEL } from "../src/client.js";

function input(overrides = {}) {
  return {
    goal: "submit the form",
    snapshotId: "snap-1",
    page: { url: "https://example.com/form", title: "Form", text: "A name field, a country picker and a submit button." },
    actions: [
      { id: "n1", operation: "CLICK", label: "Submit button" },
      { id: "n2", operation: "CLICK", label: "Cancel link" },
      { id: "n3", operation: "TYPE_TEXT", label: "Name field", value: "Ada" },
      { id: "n4", operation: "SELECT", label: "Country", value: "France" },
      { id: "n5", operation: "SCROLL_DOWN", label: "Scroll down" },
    ],
    recentActions: [{ operation: "CLICK", targetId: "n9", outcome: "opened the form" }],
    ...overrides,
  };
}

/** Valid choice answers for the compiled questions; selects `operation` and `target`. */
function validAnswers(questions, { operation = "CLICK", target = "a0" } = {}) {
  const answers = {};
  for (const [id, q] of Object.entries(questions)) {
    const labels = Object.keys(q.criteria);
    const pick = id === "operation" ? operation : target;
    const chosen = labels.includes(pick) ? pick : labels[0];
    const probabilities = {};
    for (const label of labels) {
      probabilities[label] = label === chosen ? (labels.length === 1 ? 1 : 0.8) : 0.2 / (labels.length - 1);
    }
    answers[id] = { type: "choice", choice: chosen, probabilities, confidence: 0.8 };
  }
  return answers;
}

/** A fake Jev ask that records calls and returns canned answers. */
function fakeDecisions(answersOrFn, resultOverrides = {}) {
  const calls = [];
  return {
    calls,
    ask: async (args) => {
      calls.push(args);
      return {
        model: "jev-1.13.0",
        answers: typeof answersOrFn === "function" ? answersOrFn(args.questions) : answersOrFn,
        usage: { input_tokens: 10, output_tokens: 4 },
        ...resultOverrides,
      };
    },
  };
}

test("the tool definition is a complete MCP schema named decision_browser_action", () => {
  assert.equal(browserActionTool.name, "decision_browser_action");
  assert.equal(browserActionTool.inputSchema.type, "object");
  assert.deepEqual(browserActionTool.inputSchema.required, ["goal", "snapshotId", "page", "actions"]);
  assert.equal(browserActionTool.inputSchema.additionalProperties, false);
  assert.deepEqual(
    browserActionTool.inputSchema.properties.actions.items.properties.operation.enum,
    ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN"]
  );
});

test("batches the operation question and one speculative head per candidate operation in one call", async () => {
  const decisions = fakeDecisions((questions) => validAnswers(questions));
  const decide = createBrowserDecision({ ask: decisions.ask });

  const res = await decide(input());

  assert.equal(decisions.calls.length, 1);
  const { state, questions, model } = decisions.calls[0];
  assert.deepEqual(
    Object.keys(questions),
    ["operation", "click_target", "type_text_target", "select_target", "scroll_down_target"]
  );
  assert.deepEqual(
    Object.keys(questions.operation.criteria),
    ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_DOWN", "WAIT", "DONE", "BLOCKED"]
  );
  assert.deepEqual(Object.keys(questions.click_target.criteria), ["a0", "a1"]);
  assert.deepEqual(Object.keys(questions.select_target.criteria), ["a3"]);
  assert.equal(model, DEFAULT_MODEL);
  assert.equal(state.snapshotId, "snap-1");
  assert.equal(state.page.url, "https://example.com/form");

  assert.equal(res.operation, "CLICK");
  assert.deepEqual(res.action, { id: "n1", operation: "CLICK", label: "Submit button" });
  assert.equal(res.model, "jev-1.13.0");
  assert.deepEqual(res.usage, { input_tokens: 10, output_tokens: 4 });
  assert.equal(res.snapshotId, "snap-1");
  assert.equal(res.advisory, true);
  assert.equal(res.requiresFreshObservation, true);
});

test("an explicit model is passed through unchanged", async () => {
  const decisions = fakeDecisions((questions) => validAnswers(questions));
  const decide = createBrowserDecision({ ask: decisions.ask, model: "jev-custom" });
  await decide(input());
  assert.equal(decisions.calls[0].model, "jev-custom");
});

test("WAIT, DONE and BLOCKED return a null action", async () => {
  for (const operation of ["WAIT", "DONE", "BLOCKED"]) {
    const decisions = fakeDecisions((questions) => validAnswers(questions, { operation }));
    const decide = createBrowserDecision({ ask: decisions.ask });
    const res = await decide(input());
    assert.equal(res.operation, operation);
    assert.equal(res.action, null);
  }
});

test("empty candidates still judge, with only terminal operations offered", async () => {
  const decisions = fakeDecisions((questions) => validAnswers(questions, { operation: "DONE" }));
  const decide = createBrowserDecision({ ask: decisions.ask });

  const res = await decide(input({ actions: [] }));

  assert.equal(decisions.calls.length, 1);
  assert.deepEqual(Object.keys(decisions.calls[0].questions), ["operation"]);
  assert.deepEqual(Object.keys(decisions.calls[0].questions.operation.criteria), ["WAIT", "DONE", "BLOCKED"]);
  assert.equal(res.operation, "DONE");
  assert.equal(res.action, null);
});

test("defects in unused speculative heads are ignored", async () => {
  const decisions = fakeDecisions((questions) => {
    const answers = validAnswers(questions, { operation: "CLICK", target: "a1" });
    answers.type_text_target = { type: "choice", choice: "bogus", probabilities: { bogus: 1 } };
    delete answers.scroll_down_target;
    return answers;
  });
  const decide = createBrowserDecision({ ask: decisions.ask });

  const res = await decide(input());

  assert.equal(res.operation, "CLICK");
  assert.deepEqual(res.action, { id: "n2", operation: "CLICK", label: "Cancel link" });
});

test("the selected target head is fully validated", async () => {
  const cases = {
    "missing head": (answers) => { delete answers.click_target; },
    "invented ref": (answers) => { answers.click_target.choice = "a9"; },
    "incomplete coverage": (answers) => { answers.click_target.probabilities = { a0: 1 }; },
    "out-of-range probability": (answers) => { answers.click_target.probabilities = { a0: 1.4, a1: -0.4 }; },
    "bad sum": (answers) => { answers.click_target.probabilities = { a0: 0.5, a1: 0.2 }; },
    "not argmax": (answers) => {
      answers.click_target.choice = "a0";
      answers.click_target.probabilities = { a0: 0.4, a1: 0.6 };
    },
    "invalid confidence": (answers) => { answers.click_target.confidence = 1.5; },
  };
  for (const [name, breakIt] of Object.entries(cases)) {
    const decisions = fakeDecisions((questions) => {
      const answers = validAnswers(questions, { operation: "CLICK" });
      breakIt(answers);
      return answers;
    });
    const decide = createBrowserDecision({ ask: decisions.ask });
    await assert.rejects(decide(input()), new RegExp("click_target"), name);
  }
});

test("the operation answer is validated the same way", async () => {
  const decisions = fakeDecisions((questions) => {
    const answers = validAnswers(questions, { operation: "CLICK" });
    answers.operation.probabilities = { CLICK: 2, TYPE_TEXT: 0, SELECT: 0, SCROLL_DOWN: 0, WAIT: 0, DONE: -1, BLOCKED: 0 };
    return answers;
  });
  const decide = createBrowserDecision({ ask: decisions.ask });
  await assert.rejects(decide(input()), /`operation`/);
});

test("missing model or usage evidence rejects the result", async () => {
  for (const resultOverrides of [
    { model: "" },
    { usage: null },
    { usage: { input_tokens: 1.5, output_tokens: 4 } },
  ]) {
    const decisions = fakeDecisions((questions) => validAnswers(questions), resultOverrides);
    const decide = createBrowserDecision({ ask: decisions.ask });
    await assert.rejects(decide(input()), /missing|evidence|usage/i);
  }
});

test("duplicate candidate ids are rejected before any judgment", async () => {
  const decisions = fakeDecisions({});
  const decide = createBrowserDecision({ ask: decisions.ask });
  const bad = input();
  bad.actions[1].id = "n1";
  await assert.rejects(decide(bad), /Duplicate action id `n1`/);
  assert.equal(decisions.calls.length, 0);
});

test("oversized and malformed inputs are rejected before any judgment", async () => {
  const decisions = fakeDecisions({});
  const decide = createBrowserDecision({ ask: decisions.ask });
  const cases = [
    input({ goal: "g".repeat(4001) }),
    input({ snapshotId: "s".repeat(129) }),
    input({ page: { url: "https://example.com", title: "t".repeat(1001), text: "x" } }),
    input({ page: { url: "https://example.com", title: "t", text: "x".repeat(16001) } }),
    input({ actions: [{ id: "i".repeat(129), operation: "CLICK", label: "x" }] }),
    input({ actions: [{ id: "a", operation: "CLICK", label: "x".repeat(1001) }] }),
    input({ actions: [{ id: "a", operation: "TYPE_TEXT", label: "x", value: "v".repeat(2001) }] }),
    input({ actions: Array.from({ length: 251 }, (_, i) => ({ id: `a${i}`, operation: "CLICK", label: "x" })) }),
    input({ recentActions: Array.from({ length: 11 }, () => ({ operation: "CLICK", outcome: "ok" })) }),
    input({ actions: [{ id: "a", operation: "CLICK", label: "x", value: "v".repeat(2000) }],
            page: { url: "https://example.com", title: "t", text: "x".repeat(16000) },
            goal: "g".repeat(4000), extraPad: undefined, snapshotId: "s".repeat(128),
            recentActions: [{ operation: "o".repeat(128), targetId: "t".repeat(128), outcome: "o".repeat(1000) }],
            pad: "p".repeat(190000) }),
    input({ goal: 42 }),
    input({ actions: "nope" }),
    input({ actions: [{ id: "a", operation: "NAVIGATE", label: "x" }] }),
    input({ actions: [{ id: "a", operation: "SELECT", label: "x" }] }),
    input({ actions: [{ id: "a", operation: "SELECT", label: "x", value: "" }] }),
    input({ unknownField: true }),
    input({ page: { url: "https://example.com", title: "t", text: "x", extra: 1 } }),
  ];
  for (const bad of cases) {
    await assert.rejects(decide(bad));
  }
  assert.equal(decisions.calls.length, 0);
});

test("the total serialized input cap is enforced", async () => {
  const decisions = fakeDecisions({});
  const decide = createBrowserDecision({ ask: decisions.ask });
  const big = input({ goal: "g".repeat(4000) });
  big.actions = Array.from({ length: 250 }, (_, i) => ({ id: `a${i}`, operation: "CLICK", label: "x".repeat(800) }));
  await assert.rejects(decide(big), /200000/);
  assert.equal(decisions.calls.length, 0);
});

test("non-http(s) and credentialed page URLs are rejected before any judgment", async () => {
  const decisions = fakeDecisions({});
  const decide = createBrowserDecision({ ask: decisions.ask });
  for (const url of [
    "ftp://example.com",
    "file:///etc/passwd",
    "https://user:pass@example.com/",
    "not a url",
    "javascript:alert(1)",
    42,
  ]) {
    await assert.rejects(decide(input({ page: { url, title: "t", text: "x" } })), /url|URL|string/);
  }
  assert.equal(decisions.calls.length, 0);
});

test("remoteAllowed is no longer an input field", async () => {
  const decisions = fakeDecisions({});
  const decide = createBrowserDecision({ ask: decisions.ask });
  await assert.rejects(decide(input({ remoteAllowed: false })), /Unknown field `remoteAllowed`/);
  assert.equal(decisions.calls.length, 0);
});

test("the returned snapshotId echoes the input exactly", async () => {
  const decisions = fakeDecisions((questions) => validAnswers(questions));
  const decide = createBrowserDecision({ ask: decisions.ask });
  const res = await decide(input({ snapshotId: "obs-2026-09-21-abc" }));
  assert.equal(res.snapshotId, "obs-2026-09-21-abc");
});

test("the action is a fresh copy carrying only observed candidate data", async () => {
  const decisions = fakeDecisions((questions) => validAnswers(questions, { operation: "SELECT", target: "a3" }));
  const decide = createBrowserDecision({ ask: decisions.ask });
  const inp = input();
  const res = await decide(inp);
  assert.deepEqual(res.action, { id: "n4", operation: "SELECT", label: "Country", value: "France" });
  assert.notEqual(res.action, inp.actions[3]);
  res.action.id = "mutated";
  assert.equal(inp.actions[3].id, "n4");
});

test("Jev refusals propagate unchanged", async () => {
  const decisions = {
    ask: async () => {
      throw new Error("No usable Jev credential.");
    },
  };
  const decide = createBrowserDecision({ ask: decisions.ask });
  await assert.rejects(decide(input()), /No usable Jev credential/);
});

test("invalid compiled answers are not retried or rerouted", async () => {
  const decisions = fakeDecisions(() => ({ operation: { type: "choice", choice: "EXPLODE", probabilities: {}, confidence: 0.5 } }));
  const decide = createBrowserDecision({ ask: decisions.ask });
  await assert.rejects(decide(input()), /`operation` selected an unknown option/);
  assert.equal(decisions.calls.length, 1);
});
