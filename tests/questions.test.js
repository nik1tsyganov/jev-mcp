import test from "node:test";
import assert from "node:assert/strict";
import { noul, choice, score, validateQuestions } from "../src/questions.js";

test("1. noul with instructions only returns {type:'noul', instructions} and no criteria key", () => {
  const res = noul("Is this a production bug?");
  assert.deepStrictEqual(res, {
    type: "noul",
    instructions: "Is this a production bug?",
  });
  assert.strictEqual("criteria" in res, false);
  assert.strictEqual(Object.prototype.hasOwnProperty.call(res, "criteria"), false);
});

test("2. noul with {true, false} criteria keeps it", () => {
  const criteria = {
    true: "affects users in production",
    false: "only observed in local dev",
  };
  const res = noul("Is this a production bug?", criteria);
  assert.deepStrictEqual(res, {
    type: "noul",
    instructions: "Is this a production bug?",
    criteria,
  });
  assert.strictEqual(res.criteria, criteria);
});

test("2. noul with any other key throws and names the offending key", () => {
  assert.throws(
    () => noul("Is this a production bug?", { maybe: "not sure" }),
    (err) => {
      assert.match(err.message, /maybe/);
      return true;
    }
  );

  assert.throws(
    () =>
      noul("Is this a production bug?", {
        true: "yes",
        false: "no",
        extraKey: "unexpected",
      }),
    (err) => {
      assert.match(err.message, /extraKey/);
      return true;
    }
  );

  assert.throws(
    () => noul("Is this a production bug?", "not-an-object"),
    /must be an object with the keys `true` and `false`/
  );
});

test("3. choice throws when criteria is missing, is an array, or is an empty object", () => {
  assert.throws(() => choice("Pick a severity level"), /criteria/);
  assert.throws(() => choice("Pick a severity level", undefined), /criteria/);
  assert.throws(() => choice("Pick a severity level", ["sev1", "sev2"]), /criteria/);
  assert.throws(() => choice("Pick a severity level", {}), /criteria/);
  assert.throws(() => choice("Pick a severity level", null), /criteria/);
});

test("3. choice succeeds with a non-empty object", () => {
  const criteria = {
    p0: "outage",
    p1: "major degradation",
    p2: "minor issue",
  };
  const res = choice("Pick severity", criteria);
  assert.deepStrictEqual(res, {
    type: "choice",
    instructions: "Pick severity",
    criteria,
  });
});

test("4. score throws when criteria is missing, is an object, or is an array of length 1", () => {
  assert.throws(() => score("Score the impact"), /criteria/);
  assert.throws(() => score("Score the impact", undefined), /criteria/);
  assert.throws(() => score("Score the impact", { low: 1, high: 2 }), /criteria/);
  assert.throws(() => score("Score the impact", ["only-one-level"]), /criteria/);
  assert.throws(() => score("Score the impact", []), /criteria/);
  assert.throws(() => score("Score the impact", null), /criteria/);
});

test("4. score succeeds with two or more levels", () => {
  const twoLevels = ["low", "high"];
  const resTwo = score("Rate the risk", twoLevels);
  assert.deepStrictEqual(resTwo, {
    type: "score",
    instructions: "Rate the risk",
    criteria: twoLevels,
  });

  const fourLevels = ["trivial", "minor", "major", "critical"];
  const resFour = score("Rate severity", fourLevels);
  assert.deepStrictEqual(resFour, {
    type: "score",
    instructions: "Rate severity",
    criteria: fourLevels,
  });
});

test("5. every builder throws on empty or non-string instructions", () => {
  const invalidInstructions = ["", "   ", "\t\n", null, undefined, 123, true, {}, []];
  const builders = [
    { name: "noul", fn: (inst) => noul(inst) },
    { name: "choice", fn: (inst) => choice(inst, { a: "option" }) },
    { name: "score", fn: (inst) => score(inst, ["low", "high"]) },
  ];

  for (const { name, fn } of builders) {
    for (const inst of invalidInstructions) {
      assert.throws(
        () => fn(inst),
        { message: "`instructions` must be a non-empty string." },
        `Expected ${name} to throw for instructions: ${JSON.stringify(inst)}`
      );
    }
  }
});

test("6. validateQuestions rejects a non-object and an empty object", () => {
  assert.throws(() => validateQuestions(null), /must be a non-empty object/);
  assert.throws(() => validateQuestions(undefined), /must be a non-empty object/);
  assert.throws(() => validateQuestions("string"), /must be a non-empty object/);
  assert.throws(() => validateQuestions([1, 2]), /must be a non-empty object/);
  assert.throws(() => validateQuestions({}), /must be a non-empty object/);
});

test("6. validateQuestions rejects unknown type and includes question id in message", () => {
  assert.throws(
    () => validateQuestions({ q_unknown: { type: "multiselect", instructions: "Pick options" } }),
    (err) => {
      assert.match(err.message, /q_unknown/);
      assert.match(err.message, /multiselect/);
      return true;
    }
  );
});

test("6. validateQuestions rejects malformed questions and includes question id in message", () => {
  assert.throws(
    () => validateQuestions({ q_not_object: "invalid" }),
    (err) => {
      assert.match(err.message, /Question `q_not_object` must be an object\./);
      return true;
    }
  );

  assert.throws(
    () => validateQuestions({ q_empty_inst: { type: "noul", instructions: "" } }),
    (err) => {
      assert.match(err.message, /Question `q_empty_inst`:/);
      assert.match(err.message, /`instructions` must be a non-empty string\./);
      return true;
    }
  );

  assert.throws(
    () =>
      validateQuestions({
        q_bad_noul: {
          type: "noul",
          instructions: "Is valid?",
          criteria: { maybe: "bad key" },
        },
      }),
    (err) => {
      assert.match(err.message, /Question `q_bad_noul`:/);
      assert.match(err.message, /maybe/);
      return true;
    }
  );

  assert.throws(
    () =>
      validateQuestions({
        q_bad_choice: {
          type: "choice",
          instructions: "Pick one",
          criteria: {},
        },
      }),
    (err) => {
      assert.match(err.message, /Question `q_bad_choice`:/);
      return true;
    }
  );

  assert.throws(
    () =>
      validateQuestions({
        q_bad_score: {
          type: "score",
          instructions: "Score it",
          criteria: ["single level"],
        },
      }),
    (err) => {
      assert.match(err.message, /Question `q_bad_score`:/);
      return true;
    }
  );
});

test("6. validateQuestions returns a normalised copy for valid input", () => {
  const input = {
    noul_simple: {
      type: "noul",
      instructions: "Is this valid?",
    },
    noul_criteria: {
      type: "noul",
      instructions: "Is this critical?",
      criteria: { true: "yes", false: "no" },
    },
    choice_question: {
      type: "choice",
      instructions: "Choose route",
      criteria: { route_a: "description a", route_b: null },
    },
    score_question: {
      type: "score",
      instructions: "Score clarity",
      criteria: ["poor", "fair", "good"],
    },
  };

  const output = validateQuestions(input);
  assert.notStrictEqual(output, input);
  assert.deepStrictEqual(output, {
    noul_simple: {
      type: "noul",
      instructions: "Is this valid?",
    },
    noul_criteria: {
      type: "noul",
      instructions: "Is this critical?",
      criteria: { true: "yes", false: "no" },
    },
    choice_question: {
      type: "choice",
      instructions: "Choose route",
      criteria: { route_a: "description a", route_b: null },
    },
    score_question: {
      type: "score",
      instructions: "Score clarity",
      criteria: ["poor", "fair", "good"],
    },
  });
  assert.strictEqual("criteria" in output.noul_simple, false);
});
