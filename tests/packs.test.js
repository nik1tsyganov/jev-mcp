import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { basename, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { validateQuestions } from "../src/questions.js";

const here = dirname(fileURLToPath(import.meta.url));
const packsDir = join(here, "..", "packs");
const packFileNames = readdirSync(packsDir)
  .filter((file) => file.endsWith(".json"))
  .sort();

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const REQUIRED_KEYS = [
  "name",
  "purpose",
  "corpus",
  "state_schema",
  "questions",
  "thresholds",
  "notes",
];

test("pack files exist in packs directory", () => {
  assert.ok(packFileNames.length > 0, "Expected at least one pack JSON file.");
});

test("1. each pack file parses as JSON and has required keys", () => {
  for (const file of packFileNames) {
    const raw = readFileSync(join(packsDir, file), "utf8");
    let pack;
    assert.doesNotThrow(
      () => {
        pack = JSON.parse(raw);
      },
      `${file} must parse as valid JSON`
    );

    assert.ok(isPlainObject(pack), `${file} root must be an object`);
    for (const key of REQUIRED_KEYS) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(pack, key),
        `${file} missing required key: "${key}"`
      );
    }
  }
});

test("2. pack name matches the filename stem", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    const stem = basename(file, ".json");
    assert.strictEqual(
      pack.name,
      stem,
      `${file}: pack.name "${pack.name}" does not match filename stem "${stem}"`
    );
  }
});

test("3. every question has type (noul|choice|score) and non-empty instructions", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    assert.ok(isPlainObject(pack.questions), `${file}: questions must be an object`);
    for (const [qid, q] of Object.entries(pack.questions)) {
      assert.ok(isPlainObject(q), `${file} [${qid}]: question must be an object`);
      assert.ok(
        ["noul", "choice", "score"].includes(q.type),
        `${file} [${qid}]: question type "${q.type}" must be noul, choice, or score`
      );
      assert.strictEqual(
        typeof q.instructions,
        "string",
        `${file} [${qid}]: instructions must be a string`
      );
      assert.ok(
        q.instructions.trim().length > 0,
        `${file} [${qid}]: instructions must be non-empty`
      );
    }
  }
});

test("4. criteria conforms to question type rules", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    for (const [qid, q] of Object.entries(pack.questions)) {
      if (q.type === "choice") {
        assert.ok(
          isPlainObject(q.criteria),
          `${file} [${qid}]: choice criteria must be a plain object`
        );
        assert.ok(
          Object.keys(q.criteria).length > 0,
          `${file} [${qid}]: choice criteria must not be empty`
        );
      } else if (q.type === "score") {
        assert.ok(
          Array.isArray(q.criteria),
          `${file} [${qid}]: score criteria must be an array`
        );
        assert.ok(
          q.criteria.length >= 2,
          `${file} [${qid}]: score criteria must have length >= 2`
        );
      } else if (q.type === "noul") {
        if (q.criteria !== undefined) {
          assert.ok(
            isPlainObject(q.criteria),
            `${file} [${qid}]: noul criteria must be a plain object`
          );
          const extra = Object.keys(q.criteria).filter(
            (k) => k !== "true" && k !== "false"
          );
          assert.strictEqual(
            extra.length,
            0,
            `${file} [${qid}]: noul criteria allows only 'true' and 'false'; got: ${extra.join(", ")}`
          );
        }
      }
    }
  }
});

test("5. no pack has more than 6 questions", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    const count = Object.keys(pack.questions).length;
    assert.ok(
      count <= 6,
      `${file}: has ${count} questions, exceeding maximum of 6`
    );
  }
});

test("6. every key in thresholds names a question that exists in that pack's questions", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    assert.ok(isPlainObject(pack.thresholds), `${file}: thresholds must be an object`);
    for (const thresholdKey of Object.keys(pack.thresholds)) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(pack.questions, thresholdKey),
        `${file}: threshold "${thresholdKey}" does not match any question in questions`
      );
    }
  }
});

test("7. validateQuestions does not throw on pack questions", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    assert.doesNotThrow(() => {
      validateQuestions(pack.questions);
    }, `${file}: validateQuestions threw on questions`);
  }
});
